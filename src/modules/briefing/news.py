"""A quiet news briefing from publishers' own RSS / Atom feeds.

DayOS shows each article's headline, publisher, time and the publisher's own short
description (HTML removed, shortened), and links to the original article. It never
downloads or republishes full articles, never invents headlines, and labels how old
saved headlines are.
"""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from src.services import http

TOPICS = {
    "technology": "Technology", "science": "Science", "education": "Education", "world": "World news",
    "local": "Local news", "business": "Business", "gaming": "Gaming", "programming": "Programming",
    "ai": "Artificial intelligence",
}

# Publishers' own public feeds (checked working when DayOS v2 was built). Local news has no
# default: add your local paper's feed in Settings.
DEFAULT_FEEDS: list[tuple[str, str, str]] = [
    ("technology", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("technology", "The Verge", "https://www.theverge.com/rss/index.xml"),
    ("science", "ScienceDaily", "https://www.sciencedaily.com/rss/all.xml"),
    ("science", "NASA", "https://www.nasa.gov/news-release/feed/"),
    ("world", "BBC News — World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("world", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("business", "BBC News — Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("education", "BBC News — Education", "https://feeds.bbci.co.uk/news/education/rss.xml"),
    ("education", "EdSurge", "https://www.edsurge.com/articles_rss"),
    ("gaming", "Polygon", "https://www.polygon.com/rss/index.xml"),
    ("gaming", "Rock Paper Shotgun", "https://www.rockpapershotgun.com/feed"),
    ("programming", "The GitHub Blog", "https://github.blog/feed/"),
    ("programming", "Stack Overflow Blog", "https://stackoverflow.blog/feed/"),
    ("ai", "MIT Technology Review — AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    ("ai", "Google — AI", "https://blog.google/technology/ai/rss/"),
]

ATOM = "{http://www.w3.org/2005/Atom}"
SUMMARY_CHARS = 280
MAX_PER_FEED = 25
MAX_AGE_DAYS = 3


@dataclass
class Feed:
    topic: str
    name: str
    url: str


@dataclass
class Article:
    id: str
    title: str
    link: str
    publisher: str
    topic: str
    published: str  # ISO 8601 UTC, or "" when the feed gave no date
    summary: str = ""

    @property
    def published_dt(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self.published) if self.published else None
        except ValueError:
            return None


@dataclass
class FetchResult:
    articles: list[Article] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (publisher, reason)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(fragment: str, limit: int = SUMMARY_CHARS) -> str:
    parser = _Text()
    try:
        parser.feed(fragment or "")
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = " ".join(html.unescape(text).split())
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return text


def _date(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _safe_link(link: str) -> str:
    link = (link or "").strip()
    return link if link.startswith(("https://", "http://")) else ""


def article_id(link: str, title: str) -> str:
    return hashlib.sha1((link or title).encode("utf-8", "replace")).hexdigest()[:16]


def parse_feed(body: bytes, feed: Feed) -> list[Article]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise ValueError("not a valid news feed") from None
    out: list[Article] = []
    items = root.findall(".//item")
    if items:
        for item in items[:MAX_PER_FEED]:
            title = plain_text(item.findtext("title") or "", 300)
            link = _safe_link(item.findtext("link") or "")
            if not title or not link:
                continue
            out.append(Article(article_id(link, title), title, link, feed.name, feed.topic,
                               _date(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")),
                               plain_text(item.findtext("description") or "")))
        return out
    for entry in root.findall(f".//{ATOM}entry")[:MAX_PER_FEED]:
        title = plain_text(entry.findtext(f"{ATOM}title") or "", 300)
        link = ""
        for node in entry.findall(f"{ATOM}link"):
            if node.get("rel", "alternate") == "alternate" and node.get("href"):
                link = _safe_link(node.get("href"))
                break
        if not title or not link:
            continue
        summary = entry.findtext(f"{ATOM}summary") or ""
        out.append(Article(article_id(link, title), title, link, feed.name, feed.topic,
                           _date(entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")),
                           plain_text(summary)))
    return out


def fetch_feeds(feeds: list[Feed], max_workers: int = 6) -> FetchResult:
    """Fetch feeds in parallel (call from a worker thread). Each failure is reported, never invented around."""
    result = FetchResult()

    def one(feed: Feed):
        try:
            body = http.request(feed.url, headers={"Accept": "application/rss+xml, application/atom+xml, "
                                                             "application/xml;q=0.9, */*;q=0.5"}).body
            return feed, parse_feed(body, feed), None
        except http.HttpError as exc:
            return feed, [], str(exc)
        except ValueError as exc:
            return feed, [], str(exc)

    if not feeds:
        return result
    with ThreadPoolExecutor(max_workers=min(max_workers, len(feeds))) as pool:
        for feed, articles, error in pool.map(one, feeds):
            if error:
                result.errors.append((feed.name, error))
            result.articles.extend(articles)
    seen: set[str] = set()
    unique = []
    for a in result.articles:
        if a.id not in seen:
            seen.add(a.id)
            unique.append(a)
    result.articles = sorted(unique, key=lambda a: a.published or "", reverse=True)
    return result


def feeds_for(topics: list[str], custom: list[dict], hidden: list[str]) -> list[Feed]:
    feeds = [Feed(t, n, u) for t, n, u in DEFAULT_FEEDS if t in topics]
    for c in custom:
        try:
            if c.get("topic") in topics or not topics:
                feeds.append(Feed(c.get("topic", "local"), c["name"], c["url"]))
        except (KeyError, AttributeError):
            continue
    hidden_set = {h.lower() for h in hidden}
    return [f for f in feeds if f.name.lower() not in hidden_set]


def recent(articles: list[Article], now: datetime | None = None, days: int = MAX_AGE_DAYS) -> list[Article]:
    """Drop articles older than ``days`` (undated ones are kept but sorted last)."""
    now = now or datetime.now(timezone.utc)
    out = []
    for a in articles:
        dt = a.published_dt
        if dt is None or (now - dt).total_seconds() <= days * 86400:
            out.append(a)
    return out
