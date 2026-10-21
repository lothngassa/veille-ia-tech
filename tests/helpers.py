"""Fabriques de données de test."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from veille.fetch import FeedResult, RawItem
from veille.sources import Source

NOW = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)


def source(name="Média", region="europe", country="FR", weight=1.0, kind="media", publisher=None, targeted=False,
           lang="en"):
    return Source(name=name, url=f"https://example.org/{name}.xml", region=region, country=country, lang=lang,
                  weight=weight, kind=kind, publisher=publisher or name, targeted=targeted)


def item(title, link=None, summary="", hours_ago=2.0, source_name=""):
    return RawItem(title=title, link=link or f"https://example.org/{abs(hash(title))}", summary=summary,
                   published=NOW - timedelta(hours=hours_ago), source_name=source_name)


def result(src, *items):
    return FeedResult(source=src, items=list(items))
