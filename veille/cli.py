"""Commandes : python veille.py <commande>"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
import time
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler

from . import __version__, net, pipeline, scheduler, telegram
from .config import (CONFIG_PATH, LOG_DIR, LOG_PATH, PREVIEW_PATH, TASK_NAME, ConfigError, load_config,
                     telegram_ready)
from .fetch import fetch_all
from .render import preview_html
from .sources import load_sources
from .state import AlreadyRunning, State, single_instance

log = logging.getLogger("veille")
AUTO_ATTEMPTS = 3
AUTO_RETRY_DELAY = 300  # secondes entre deux tentatives en mode automatique


def say(text: str = "") -> None:
    """print() sans planter sous pythonw.exe (pas de console)."""
    if sys.stdout:
        print(text, flush=True)


def setup_logging(interactive: bool) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s : %(message)s"))
    root.addHandler(file_handler)
    if interactive and sys.stderr:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.WARNING)
        console.setFormatter(logging.Formatter("⚠ %(message)s"))
        root.addHandler(console)


def _config_or_exit() -> dict:
    try:
        return load_config()
    except ConfigError as e:
        say(f"✘ {e}")
        raise SystemExit(2) from None


def _require_telegram(cfg: dict) -> None:
    if not telegram_ready(cfg):
        say("✘ Telegram n'est pas configuré. Lance d'abord : python veille.py configurer")
        raise SystemExit(2)


def _plain(message: str) -> str:
    """Version console d'un message Telegram : texte brut, liens en fin de ligne."""
    text = re.sub(r'<a href="([^"]+)">(.*?)</a>', lambda m: m.group(2), message)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


# --------------------------------------------------------------------------- Commandes

def cmd_configure(_args) -> int:
    from . import setup_wizard
    return setup_wizard.run()


def cmd_preview(args) -> int:
    cfg = _config_or_exit()
    state = State()
    now = datetime.now().astimezone()
    edition = pipeline.due_edition(now, cfg["heure_envoi"])
    outcome = pipeline.build_edition(cfg, state, now, edition, use_ai=not args.sans_ia, progress=say)
    PREVIEW_PATH.write_text(preview_html(outcome.messages, "AI · TECH BRIEF"), encoding="utf-8")
    if not args.silencieux:
        for i, message in enumerate(outcome.messages, start=1):
            say(f"\n──────── message {i}/{len(outcome.messages)} ────────\n")
            say(_plain(message))
    say(f"\n✔ Aperçu enregistré : {PREVIEW_PATH}")
    if not args.sans_ouvrir:
        webbrowser.open(PREVIEW_PATH.as_uri())
    return 0


def cmd_send(_args) -> int:
    """Envoi manuel immédiat (compte comme l'édition du jour : la tâche planifiée ne la renverra pas)."""
    cfg = _config_or_exit()
    _require_telegram(cfg)
    try:
        with single_instance():
            state = State()
            now = datetime.now().astimezone()
            edition = pipeline.due_edition(now, cfg["heure_envoi"])
            outcome = pipeline.build_edition(cfg, state, now, edition, progress=say)
            say(f"Envoi de {len(outcome.messages)} message(s) sur Telegram…")
            pipeline.deliver(cfg, state, outcome, edition, now)
    except AlreadyRunning as e:
        say(f"✘ {e}")
        return 1
    except telegram.TelegramError as e:
        say(f"✘ Envoi Telegram impossible : {e}")
        return 1
    say("✔ Brief envoyé.")
    return 0


def cmd_auto(_args) -> int:
    """Lancé par la tâche planifiée : envoie l'édition due si elle ne l'a pas déjà été."""
    cfg = _config_or_exit()
    if not telegram_ready(cfg):
        log.error("Telegram n'est pas configuré : python veille.py configurer")
        return 2
    try:
        with single_instance():
            return _auto(cfg)
    except AlreadyRunning as e:
        log.info("Rien à faire : %s", e)
        return 0


