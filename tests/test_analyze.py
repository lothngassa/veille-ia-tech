import unittest
from datetime import timedelta

from tests.helpers import NOW, item, result, source
from veille.analyze import (analyze, clean_url, display_article, is_ai_text, pick_essentials, sectors_of, select,
                            title_tokens, trend_arrow, url_key, watch_matches, watchlist_items)
from veille.regions import detect_regions, flag, resolve_region
from veille.sources import Source


def run(*results, seen=(), recent=()):
    return analyze(list(results), NOW - timedelta(hours=24), NOW, set(seen), list(recent))


class UrlTest(unittest.TestCase):
    def test_tracking_parameters_removed(self):
        self.assertEqual(clean_url("https://a.com/x?utm_source=rss&id=3&fbclid=9#top"), "https://a.com/x?id=3")

    def test_same_article_same_key(self):
        self.assertEqual(url_key("https://www.a.com/x/?utm_medium=feed"), url_key("https://a.com/x"))


class ClassificationTest(unittest.TestCase):
    def test_sectors(self):
        self.assertIn("agents", sectors_of("Anthropic ships new MCP connectors for AI agents"))
        self.assertIn("puces", sectors_of("TSMC to build a new chip plant"))
        self.assertIn("financement", sectors_of("La startup lève 20 millions en série A"))
        self.assertNotIn("mobile", sectors_of("Une robe orange pour l'été"))

    def test_ai_detection_avoids_french_false_positive(self):
        self.assertFalse(is_ai_text("J'ai testé le nouveau vélo électrique", []))
        self.assertTrue(is_ai_text("L'IA générative arrive dans Excel", []))
        self.assertTrue(is_ai_text("AI-powered search goes live", []))

    def test_tokens_ignore_accents_and_stopwords(self):
        self.assertEqual(title_tokens("Les Échos de l'économie"), frozenset({"echo", "economie"}))


class RegionTest(unittest.TestCase):
    def test_detection(self):
        self.assertEqual(detect_regions("Nigerian fintech raises $20M"), ["afrique"])
        self.assertEqual(detect_regions("Latin American startups and the US market")[0], "amerique_latine")
        self.assertNotIn("amerique_nord", detect_regions("La scène tech latino-américaine"))

    def test_resolve(self):
        self.assertEqual(resolve_region("amerique_nord", "Kenya's Safaricom launches AI service"), "afrique")
        self.assertEqual(resolve_region("europe", "Mistral signs deal with US firm"), "europe")
        self.assertEqual(resolve_region("monde", "Generic headline"), "monde")
        self.assertEqual(resolve_region("monde", "Generic", "A deal in Brazil"), "amerique_latine")

    def test_flag(self):
        self.assertEqual(flag("FR"), "🇫🇷")
        self.assertEqual(flag(""), "🌐")


