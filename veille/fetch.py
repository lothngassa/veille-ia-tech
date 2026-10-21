"""Téléchargement parallèle et lecture des flux RSS / Atom, avec la seule bibliothèque standard."""

from __future__ import annotations

import gzip
import html
import logging
import re
import threading
import time
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from .sources import Source

log = logging.getLogger(__name__)

BROWSER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
MAX_BYTES = 8 * 1024 * 1024
REDDIT, YOUTUBE, GOOGLE_NEWS = "reddit.com", "youtube.com", "news.google.com"


@dataclass(frozen=True)
class HostPolicy:
    concurrency: int = 2       # requêtes simultanées maximum vers ce site
    gap: float = 0.0           # pause (s) après chaque requête
    agent: str = BROWSER_AGENT
    retry_404: bool = False    # certains sites renvoient des 404 au hasard


# Reddit refuse les faux navigateurs et limite fortement les requêtes anonymes ;
# les flux YouTube renvoient parfois 404/500 de façon intermittente.
_POLICIES = {
    REDDIT: HostPolicy(concurrency=1, gap=6.0, agent="veille-ia-tech/1.0 (personal news digest)"),
    YOUTUBE: HostPolicy(concurrency=2, retry_404=True),
    GOOGLE_NEWS: HostPolicy(concurrency=3),
}
_semaphores: dict[str, threading.Semaphore] = {}
_semaphores_guard = threading.Lock()


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def _policy(url: str) -> HostPolicy:
    return _POLICIES.get(_host(url), HostPolicy())


def _semaphore(url: str) -> threading.Semaphore:
    host = _host(url)
    with _semaphores_guard:
        if host not in _semaphores:
            _semaphores[host] = threading.Semaphore(_policy(url).concurrency)
        return _semaphores[host]


@dataclass
class RawItem:
    title: str
    link: str
    summary: str
    published: datetime | None
    source_name: str = ""  # renseigné par les agrégateurs (balise <source> de Google News)


@dataclass
class FeedResult:
    source: Source
    items: list[RawItem] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


# --------------------------------------------------------------------------- HTTP

def http_get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": _policy(url).agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "fr,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(MAX_BYTES + 1)
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
    if len(data) > MAX_BYTES:
        raise ValueError("flux trop volumineux")
    if encoding == "gzip" or data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    if encoding == "deflate":
        try:
            return zlib.decompress(data)
        except zlib.error:
            return zlib.decompress(data, -zlib.MAX_WBITS)
    return data