def _auto(cfg: dict) -> int:
    state = State()
    now = datetime.now().astimezone()
    due, reason = pipeline.edition_to_send(now, cfg["heure_envoi"], state.last_edition, cfg["rattrapage"])
    log.info(reason)
    if due is None:
        return 0
    if not pipeline.wait_for_network():
        log.error("Pas de connexion internet après 10 minutes d'attente")
        return 1
    return _send_with_retries(cfg, state, now, due)


def _send_with_retries(cfg: dict, state: State, now: datetime, due) -> int:
    for attempt in range(1, AUTO_ATTEMPTS + 1):
        try:
            outcome = pipeline.build_edition(cfg, state, now, due)
            pipeline.deliver(cfg, state, outcome, due, datetime.now().astimezone())
            return 0
        except (pipeline.CollectError, telegram.TelegramError) as e:
            # Souvent passager (Wi-Fi qui décroche, Telegram momentanément injoignable) : on réessaie.
            log.warning("Tentative %d/%d échouée : %s", attempt, AUTO_ATTEMPTS, e)
            if attempt < AUTO_ATTEMPTS:
                time.sleep(AUTO_RETRY_DELAY)
                pipeline.wait_for_network()
                continue
            pipeline.notify_failure(cfg, str(e))
        except Exception as e:
            log.exception("Échec de l'édition automatique")
            pipeline.notify_failure(cfg, f"{type(e).__name__} : {e}")
            break
    return 1


def cmd_test(_args) -> int:
    cfg = _config_or_exit()
    _require_telegram(cfg)
    try:
        me = telegram.get_me(cfg["telegram"]["token"])
        telegram.send_message(cfg["telegram"]["token"], cfg["telegram"]["chat_id"],
                              "🧪 <b>Test</b> : la connexion à Telegram fonctionne.")
    except telegram.TelegramError as e:
        say(f"✘ {e}")
        return 1
    say(f"✔ Message de test envoyé par @{me['username']}.")
    return 0


def cmd_sources(_args) -> int:
    """Teste chaque source et affiche un tableau d'état."""
    sources = load_sources()
    say(f"Test de {len(sources)} sources…\n")
    results = fetch_all(sources)
    now = datetime.now().astimezone()
    ok = 0
    for r in sorted(results, key=lambda r: (r.ok, r.source.region, r.source.name)):
        if r.ok:
            ok += 1
            dated = [i.published for i in r.items if i.published]
            fresh = sum(1 for d in dated if (now - d).total_seconds() < 86400)
            age = f"{(now - max(dated)).total_seconds() / 3600:5.0f} h" if dated else "    —"
            say(f"  ✔ {r.source.name:<32} {r.source.region:<16} {len(r.items):>4} articles · {fresh:>3} sur 24 h"
                f" · dernier il y a {age}")
        else:
            say(f"  ✘ {r.source.name:<32} {r.source.region:<16} {r.error}")
    say(f"\n{ok}/{len(results)} sources fonctionnent.")
    return 0 if ok else 1


def cmd_install(_args) -> int:
    cfg = _config_or_exit()
    try:
        scheduler.install(cfg["heure_envoi"])
        info = scheduler.status() or {}
    except scheduler.SchedulerError as e:
        say(f"✘ {e}")
        return 1
    say(f"✔ Tâche « {TASK_NAME} » installée : chaque jour à {cfg['heure_envoi']}, et au démarrage de session "
        f"si un envoi a été manqué.\n  Prochaine exécution : {info.get('next_run', '?')}")
    return 0


def cmd_uninstall(_args) -> int:
    try:
        removed = scheduler.uninstall()
    except scheduler.SchedulerError as e:
        say(f"✘ {e}")
        return 1
    say("✔ Tâche planifiée supprimée." if removed else "Aucune tâche planifiée à supprimer.")
    return 0