class ClusteringTest(unittest.TestCase):
    def test_same_story_across_outlets_is_merged(self):
        a = result(source("BBC", "europe", "GB", 1.3), item("OpenAI unveils GPT-7 with deeper reasoning"))
        b = result(source("The Verge", "amerique_nord", "US", 1.3), item("OpenAI launches GPT-7, its new reasoning model"))
        c = result(source("Le Monde", "europe", "FR", 1.3), item("Apple prépare un iPhone pliable pour 2027"))
        analysis = run(a, b, c)
        self.assertEqual(len(analysis.stories), 2)
        top = analysis.stories[0]
        self.assertEqual(top.coverage, 2)
        self.assertIn("GPT-7", top.lead.title)

    def test_bridge_article_does_not_chain_two_stories(self):
        musk = [item(t) for t in (
            "Elon Musk will give a SpaceX share to every kid in America",
            "Musk pledges SpaceX share to every American child next year",
            "Every kid in America to get a SpaceX share, says Musk",
        )]
        bridge = item("Anthropic plans fund for workers, Musk commits SpaceX shares to kids")
        anthropic = [item(t) for t in (
            "Anthropic commits 5% of shares to public benefit fund",
            "Anthropic pledges 5% of its shares to a public-good fund",
        )]
        results = [result(source(f"M{i}", "amerique_nord", "US"), it) for i, it in enumerate(musk + [bridge] + anthropic)]
        analysis = run(*results)
        for story in analysis.stories:
            titles = " ".join(a.title for a in story.articles)
            self.assertFalse("every kid" in titles.lower() and "public benefit" in titles.lower(),
                             f"fusion en chaîne : {titles}")

    def test_wire_copies_count_once(self):
        wire = "AI agents are only as good as the personal information you share"
        copies = [result(source(f"Local paper {i}", "amerique_nord", "US", 0.6), item(wire, f"https://p{i}.com/x"))
                  for i in range(10)]
        original = result(source("Reuters", "monde", "", 1.3), item("Nvidia unveils Rubin chips at GTC Paris"))
        second = result(source("BBC", "europe", "GB", 1.3), item("Nvidia's new Rubin chips unveiled in Paris"))
        analysis = run(*copies, original, second)
        wire_story = next(s for s in analysis.stories if "personal information" in s.lead.title)
        self.assertEqual(wire_story.coverage, 10)
        self.assertLess(wire_story.independent_coverage, 1.0)
        self.assertIn("Rubin", analysis.stories[0].lead.title)  # 2 médias indépendants > 10 copies d'une dépêche

    def test_noise_and_already_sent_are_filtered(self):
        src = source("Clubic", "europe", "FR")
        sent = item("Le Conseil d'État valide la loi sur l'IA", "https://clubic.com/ia")
        analysis = run(result(src, item("Black Friday : les meilleures offres sur les SSD"), sent,
                              item("Mistral AI lève 2 milliards d'euros")),
                       seen={url_key("https://clubic.com/ia")})
        self.assertEqual([s.lead.title for s in analysis.stories], ["Mistral AI lève 2 milliards d'euros"])
        self.assertEqual(analysis.funnel.off_topic, 1)
        self.assertEqual(analysis.funnel.already_sent, 1)

    def test_old_articles_are_outside_window(self):
        analysis = run(result(source("A"), item("Ancien article sur l'IA générative", hours_ago=30),
                              item("Nouvel article sur l'IA générative", hours_ago=1)))
        self.assertEqual(len(analysis.stories), 1)

    def test_generalist_source_keeps_only_tech(self):
        src = source("Nikkei", "asie", "JP", kind="generaliste")
        analysis = run(result(src, item("Toyota posts record quarterly profit"),
                              item("SoftBank invests in AI chip startup")))
        self.assertEqual(len(analysis.stories), 1)

    def test_targeted_searches_do_not_bias_statistics(self):
        normal = result(source("TechCrunch", "amerique_nord", "US"), item("TSMC opens new chip fab in Arizona"))
        targeted = result(source("Google News · Agents", "monde", kind="agregateur", targeted=True),
                          item("AI agents everywhere - Site", source_name="Site"),
                          item("Agentic AI wave - Other", source_name="Other"))
        analysis = run(normal, targeted)
        self.assertEqual(analysis.sector_counts.get("agents", 0), 0)
        self.assertEqual(analysis.sector_counts["puces"], 1)

    def test_google_news_title_and_reputation(self):
        gn = result(source("Google News Kenya", "afrique", "KE", 0.8, kind="agregateur"),
                    item("Microsoft signs a big AI deal in Nairobi - Reuters", source_name="Reuters"),
                    item("Ten amazing gadgets you need today - Obscure Blog", source_name="Obscure Blog"))
        analysis = run(gn)
        by_source = {s.lead.source: s.lead for s in analysis.stories}
        self.assertEqual(by_source["Reuters"].title, "Microsoft signs a big AI deal in Nairobi")
        self.assertGreater(by_source["Reuters"].weight, by_source["Obscure Blog"].weight)
        self.assertEqual(by_source["Reuters"].country, "")  # pas le pays de l'édition Google News


class SelectionTest(unittest.TestCase):
    def test_regions_and_source_cap(self):
        src = source("TechCabal", "afrique", "NG")
        titles = ["Flutterwave expands to Egypt", "Paystack launches new API", "Moniepoint hits 10M users",
                  "Safaricom tests 5G in Nairobi"]
        analysis = run(result(src, *[item(t) for t in titles]))
        sel = select(analysis.stories, top_n=1, per_region=4, max_per_source=2)
        self.assertEqual(len(sel.top), 1)
        self.assertEqual(len(sel.regions["afrique"]), 2)  # 2 maximum par média
        self.assertNotIn(sel.top[0], sel.regions["afrique"])


