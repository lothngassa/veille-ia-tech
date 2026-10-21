"""Orchestration : collecte -> analyse -> brief Claude -> mise en page -> envoi -> mémoire."""

from __future__ import annotations

import html
import logging
import math
import socket
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from . import telegram
from .analyze import (analyze, mark_watched, pick_essentials, sector_pulse, sectors_per_day, select, trend_arrow,
                      watch_matches, watchlist_items)
from .brief_ai import AIError, generate_brief, history_record
from .config import parse_send_time
from .fetch import fetch_all
from .render import Edition, fr_date, render
from .sources import Source, load_sources
from .state import State, load_history, prune_history, save_history

log = logging.getLogger(__name__)


class CollectError(Exception):
    """La collecte n'a pas donné assez de matière pour un brief fiable (souvent : pas de connexion)."""


@dataclass
class Outcome:
    edition: Edition
    messages: list[str]
    seen_keys: list[str]
    story_tokens: list[frozenset]
    history: dict


# --------------------------------------------------------------------------- Calendrier

def due_edition(now_local: datetime, send_time: str) -> date:
    """L'édition attendue : celle d'aujourd'hui si l'heure d'envoi est passée, sinon celle d'hier."""
    hour, minute = parse_send_time(send_time)
    scheduled = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now_local.date() if now_local >= scheduled else now_local.date() - timedelta(days=1)


def edition_to_send(now_local: datetime, send_time: str, last_edition: date | None,
                    catch_up: bool) -> tuple[date | None, str]:
    """Décide s'il faut envoyer une édition maintenant (et laquelle), avec l'explication pour le journal.

    - Après l'heure d'envoi : l'édition du jour, si elle n'est pas déjà partie.
    - Avant l'heure d'envoi : l'édition d'hier seulement si elle a été manquée (PC éteint) et que le
      rattrapage est activé. Sur une installation toute neuve, on attend simplement la première heure d'envoi.
    """
    due = due_edition(now_local, send_time)
    if last_edition and last_edition >= due:
        return None, f"Édition du {due} déjà envoyée"
    if due < now_local.date():
        if last_edition is None:
            return None, f"Première installation : premier envoi automatique à {send_time}"
        if not catch_up:
            return None, f"Édition du {due} manquée, rattrapage désactivé"
        return due, f"Rattrapage de l'édition du {due} (PC éteint à l'heure prévue)"
    return due, f"Envoi de l'édition du {due}"


def window_start(last_sent: datetime | None, now: datetime, cfg: dict) -> datetime:
    """Tout depuis le dernier envoi, avec un minimum (24 h) et un maximum (7 jours par défaut)."""
    lo, hi = cfg["fenetre_heures"]["min"], cfg["fenetre_heures"]["max"]
    hours = lo if last_sent is None else (now - last_sent).total_seconds() / 3600
    return now - timedelta(hours=min(max(hours, lo), hi))


