import unittest
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from veille.fetch import clean_text, parse_date, parse_feed

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Test</title>
  <item>
    <title>OpenAI lance &lt;b&gt;GPT-7&lt;/b&gt;</title>
    <link>https://example.com/a?utm_source=rss</link>
    <description><![CDATA[<p>Un <b>nouveau</b> mod&egrave;le.</p>]]></description>
    <pubDate>Tue, 20 Oct 2026 16:00:00 +0200</pubDate>
  </item>
  <item><title>Sans lien</title></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title type="html">Nvidia d&#233;voile Rubin</title>
    <link rel="replies" href="https://example.com/comments"/>
    <link rel="alternate" href="https://example.com/rubin"/>
    <updated>2026-10-20T12:30:00Z</updated>
    <summary>Résumé</summary>
  </entry>
</feed>""".encode("utf-8")

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel><title>T</title></channel>
  <item><title>Article RDF</title><link>https://example.com/rdf</link><dc:date>2026-10-20T08:00:00+00:00</dc:date></item>
</rdf:RDF>"""


class ParseFeedTest(unittest.TestCase):
    def test_rss(self):
        items = parse_feed(RSS)
        self.assertEqual(len(items), 1)  # l'article sans lien est ignoré
        self.assertEqual(items[0].title, "OpenAI lance GPT-7")
        self.assertEqual(items[0].summary, "Un nouveau modèle.")
        self.assertEqual(items[0].published, datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc))

    def test_atom_prefers_alternate_link(self):
        items = parse_feed(ATOM)
        self.assertEqual(items[0].link, "https://example.com/rubin")
        self.assertEqual(items[0].title, "Nvidia dévoile Rubin")
        self.assertEqual(items[0].published.hour, 12)

    def test_rdf(self):
        items = parse_feed(RDF)
        self.assertEqual([i.title for i in items], ["Article RDF"])
        self.assertIsNotNone(items[0].published)

    def test_html_entities_and_control_chars_are_repaired(self):
        broken = b"<rss><channel><item><title>A&nbsp;B \x01ok</title><link>https://x.org/1</link></item></channel></rss>"
        self.assertEqual(parse_feed(broken)[0].title, "A B ok")

    def test_undeclared_namespace_prefix_is_repaired(self):
        broken = b"<rss><channel><item><title>T</title><link>https://x.org/1</link><dc:creator>Moi</dc:creator>" \
                 b"</item></channel></rss>"
        self.assertEqual(len(parse_feed(broken)), 1)

    def test_html_page_is_rejected(self):
        with self.assertRaises(ET.ParseError):
            parse_feed(b"<!doctype html><html><body>Cloudflare</body></html>")

    def test_google_news_source(self):
        feed = b"""<rss><channel><item><title>Titre - Reuters</title><link>https://news.google.com/rss/articles/x</link>
        <source url="https://www.reuters.com">Reuters</source></item></channel></rss>"""
        self.assertEqual(parse_feed(feed)[0].source_name, "Reuters")


class HelpersTest(unittest.TestCase):
    def test_dates(self):
        utc = timezone.utc
        self.assertEqual(parse_date("Tue, 20 Oct 2026 16:00:00 GMT"), datetime(2026, 10, 20, 16, 0, tzinfo=utc))
        self.assertEqual(parse_date("2026-10-20T16:00:00Z"), datetime(2026, 10, 20, 16, 0, tzinfo=utc))
        self.assertEqual(parse_date("2026-10-20T18:00:00+02:00"), datetime(2026, 10, 20, 16, 0, tzinfo=utc))
        self.assertEqual(parse_date("2026-10-20 16:00:00"), datetime(2026, 10, 20, 16, 0, tzinfo=utc))
        self.assertIsNone(parse_date("hier soir"))
        self.assertIsNone(parse_date(""))

    def test_clean_text(self):
        self.assertEqual(clean_text("<p>Hello&amp;amp;  <b>world</b></p>"), "Hello& world")


if __name__ == "__main__":
    unittest.main()
