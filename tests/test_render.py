import unittest
from datetime import timedelta
from html.parser import HTMLParser

from tests.helpers import NOW, item, result, source
from veille.analyze import analyze, sector_pulse, select, watch_matches, watchlist_items
from veille.brief_ai import AIError, parse_brief
from veille.render import (MAX_UNITS, Edition, bar, fr_date, pack_messages, render, telegram_length)

ALLOWED = {"b", "i", "a", "code", "pre", "blockquote", "u", "s"}


class TelegramHtml(HTMLParser):
    """Vérifie que le HTML respecte le sous-ensemble Telegram et que les balises sont bien imbriquées."""

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED:
            self.errors.append(f"balise interdite <{tag}>")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> inattendu")
        else:
            self.stack.pop()


def assert_valid(test, message):
    checker = TelegramHtml()
    checker.feed(message)
    checker.close()
    test.assertEqual(checker.errors + checker.stack, [], message[:300])
    test.assertLessEqual(telegram_length(message), 4096)


def sample_analysis():
    results = [
        result(source("TechCrunch", "amerique_nord", "US", 1.3),
               item("OpenAI unveils GPT-7 <reasoning> & agents", summary="Un résumé & des <détails>."),
               item("Nvidia stock rallies after earnings")),
        result(source("BBC", "europe", "GB", 1.3), item("OpenAI launches GPT-7 reasoning model")),
        result(source("TechCabal", "afrique", "NG"), item("Flutterwave raises $100M to expand in Egypt")),
        result(source("Inc42", "asie", "IN"), item("Indian AI startup Sarvam releases open-weight model")),
        result(source("YouTube", "monde", kind="video"), item("This changes everything")),
    ]
    return analyze(results, NOW - timedelta(hours=24), NOW, set(), [])


def edition(analysis, brief=None, compact=True):
    sel = select(analysis.stories, 5, 5, 2)
    world = brief.world if brief else {k: [(s, s.lead.title) for s in v] for k, v in sel.regions.items()}
    items = watchlist_items(["OpenAI", "Mistral"])
    return Edition(day=NOW.date(), now=NOW, analysis=analysis, pulses=sector_pulse(analysis, []),
                   ai_share_trend="·", top=[i.story for i in brief.items] if brief else sel.top, world=world,
                   watch=watch_matches(analysis.stories, items), brief=brief, total_sources=5, elapsed=12.3,
                   compact=compact)