def wait_for_network(timeout: float = 600, host: str = "api.telegram.org") -> bool:
    """Au démarrage du PC, le Wi-Fi met parfois une minute à se connecter : on patiente."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            socket.create_connection((host, 443), timeout=5).close()
            return True
        except OSError:
            if time.monotonic() > deadline:
                return False
            time.sleep(15)


# --------------------------------------------------------------------------- Construction

def watchlist_sources(cfg: dict, days: int) -> list[Source]:
    if not cfg.get("watchlist_google_news"):
        return []
    sources = []
    for item in watchlist_items(cfg.get("watchlist", [])):
        q = quote(f"{item.query} when:{days}d")
        sources.append(Source(
            name=f"Google News · {item.name}", url=f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
            region="monde", country="", lang="en", weight=0.8, kind="agregateur", publisher=f"Google News · {item.name}",
            targeted=True,
        ))
    return sources


def build_edition(cfg: dict, state: State, now_local: datetime, edition_day: date, use_ai: bool = True,
                  progress=lambda msg: None) -> Outcome:
    started = time.monotonic()
    now = now_local.astimezone(timezone.utc)
    since = window_start(state.last_sent_at, now, cfg)
    days = max(1, math.ceil((now - since).total_seconds() / 86400))

    # Les recherches Google News « when:1d » s'élargissent à toute la période en cas de rattrapage.
    sources = [replace(s, url=s.url.replace("when:1d", f"when:{days}d")) for s in load_sources()]
    sources += watchlist_sources(cfg, days)
    progress(f"Collecte de {len(sources)} sources…")
    results = fetch_all(sources)

    ok = sum(1 for r in results if r.ok)
    if ok < max(5, len(sources) // 5):
        # Mieux vaut ne rien envoyer qu'un brief vide ou bancal : la connexion a sans doute lâché.
        raise CollectError(f"seulement {ok} source(s) sur {len(sources)} ont répondu (connexion internet ?)")

    progress("Analyse et regroupement des sujets…")
    analysis = analyze(results, since, now, state.seen_keys(), state.recent_tokens())
    if not analysis.stories:
        raise CollectError("aucun article nouveau depuis le dernier envoi")
    history = load_history(edition_day)
    pulses = sector_pulse(analysis, history)
    ai_trend = trend_arrow(analysis.ai_share, [h["part_ia"] for h in history if "part_ia" in h])
    watch_items = watchlist_items(cfg.get("watchlist", []))
    mark_watched(analysis.stories, watch_items)
    edition_label = fr_date(now_local.date())
    compact = cfg.get("format", "court") != "complet"

    brief, ai_error = None, None
    if use_ai and cfg["ia"]["active"]:
        progress("Analyse éditoriale par Claude…")
        try:
            brief = generate_brief(analysis, pulses, watch_items, history, cfg, edition_label, now,
                                   include_world=not compact)
        except AIError as e:
            ai_error = str(e)
            log.warning("Brief IA indisponible : %s", e)
        except Exception as e:  # le brief automatique doit partir même si l'analyse IA plante
            ai_error = f"erreur inattendue ({type(e).__name__})"
            log.exception("Erreur inattendue pendant l'analyse IA")

    top, world = _choose_stories(analysis, brief, cfg["selection"], compact)
    window_hours = (now - since).total_seconds() / 3600
    edition = Edition(
        day=now_local.date(),
        now=now_local,
        analysis=analysis,
        pulses=pulses,
        ai_share_trend=ai_trend,
        top=top,
        world=world,
        watch=watch_matches(analysis.stories, watch_items),
        brief=brief,
        ai_error=ai_error,
        catchup_since=since.astimezone(now_local.tzinfo) if window_hours > 30 else None,
        total_sources=len(sources),
        compact=compact,
    )
    edition.elapsed = time.monotonic() - started
    messages = render(edition)

    shown = list(top) + [s for entries in world.values() for s, _ in entries]
    if brief and brief.underdog:
        shown.append(brief.underdog[0])
    seen = [a.key for s in shown for a in s.articles]
    seen += [a.key for a in analysis.all_articles if a.published is None]  # flux sans dates : ne pas les resservir
    record = history_record(edition_label, brief, [s.lead.title for s in top], sectors_per_day(analysis))
    record["part_ia"] = round(analysis.ai_share, 3)
    return Outcome(edition, messages, seen, [s.lead.tokens for s in shown], record)


def _choose_stories(analysis, brief, sel: dict, compact: bool):
    """(sujets principaux, tour du monde) selon le mode : Claude, court ou complet."""
    if brief:
        return [item.story for item in brief.items], ({} if compact else brief.world)
    if compact:
        top = pick_essentials(analysis.stories, int(sel["min"]), int(sel["habituel"]), int(sel["max"]),
                              int(sel["max_par_source"]))
        return top, {}
    selection = select(analysis.stories, int(sel["habituel"]), int(sel["par_region"]), int(sel["max_par_source"]))
    return selection.top, {k: [(s, s.lead.title) for s in v] for k, v in selection.regions.items()}


# --------------------------------------------------------------------------- Envoi

def deliver(cfg: dict, state: State, outcome: Outcome, edition_day: date, sent_at: datetime) -> None:
    tg = cfg["telegram"]
    telegram.send_messages(tg["token"], tg["chat_id"], outcome.messages)
    state.record_edition(edition_day, sent_at, outcome.seen_keys, outcome.story_tokens)
    state.save()
    save_history(edition_day, outcome.history)
    prune_history(sent_at.date())
    log.info("Édition du %s envoyée : %d message(s)", edition_day, len(outcome.messages))


def notify_failure(cfg: dict, error: str) -> None:
    """Prévient sur Telegram quand l'envoi automatique échoue (si Telegram est joignable)."""
    tg = cfg["telegram"]
    try:
        telegram.send_message(tg["token"], tg["chat_id"],
                              f"⚠️ <b>Veille IA &amp; Tech</b> : l'édition n'a pas pu être générée.\n"
                              f"<i>{html.escape(error[:300])}</i>\nDétails : logs/veille.log")
    except telegram.TelegramError:
        pass
