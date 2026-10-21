"""Mise en page des messages Telegram (HTML) et de l'aperçu local."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from .analyze import Analysis, Article, Pulse, Story, display_article, title_tokens
from .brief_ai import AIBrief, model_name
from .regions import REGIONS, flag

LINE = "━━━━━━━━━━━━━━━━━━"
MAX_UNITS = 3900  # limite Telegram : 4096 caractères (UTF-16) après mise en forme ; marge de sécurité
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
RELIABILITY_ICON = {"source primaire": "🏛️", "confirmé": "✅", "source unique": "🔸", "à confirmer": "⚠️"}


# --------------------------------------------------------------------------- Outils

def esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{esc(text)}</a>'


def fr_date(d: date) -> str:
    day = "1er" if d.day == 1 else str(d.day)
    return f"{JOURS[d.weekday()]} {day} {MOIS[d.month - 1]} {d.year}"


def num(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", " ")


def bar(value: float, maximum: float, width: int = 10) -> str:
    """Barre de progression ; toute valeur non nulle affiche au moins un bloc."""
    filled = 0
    if maximum > 0 and value > 0:
        filled = min(width, max(1, round(width * value / maximum)))
    return "█" * filled + "░" * (width - filled)


def telegram_length(text: str) -> int:
    """Longueur comptée par Telegram : texte visible, en unités UTF-16."""
    visible = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(visible.encode("utf-16-le")) // 2


def _period(hours: float) -> str:
    if hours <= 26:
        return "dernières 24 h"
    if hours < 44:
        return f"dernières {round(hours)} h"
    return f"derniers {round(hours / 24)} jours"


def duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60} min {seconds % 60:02d} s" if seconds >= 60 else f"{seconds} s"


def source_tag(story: Story) -> str:
    lead = story.lead
    extra = f" · +{story.coverage - 1}" if story.coverage > 1 else ""
    return f"<i>{esc(lead.source)} {flag(lead.country)}{extra}</i>"


def source_links(story: Story, limit: int = 3, first: Article | None = None) -> str:
    """Liens vers les meilleurs articles du sujet (source primaire d'abord), un par média."""
    seen, parts = set(), []
    for art in ([first] if first else []) + story.articles:
        if art.publisher in seen:
            continue
        seen.add(art.publisher)
        label = f"{art.publisher} (officiel)" if art.kind == "primaire" else art.publisher
        parts.append(link(art.url, label))
        if len(parts) >= limit:
            break
    more = story.coverage - len(parts)
    if more <= 0:
        return " · ".join(parts)
    return " · ".join(parts) + f" <i>+{more} média{'s' if more > 1 else ''}</i>"


def folded(content: str) -> str:
    """Bloc repliable Telegram : on voit les premières lignes, un appui déplie le reste."""
    return f"<blockquote expandable>{content}</blockquote>"


def section(title: str) -> str:
    return f"{LINE}\n<b>{esc(title)}</b>\n{LINE}"


# --------------------------------------------------------------------------- Contexte d'édition

@dataclass
class Edition:
    day: date
    now: datetime
    analysis: Analysis
    pulses: list[Pulse]
    ai_share_trend: str
    top: list[Story]                                  # mode sans IA : sujets principaux
    world: dict[str, list[tuple[Story, str]]]         # région -> [(sujet, titre affiché)]
    watch: dict[str, tuple[int, list[Story]]]
    brief: AIBrief | None = None
    ai_error: str | None = None
    catchup_since: datetime | None = None             # rattrapage : début de la période couverte
    elapsed: float = 0.0
    total_sources: int = 0
    extra_notes: list[str] = field(default_factory=list)
    compact: bool = True  # format « court » : seulement les sujets qui comptent


# --------------------------------------------------------------------------- Blocs

def _rising(ed: Edition) -> str:
    """« En hausse : Agents IA ↑↑ · Robotique ↑ » (seulement quand l'historique permet de comparer)."""
    up = [p for p in ed.pulses if p.trend in ("↑↑", "↑")][:3]
    return " · ".join(f"{p.label} {p.trend}" for p in up)


def header_block(ed: Edition) -> str:
    a = ed.analysis
    retained = len(ed.brief.items) if ed.brief else len(ed.top)
    lines = [
        LINE,
        "<b>AI · TECH BRIEF</b>",
        f"<b>{esc(fr_date(ed.day).upper())}</b> · {ed.now:%H:%M}",
        LINE,
        f"<i>{num(a.funnel.collected)} articles · {a.sources_ok} sources · 7 régions · {_period(a.window_hours)}</i>",
        f"<b>→ les {retained} sujets qui comptent</b>",
    ]
    if ed.catchup_since:
        lines.append(f"⏪ <i>Rattrapage : tout depuis {esc(fr_date(ed.catchup_since.date()))} "
                     f"{ed.catchup_since:%H:%M}</i>")
    if ed.compact and _rising(ed):
        lines.append(f"📈 <i>En hausse : {esc(_rising(ed))}</i>")
    if ed.brief and ed.brief.one_liner:
        lines += ["", "💬 <b>En une phrase</b>", f"<i>{esc(ed.brief.one_liner)}</i>"]
    return "\n".join(lines)


def pulse_block(ed: Edition) -> str:
    if not ed.pulses:
        return ""
    top = max(p.per_day for p in ed.pulses)
    rows = [f"{p.label:<12}{bar(p.per_day, top)} {p.trend:<2} {num(p.count):>4}" for p in ed.pulses]
    share = f"IA : {ed.analysis.ai_share:.0%} des articles {ed.ai_share_trend}"
    return "<b>POULS DU SECTEUR</b>\n<pre>" + esc(share + "\n" + "\n".join(rows)) + "</pre>"


def _deep_dive(item) -> str:
    d = item.deep
    parts = ["🔎 <b>ANALYSE APPROFONDIE</b>"]
    if d.get("contexte"):
        parts.append(f"<b>Pourquoi maintenant</b>\n{esc(d['contexte'])}")
    if d.get("impact"):
        parts.append(f"<b>Impact</b>\n{esc(d['impact'])}")
    if d.get("scenarios"):
        parts.append("<b>Ce qui pourrait suivre</b>\n" + "\n".join(f"{i}. {esc(s)}" for i, s in
                                                                 enumerate(d["scenarios"], start=1)))
    if d.get("risques"):
        parts.append(f"<b>Risques</b>\n{esc(d['risques'])}")
    if d.get("opportunites"):
        parts.append(f"<b>Opportunités</b>\n{esc(d['opportunites'])}")
    if d.get("avis"):
        parts.append(f"<b>L'avis de Claude</b>\n{esc(d['avis'])}")
    return folded("\n\n".join(parts)) if len(parts) > 1 else ""


def ai_item_block(rank: int, item) -> str:
    story = item.story
    lines = [f"<b>{rank:02d} · {esc(item.actor or 'TECH')}</b>", f"<b>{esc(item.title)}</b>", ""]
    if item.facts:
        lines.append(esc(item.facts))
    if item.why:
        lines.append(f"\n▸ <b>Pourquoi c'est important</b> — {esc(item.why)}")
    if item.affected:
        lines.append(f"▸ <b>Concernés</b> — {esc(' · '.join(item.affected))}")
    if item.watch:
        lines.append(f"▸ <b>À surveiller</b> — {esc(item.watch)}")
    reliability = ""
    if item.reliability:
        icon = RELIABILITY_ICON.get(item.reliability, "")
        reliability = f" · {icon} {esc(item.reliability)}"
    lines.append(f"\n<code>{bar(item.importance, 10)}</code> <b>{item.importance:.1f}</b>/10"
                 f"{reliability} · {story.coverage} média{'s' if story.coverage > 1 else ''}")
    lines.append(f"🔗 {source_links(story)}")
    deep = _deep_dive(item)
    if deep:
        lines.append(deep)
    return "\n".join(lines)


def rule_item_block(rank: int, story: Story) -> str:
    """Un sujet sans IA : titre (en français si un média francophone le couvre), extrait, sources."""
    art = display_article(story)
    lines = [f"<b>{rank}.</b> {story.emoji} <b>{link(art.url, art.title)}</b>"]
    summary = art.summary or story.lead.summary
    if summary:
        lines.append(f"<i>{esc(summary)}</i>")
    lines.append(f"{flag(art.country)} {source_links(story, first=art)}")
    return "\n".join(lines)


def signal_block(brief: AIBrief) -> str:
    sig = brief.signal
    if not sig.get("titre"):
        return ""
    lines = [section("LE SIGNAL"), f"<b>{esc(sig['titre'].upper())}</b>"]
    lines += [f"→ {esc(p)}" for p in sig.get("preuves", [])]
    if sig.get("interpretation"):
        lines += ["", f"<i>{esc(sig['interpretation'])}</i>"]
    return "\n".join(lines)


def underdog_block(brief: AIBrief) -> str:
    if not brief.underdog:
        return ""
    story, title, why = brief.underdog
    lines = [section("L'OUTSIDER"), f"{story.emoji} <b>{link(story.lead.url, title or story.lead.title)}</b>",
             source_tag(story)]
    if why:
        lines.append(esc(why))
    return "\n".join(lines)


def changes_block(brief: AIBrief) -> str:
    if not brief.changes:
        return ""
    lines = [section("DEPUIS HIER")]
    lines += [f"{'＋' if sign == '+' else '－'} {esc(text)}" for sign, text in brief.changes]
    return "\n".join(lines)


def take_block(brief: AIBrief) -> str:
    parts = []
    if brief.take:
        parts += [section("L'ANALYSE DE CLAUDE"), esc(brief.take)]
    w = brief.watch
    if any(w.values()):
        parts += ["", section("À SURVEILLER")]
        for label, key in (("24 h", "h24"), ("7 j", "j7"), ("30 j", "j30")):
            if w.get(key):
                parts.append(f"<b>{label}</b> → {esc(w[key])}")
    return "\n".join(parts).strip()


def world_blocks(ed: Edition) -> list[str]:
    blocks = ["🌍 <b>TOUR DU MONDE</b>\n<i>Touche une région pour la déplier.</i>"]
    for key, (label, emoji) in REGIONS.items():
        entries = ed.world.get(key, [])
        count = ed.analysis.region_counts.get(key, 0)
        rows = [f"{s.emoji} {link(s.lead.url, title)} — {source_tag(s)}" for s, title in entries]
        body = "\n".join(rows) or "<i>Rien de marquant aujourd'hui.</i>"
        blocks.append(folded(f"{emoji} <b>{esc(label.upper())}</b> · {num(count)} articles\n{body}"))
    return blocks


def watch_block(ed: Edition) -> str:
    if not ed.watch:
        return ""
    rows = ["📌 <b>TA WATCHLIST</b>"]
    for name, (count, stories) in ed.watch.items():
        if not count:
            rows.append(f"<b>{esc(name)}</b> · <i>rien aujourd'hui</i>")
            continue
        rows.append(f"<b>{esc(name)}</b> · {count} article{'s' if count > 1 else ''}")
        rows += [f"  • {link(s.lead.url, s.lead.title)} — {source_tag(s)}" for s in stories]
    return folded("\n".join(rows))


def pick_videos(videos: list[Article], limit: int = 5) -> list[Article]:
    """Une vidéo par chaîne maximum, sans quasi-doublons (ex. la même annonce déclinée par pays)."""
    out: list[Article] = []
    channels: set[str] = set()
    seen_tokens: list[frozenset] = []
    for v in videos:
        tokens = title_tokens(v.title)
        if v.source in channels or any(len(tokens & t) >= max(2, len(tokens) // 2) for t in seen_tokens):
            continue
        out.append(v)
        channels.add(v.source)
        seen_tokens.append(tokens)
        if len(out) >= limit:
            break
    return out


def videos_block(ed: Edition) -> str:
    videos = pick_videos(ed.analysis.videos)
    if not videos:
        return ""
    rows = ["🎬 <b>À REGARDER</b>"]
    rows += [f"▶️ {link(v.url, v.title)} — <i>{esc(v.source)}</i>" for v in videos]
    return folded("\n".join(rows))


def _funnel_rows(ed: Edition) -> list[str]:
    """L'entonnoir : combien d'articles à chaque étape, chiffres alignés."""
    a, f = ed.analysis, ed.analysis.funnel
    steps = [
        (f.collected, f"articles collectés ({a.sources_ok}/{ed.total_sources} sources)"),
        (f.duplicates, "doublons fusionnés"),
        (f.off_topic, "promos et hors-sujet"),
        (f.already_sent, "déjà envoyés"),
        (f.stories, "sujets uniques"),
        (ed.brief.candidates if ed.brief else 0, "analysés par Claude"),
        (len(ed.brief.items) if ed.brief else len(ed.top), "retenus pour le brief"),
    ]
    width = len(num(f.collected))
    return [f"<code>{num(n):>{width}}</code> {label}" for n, label in steps if n or label.startswith("retenus")]


def _engine_note(ed: Edition) -> str:
    if ed.brief:
        cost = f" · ≈ {ed.brief.cost_usd:.2f} $".replace(".", ",") if ed.brief.cost_usd is not None else ""
        return f"Analyse : {esc(model_name(ed.brief.model))}{cost}"
    if ed.ai_error:
        return f"Analyse IA indisponible ({esc(ed.ai_error)}) : brief automatique."
    return "Mode automatique (sans IA)"


def backstage_block(ed: Edition) -> str:
    rows = ["⚙️ <b>COULISSES</b>", *_funnel_rows(ed)]
    failed = ed.analysis.sources_failed
    if failed:
        shown = ", ".join(failed[:6]) + (" …" if len(failed) > 6 else "")
        rows.append(f"\n<i>Indisponibles : {esc(shown)}</i>")
    rows.append(f"<i>{_engine_note(ed)}</i>")
    rows.append(f"<i>Généré en {duration(ed.elapsed)}</i>")
    rows += [f"<i>{esc(n)}</i>" for n in ed.extra_notes]
    return folded("\n".join(rows))


# --------------------------------------------------------------------------- Assemblage

def build_blocks(ed: Edition) -> list[str]:
    """Format court : en-tête, les sujets qui comptent, (analyse Claude), coulisses repliées.
    Format complet : ajoute le pouls, le tour du monde, la watchlist et les vidéos."""
    blocks = [header_block(ed)]
    if not ed.compact:
        blocks.append(pulse_block(ed))
    if ed.brief:
        blocks.append(section("L'ESSENTIEL"))
        blocks += [ai_item_block(i, item) for i, item in enumerate(ed.brief.items, start=1)]
        blocks += [signal_block(ed.brief), take_block(ed.brief)]
        if not ed.compact:
            blocks += [underdog_block(ed.brief), changes_block(ed.brief)]
    else:
        blocks += [rule_item_block(i, s) for i, s in enumerate(ed.top, start=1)]
    if not ed.compact:
        blocks += world_blocks(ed)
        blocks += [watch_block(ed), videos_block(ed)]
    blocks.append(backstage_block(ed))
    return [b for b in blocks if b and b.strip()]


_OPEN_TAG = re.compile(r"<(blockquote(?: expandable)?|pre)>")


def _tag_open_after(line: str, open_tag: str | None) -> str | None:
    """Balise blockquote/pre encore ouverte après cette ligne."""
    for m in _OPEN_TAG.finditer(line):
        open_tag = m.group(1)
    if open_tag and f"</{open_tag.split()[0]}>" in line:
        return None
    return open_tag


def _split_oversized(block: str) -> list[str]:
    """Coupe un bloc trop long entre deux lignes, en refermant puis rouvrant blockquote/pre si besoin."""
    pieces: list[str] = []
    current, open_tag = "", None
    for line in block.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if current and telegram_length(candidate) > MAX_UNITS:
            pieces.append(current + (f"</{open_tag.split()[0]}>" if open_tag else ""))
            candidate = (f"<{open_tag}>" if open_tag else "") + line
        current = candidate
        open_tag = _tag_open_after(line, open_tag)
    if current:
        pieces.append(current)
    return pieces


def pack_messages(blocks: list[str]) -> list[str]:
    """Regroupe les blocs en messages sous la limite Telegram, sans jamais couper un bloc s'il tient entier."""
    messages, current = [], ""
    for block in blocks:
        parts = [block] if telegram_length(block) <= MAX_UNITS else _split_oversized(block)
        for part in parts:
            candidate = f"{current}\n\n{part}" if current else part
            if current and telegram_length(candidate) > MAX_UNITS:
                messages.append(current)
                current = part
            else:
                current = candidate
    if current:
        messages.append(current)
    return messages


def render(ed: Edition) -> list[str]:
    return pack_messages(build_blocks(ed))


# --------------------------------------------------------------------------- Aperçu local

def preview_html(messages: list[str], title: str) -> str:
    """Page HTML qui imite l'affichage Telegram, pour vérifier la mise en page sans rien envoyer."""
    bubbles = "\n".join(
        f'<div class="bubble">{_preview_message(m)}<span class="meta">{i}/{len(messages)}</span></div>'
        for i, m in enumerate(messages, start=1)
    )
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
:root {{ --bg:#e6ebee; --bubble:#fff; --text:#0f1419; --muted:#6b7a86; --link:#2a7ab8; --quote:#2a7ab8;
        --code:#f1f3f5; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0e1621; --bubble:#182533; --text:#e9eef2; --muted:#8a9aa9;
        --link:#6ab3f3; --quote:#6ab3f3; --code:#0f1b27; }} }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.45 -apple-system, "Segoe UI", Roboto,
        sans-serif; }}
main {{ max-width:560px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:13px; font-weight:600; color:var(--muted); text-align:center; margin:0 0 16px; }}
.bubble {{ background:var(--bubble); border-radius:14px; padding:10px 14px 18px; margin:0 0 10px;
          white-space:pre-wrap; word-wrap:break-word; position:relative; box-shadow:0 1px 1px rgba(0,0,0,.08); }}
.meta {{ position:absolute; right:10px; bottom:4px; font-size:11px; color:var(--muted); }}
a {{ color:var(--link); text-decoration:none; }}
pre, code {{ font:13px/1.35 ui-monospace, Consolas, monospace; background:var(--code); border-radius:6px; }}
pre {{ padding:8px; margin:4px 0; white-space:pre; overflow-x:auto; }}
code {{ padding:0 3px; }}
blockquote {{ margin:6px 0; padding:4px 10px; border-left:3px solid var(--quote); border-radius:4px;
             background:color-mix(in srgb, var(--quote) 8%, transparent); }}
details > summary {{ cursor:pointer; color:var(--link); list-style:none; }}
</style></head><body><main><h1>{esc(title)} · aperçu</h1>
{bubbles}
</main></body></html>"""


def _preview_message(message: str) -> str:
    # Les blocs repliables de Telegram deviennent des <details> dépliables dans l'aperçu.
    def fold(m: re.Match) -> str:
        body = m.group(1)
        first, _, rest = body.partition("\n")
        return f"<blockquote><details><summary>{first}</summary>{rest}</details></blockquote>"

    return re.sub(r"<blockquote expandable>(.*?)</blockquote>", fold, message, flags=re.S)