def _describe(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"réseau ({exc.reason})"
    if isinstance(exc, ET.ParseError):
        return "flux illisible (XML invalide)"
    if isinstance(exc, TimeoutError):
        return "délai dépassé"
    return f"{type(exc).__name__}: {exc}"


def _transient(exc: Exception, url: str, attempt: int) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (429, 500, 502, 503, 504) or (exc.code == 404 and _policy(url).retry_404)
    # Un site qui ne répond pas a peu de chances de répondre tout de suite : un seul nouvel essai.
    return attempt == 1 and isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def _download(url: str, timeout: float) -> bytes:
    with _semaphore(url):
        try:
            return http_get(url, timeout)
        finally:
            time.sleep(_policy(url).gap)


def fetch_source(source: Source, timeout: float = 15, attempts: int = 3) -> FeedResult:
    start = time.monotonic()
    result = FeedResult(source)
    for attempt in range(1, attempts + 1):
        try:
            result.items = parse_feed(_download(source.url, timeout))
            result.error = None
            break
        except Exception as exc:  # une source en panne ne doit jamais bloquer les autres
            result.error = _describe(exc)
            if attempt == attempts or not _transient(exc, source.url, attempt):
                break
            time.sleep(2 * attempt)
    result.seconds = time.monotonic() - start
    if result.error:
        log.info("Source en échec : %s (%s)", source.name, result.error)
    return result


def fetch_all(sources: list[Source], workers: int = 16, timeout: float = 15, budget: float = 75) -> list[FeedResult]:
    """Télécharge toutes les sources en parallèle. Au-delà de `budget` secondes, on n'attend plus les retardataires
    (marqués en échec) : un site qui traîne ne retarde jamais le brief."""
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {pool.submit(fetch_source, s, timeout): s for s in sources}
    done, _ = wait(futures, timeout=budget)
    pool.shutdown(wait=False, cancel_futures=True)
    results = []
    for future, source in futures.items():
        if future in done:
            results.append(future.result())
        else:
            log.info("Source abandonnée (trop lente) : %s", source.name)
            results.append(FeedResult(source, error="trop lente (abandonnée)", seconds=budget))
    return results


# --------------------------------------------------------------------------- Parsing

_UNKNOWN_ENTITY = re.compile(rb"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_CONTROL_CHARS = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_TAG_PREFIX = re.compile(rb"<(/?)[A-Za-z_][\w.-]*:(?=[A-Za-z_])")
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _text(el: ET.Element) -> str:
    return "".join(el.itertext()).strip()


def clean_text(value: str) -> str:
    """HTML -> texte brut sur une ligne."""
    value = html.unescape(_TAGS.sub(" ", value))
    value = html.unescape(value)  # certains flux échappent deux fois
    return _SPACES.sub(" ", value).strip()


def parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(value)  # RSS : « Mon, 20 Oct 2026 18:00:00 +0200 »
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # Atom : ISO 8601
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M %z"):
                try:
                    dt = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_xml(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        pass
    data = _CONTROL_CHARS.sub(b"", _UNKNOWN_ENTITY.sub(b"&amp;", data))  # &nbsp; & co, caractères interdits
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        # Dernier recours : préfixes d'espace de noms non déclarés (<dc:creator> sans xmlns:dc).
        return ET.fromstring(_TAG_PREFIX.sub(rb"<\1", data))


def parse_feed(data: bytes) -> list[RawItem]:
    """Lit un flux RSS 2.0, RSS 1.0 (RDF) ou Atom. Tolère les entités HTML et les caractères invalides."""
    data = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if data[:15].lower().startswith((b"<!doctype html", b"<html")):
        raise ET.ParseError("page HTML au lieu d'un flux")
    root = _parse_xml(data)
    if _local(root.tag).lower() == "html":
        raise ET.ParseError("page HTML au lieu d'un flux")
    items = (_parse_entry(el) for el in root.iter() if _local(el.tag) in ("item", "entry"))
    return [item for item in items if item]


# Balise -> champ. Pour chaque champ, on garde la première valeur rencontrée.
_FIELDS = {
    "title": "title", "origLink": "orig_link", "description": "summary", "summary": "summary",
    "encoded": "content", "content": "content", "pubDate": "published", "published": "published",
    "issued": "published", "date": "published", "updated": "updated", "modified": "updated",
}


def _add_link(child: ET.Element, links: list[str]) -> None:
    href = child.get("href")
    if href is None:
        links.insert(0, _text(child))  # RSS : <link>url</link>, prioritaire
    elif child.get("rel", "alternate") == "alternate":
        links.append(href.strip())     # Atom : <link rel="alternate" href="url"/>


def _parse_entry(el: ET.Element) -> RawItem | None:
    fields: dict[str, str] = {}
    links: list[str] = []
    for child in el:
        name = _local(child.tag)
        if name == "link":
            _add_link(child, links)
        elif name == "guid" and child.get("isPermaLink", "true") != "false":
            fields.setdefault("guid", _text(child))
        elif name == "source" and len(child) == 0:
            fields.setdefault("source", _text(child))
        elif name in _FIELDS:
            fields.setdefault(_FIELDS[name], _text(child))

    guid = fields.get("guid", "")
    candidates = [fields.get("orig_link", ""), *links, guid if guid.startswith("http") else ""]
    url = next((u for u in candidates if u.startswith("http")), "")
    title = clean_text(fields.get("title", ""))
    if not title or not url:
        return None
    return RawItem(
        title=title,
        link=url.strip(),
        summary=clean_text(fields.get("summary") or fields.get("content", ""))[:600],
        published=parse_date(fields.get("published", "")) or parse_date(fields.get("updated", "")),
        source_name=clean_text(fields.get("source", "")),
    )