def _story_with_coverage(title: str, outlets: int, lang: str = "en", region: str = "amerique_nord"):
    """Un sujet couvert par `outlets` médias indépendants (titres légèrement différents)."""
    variants = [f"{title}", f"{title} for developers", f"{title} with partners", f"{title} amid strong demand",
                f"{title} after long wait", f"{title} ahead of schedule", f"{title} at big event",
                f"{title} with new features"]
    return [result(source(f"{title[:12]}-{i}", region, "US", 1.0), item(variants[i % len(variants)]))
            for i in range(outlets)]


class EssentialsTest(unittest.TestCase):
    """Brief court : 5 sujets d'office, jusqu'à 7 s'ils sont repris, 10 seulement les jours très chargés."""

    def _pick(self, coverages, lang="en"):
        topics = ["Nvidia unveils Rubin accelerators", "Mistral releases Magistral Large", "Apple opens Siri to agents",
                  "Samsung ships HBM5 memory", "Tesla starts robotaxi service", "Meta launches Llama glasses",
                  "Amazon cuts Alexa prices", "Intel spins off foundry unit", "Sony reveals PlayStation cloud",
                  "Oracle signs sovereign cloud pact", "Baidu opens Ernie weights", "Spotify adds AI DJ voices"]
        results = []
        for topic, n in zip(topics, coverages):
            results += _story_with_coverage(topic, n, lang)
        return pick_essentials(run(*results).stories)

    def test_quiet_day_gives_five(self):
        self.assertEqual(len(self._pick([2, 2, 1, 1, 1, 1, 1, 1, 1, 1])), 5)

    def test_normal_day_up_to_seven(self):
        self.assertEqual(len(self._pick([6, 5, 4, 4, 3, 3, 3, 3, 3, 1, 1, 1])), 7)

    def test_very_busy_day_up_to_ten(self):
        self.assertEqual(len(self._pick([8] * 12)), 10)

    def test_same_story_in_two_languages_counted_once(self):
        en = result(source("The Verge", "amerique_nord", "US", 1.3),
                    item("Elon Musk will give a SpaceX share to every kid in America"))
        es = result(Source(name="Infobae", url="https://x/es", region="amerique_latine", country="AR", lang="es",
                           weight=1.0, kind="media", publisher="Infobae"),
                    item("Elon Musk regalará una acción de SpaceX a cada niño"))
        other = result(source("BBC", "europe", "GB", 1.3), item("Nvidia unveils Rubin accelerators in Paris"))
        picked = pick_essentials(run(en, es, other).stories)
        self.assertEqual(len(picked), 2)

    def test_french_title_is_preferred(self):
        en = result(source("TechCrunch", "amerique_nord", "US", 1.3), item("OpenAI launches GPT-7 reasoning model"))
        fr = result(Source(name="Le Monde", url="https://x/fr", region="europe", country="FR", lang="fr", weight=1.3,
                           kind="media", publisher="Le Monde"),
                    item("OpenAI lance GPT-7, son nouveau modèle de raisonnement"))
        picked = pick_essentials(run(en, fr).stories)
        self.assertEqual(len(picked), 1)  # même histoire en deux langues : une seule place
        self.assertEqual(picked[0].coverage, 2)
        self.assertEqual(display_article(picked[0]).source, "Le Monde")


class WatchlistAndTrendTest(unittest.TestCase):
    def test_watchlist(self):
        items = watchlist_items(["Mistral", {"nom": "MCP", "motif": r"\bMCP\b"}])
        analysis = run(result(source("A"), item("Mistral dévoile un modèle"), item("Le protocole MCP s'étend")))
        matches = watch_matches(analysis.stories, items)
        self.assertEqual(matches["Mistral"][0], 1)
        self.assertEqual(matches["MCP"][0], 1)

    def test_trend(self):
        self.assertEqual(trend_arrow(10, []), "·")
        self.assertEqual(trend_arrow(20, [10, 10]), "↑↑")
        self.assertEqual(trend_arrow(12, [10]), "↑")
        self.assertEqual(trend_arrow(10, [10]), "→")
        self.assertEqual(trend_arrow(7, [10]), "↓")
        self.assertEqual(trend_arrow(3, [10]), "↓↓")


if __name__ == "__main__":
    unittest.main()