class RenderTest(unittest.TestCase):
    def test_short_format_lists_only_the_essentials(self):
        messages = render(edition(sample_analysis()))
        for m in messages:
            assert_valid(self, m)
        text = "\n".join(messages)
        self.assertIn("&lt;reasoning&gt; &amp; agents", text)  # échappement HTML
        self.assertIn("sujets qui comptent", text)
        self.assertIn("Mode automatique (sans IA)", text)
        for absent in ("TOUR DU MONDE", "WATCHLIST", "À REGARDER", "POULS DU SECTEUR"):
            self.assertNotIn(absent, text)

    def test_full_format_is_valid_telegram_html(self):
        messages = render(edition(sample_analysis(), compact=False))
        for m in messages:
            assert_valid(self, m)
        text = "\n".join(messages)
        for present in ("TOUR DU MONDE", "WATCHLIST", "POULS DU SECTEUR"):
            self.assertIn(present, text)

    def test_ai_edition_is_valid_and_uses_only_known_links(self):
        analysis = sample_analysis()
        ids = {f"S{i}": s for i, s in enumerate(analysis.stories, start=1)}
        data = {
            "en_une_phrase": "Une phrase <forte>.",
            "sujets": [{"id": "S1", "acteur": "openai", "titre": "OpenAI dévoile GPT-7", "faits": "Faits.",
                        "pourquoi": "Parce que.", "concernes": ["Développeurs"], "importance": 12,
                        "fiabilite": "confirmé", "a_surveiller": "La suite.",
                        "approfondi": {"contexte": "C", "impact": "I", "scenarios": ["a", "b", "c"],
                                       "risques": "R", "opportunites": "O", "avis": "A"}},
                       {"id": "S99", "acteur": "X", "titre": "Inventé", "faits": "", "pourquoi": "", "concernes": [],
                        "importance": 5, "fiabilite": "confirmé", "a_surveiller": "", "approfondi": {}},
                       {"id": "S1", "acteur": "doublon", "titre": "Doublon", "faits": "", "pourquoi": "",
                        "concernes": [], "importance": 5, "fiabilite": "confirmé", "a_surveiller": "",
                        "approfondi": {}}],
            "signal": {"titre": "Les agents montent", "preuves": ["p1", "p2"], "interpretation": "i"},
            "outsider": {"id": "S2", "titre": "Peu repris", "pourquoi": "Car."},
            "changements": [{"sens": "+", "texte": "Nouveau"}],
            "analyse": "Analyse.",
            "surveiller": {"h24": "a", "j7": "b", "j30": "c"},
            "monde": {"afrique": [{"id": "S3", "titre": "Flutterwave lève 100 M$"}, {"id": "S1", "titre": "dup"}]},
        }
        brief = parse_brief(data, ids, max_items=5, per_region=5)
        self.assertEqual([i.title for i in brief.items], ["OpenAI dévoile GPT-7"])  # S99 inconnu, S1 en double
        self.assertEqual(brief.items[0].importance, 10.0)
        self.assertEqual(brief.items[0].actor, "OPENAI")
        self.assertEqual([t for _, t in brief.world["afrique"]], ["Flutterwave lève 100 M$"])
        brief.model, brief.cost_usd = "claude-opus-5-5", 0.12
        messages = render(edition(analysis, brief, compact=False))
        for m in messages:
            assert_valid(self, m)
        text = "\n".join(messages)
        self.assertIn("<blockquote expandable>🔎 <b>ANALYSE APPROFONDIE</b>", text)
        self.assertIn("Claude Opus 5.5 · ≈ 0,12 $", text)
        self.assertNotIn("Inventé", text)

    def test_brief_without_valid_story_is_rejected(self):
        with self.assertRaises(AIError):
            parse_brief({"sujets": [{"id": "S404"}]}, {}, 5, 5)


class PackingTest(unittest.TestCase):
    def test_messages_respect_limit_and_keep_blocks_whole(self):
        blocks = [f"<b>Bloc {i}</b>\n" + "x" * 900 for i in range(10)]
        messages = pack_messages(blocks)
        self.assertGreater(len(messages), 1)
        for m in messages:
            self.assertLessEqual(telegram_length(m), MAX_UNITS)
        self.assertEqual("\n\n".join(messages), "\n\n".join(blocks))

    def test_oversized_blockquote_is_split_and_rebalanced(self):
        block = "<blockquote expandable>" + "\n".join("ligne " + "y" * 80 for _ in range(120)) + "</blockquote>"
        messages = pack_messages([block])
        self.assertGreater(len(messages), 1)
        for m in messages:
            assert_valid(self, m)

    def test_emoji_count_double_like_telegram(self):
        self.assertEqual(telegram_length("<b>🌍</b> a&amp;b"), 2 + 1 + 3)


class FormatTest(unittest.TestCase):
    def test_french_date(self):
        self.assertEqual(fr_date(NOW.date()), "mardi 20 octobre 2026")
        self.assertEqual(fr_date(NOW.date().replace(day=1)), "jeudi 1er octobre 2026")

    def test_bar(self):
        self.assertEqual(bar(5, 10), "█████░░░░░")
        self.assertEqual(bar(0.1, 10), "█░░░░░░░░░")  # valeur non nulle : au moins un bloc
        self.assertEqual(bar(0, 10), "░" * 10)


if __name__ == "__main__":
    unittest.main()