def cmd_status(_args) -> int:
    cfg = _config_or_exit()
    state = State()
    token = cfg["telegram"]["token"]
    say(f"Veille IA & Tech v{__version__}\n")
    say(f"  Configuration   : {CONFIG_PATH}")
    say(f"  Telegram        : {'✔ configuré' if telegram_ready(cfg) else '✘ à configurer'}"
        + (f" (token …{token[-4:]}, chat {cfg['telegram']['chat_id']})" if token else ""))
    say(f"  Heure d'envoi   : {cfg['heure_envoi']} · rattrapage {'activé' if cfg['rattrapage'] else 'désactivé'}")
    ia = cfg["ia"]
    say(f"  Analyse Claude  : {'✔ ' + ia['modele'] + ' (effort ' + ia['effort'] + ')' if ia['active'] else '✘ désactivée'}")
    say(f"  Watchlist       : {', '.join((w if isinstance(w, str) else w.get('nom', '?')) for w in cfg['watchlist'])}")
    say(f"  Sources         : {len(load_sources())} flux (+ {len(cfg['watchlist'])} recherches watchlist)")
    last = state.last_sent_at.strftime("%d/%m/%Y %H:%M") if state.last_sent_at else "jamais"
    say(f"  Dernier envoi   : {last}")
    if sys.platform == "win32":
        say(f"  Tâche planifiée : {_task_summary()}")
    say(f"  Journal         : {LOG_PATH}")
    return 0


def _task_summary() -> str:
    try:
        info = scheduler.status()
    except scheduler.SchedulerError as e:
        return f"✘ état illisible ({e})"
    if not info:
        return "✘ non installée (python veille.py installer)"
    code = info.get("last_result")
    labels = {0: "succès", 267011: "jamais lancée"}  # 267011 : la tâche n'a encore jamais tourné
    result = labels.get(code, f"code {code}") if isinstance(code, int) else "inconnu"
    return (f"✔ {info.get('state')} · prochaine : {info.get('next_run') or '?'}"
            f" · dernière : {info.get('last_run') or 'jamais'} ({result})")


COMMANDS = {
    "configurer": (cmd_configure, "assistant d'installation (Telegram, Claude, tâche planifiée)"),
    "apercu": (cmd_preview, "génère le brief sans l'envoyer et l'ouvre dans le navigateur"),
    "envoyer": (cmd_send, "génère et envoie le brief maintenant"),
    "tester": (cmd_test, "envoie un message de test sur Telegram"),
    "sources": (cmd_sources, "vérifie que chaque flux répond"),
    "statut": (cmd_status, "affiche la configuration et l'état de la tâche planifiée"),
    "installer": (cmd_install, "crée/met à jour la tâche planifiée Windows"),
    "desinstaller": (cmd_uninstall, "supprime la tâche planifiée"),
    "auto": (cmd_auto, "mode tâche planifiée (envoie l'édition due, sinon ne fait rien)"),
}


def main(argv: list[str] | None = None) -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="veille.py",
        description="Veille IA & Tech : le brief quotidien de l'actualité mondiale de l'IA et de la tech, sur Telegram.",
        epilog="Pour commencer : python veille.py configurer",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="commande")
    for name, (_, desc) in COMMANDS.items():
        p = sub.add_parser(name, help=desc, description=desc)
        if name == "apercu":
            p.add_argument("--sans-ia", action="store_true", help="ne pas appeler Claude (gratuit)")
            p.add_argument("--sans-ouvrir", action="store_true", help="ne pas ouvrir le navigateur")
            p.add_argument("--silencieux", action="store_true", help="ne pas afficher le brief dans la console")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    setup_logging(interactive=args.command != "auto")
    net.install()
    log.info("Commande : %s", args.command)
    handler = COMMANDS[args.command][0]
    try:
        return handler(args)
    except KeyboardInterrupt:
        say("\nInterrompu.")
        return 130
    except SystemExit:
        raise
    except Exception:
        log.exception("Erreur inattendue")
        say(f"✘ Erreur inattendue : détails dans {LOG_PATH}")
        return 1
