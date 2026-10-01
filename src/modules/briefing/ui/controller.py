"""Fetches weather and news only when they're switched on, the cached copy is older than the
chosen interval (or the user presses Refresh), and no request is already running. After a
failure, automatic attempts wait at least :data:`RETRY_AFTER` — there are no retry loops."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Signal

from src.modules.briefing import news, weather
from src.services import http
from src.ui.worker import run_in_background

log = logging.getLogger(__name__)

RETRY_AFTER = 15 * 60  # seconds between automatic attempts after a failure
WEATHER_KEY = "weather:current"
NEWS_KEY = "news:articles"


class BriefingController(QObject):
    weather_changed = Signal()
    news_changed = Signal()

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.cache = http.HttpCache(ctx.db)
        self.weather_busy = False
        self.news_busy = False
        self.weather_error = ""
        self.news_errors: list[tuple[str, str]] = []
        self._weather_attempt = 0.0
        self._news_attempt = 0.0

    # -- weather --------------------------------------------------------------------------
    def weather(self) -> tuple[weather.WeatherReport | None, datetime | None]:
        place = weather.Place.from_setting(self.ctx.settings.get("weather.place"))
        cached = self.cache.get(WEATHER_KEY)
        if not cached or place is None:
            return None, None
        value, when = cached
        if not isinstance(value, dict) or value.get("key") != self._weather_key(place):
            return None, None  # cached for another place or unit
        try:
            return weather.WeatherReport.from_cache(value["report"]), when
        except (KeyError, TypeError):
            return None, None

    def _weather_key(self, place: weather.Place) -> str:
        return f"{place.lat:.3f},{place.lon:.3f},{self.ctx.settings.get('weather.units')}"

    def weather_stale(self) -> bool:
        report, when = self.weather()
        minutes = int(self.ctx.settings.get("weather.refresh_minutes"))
        return report is None or when is None or datetime.now() - when > timedelta(minutes=minutes)

    def refresh_weather(self, force: bool = False) -> bool:
        s = self.ctx.settings
        place = weather.Place.from_setting(s.get("weather.place"))
        if not s.get("weather.enabled") or place is None or self.weather_busy:
            return False
        if not force and (not self.weather_stale() or time.time() - self._weather_attempt < RETRY_AFTER):
            return False
        self.weather_busy = True
        self._weather_attempt = time.time()
        units = str(s.get("weather.units"))
        key = self._weather_key(place)

        def done(report: weather.WeatherReport) -> None:
            self.weather_busy = False
            self.weather_error = ""
            self.cache.put(WEATHER_KEY, {"key": key, "report": report.to_cache()})
            self.weather_changed.emit()

        def failed(exc: Exception) -> None:
            self.weather_busy = False
            self.weather_error = str(exc) if isinstance(exc, http.HttpError) else "The weather couldn't be read."
            log.info("Weather refresh failed: %s", getattr(exc, "kind", type(exc).__name__))
            self.weather_changed.emit()

        run_in_background(lambda: weather.fetch(place, units), done, failed)
        self.weather_changed.emit()
        return True

    # -- news ---------------------------------------------------------------------------------
    def feeds(self) -> list[news.Feed]:
        s = self.ctx.settings
        return news.feeds_for(list(s.get("news.topics")), list(s.get("news.custom_feeds")),
                              list(s.get("news.hidden_sources")))

    def articles(self) -> tuple[list[news.Article], datetime | None]:
        cached = self.cache.get(NEWS_KEY)
        if not cached:
            return [], None
        value, when = cached
        hidden = {h.lower() for h in self.ctx.settings.get("news.hidden_sources")}
        topics = set(self.ctx.settings.get("news.topics"))
        out = []
        for raw in value if isinstance(value, list) else []:
            try:
                a = news.Article(**raw)
            except TypeError:
                continue
            if a.publisher.lower() not in hidden and (a.topic in topics or a.topic == "local"):
                out.append(a)
        return news.recent(out), when

    def news_stale(self) -> bool:
        _articles, when = self.articles()
        minutes = int(self.ctx.settings.get("news.refresh_minutes"))
        return when is None or datetime.now() - when > timedelta(minutes=minutes)

    def refresh_news(self, force: bool = False) -> bool:
        s = self.ctx.settings
        feeds = self.feeds()
        if not s.get("news.enabled") or not feeds or self.news_busy:
            return False
        if not force and (not self.news_stale() or time.time() - self._news_attempt < RETRY_AFTER):
            return False
        self.news_busy = True
        self._news_attempt = time.time()

        def done(result: news.FetchResult) -> None:
            self.news_busy = False
            self.news_errors = result.errors
            if result.articles:  # keep the previous headlines if every feed failed
                self.cache.put(NEWS_KEY, [a.__dict__ for a in result.articles[:400]])
            self.news_changed.emit()

        def failed(exc: Exception) -> None:
            self.news_busy = False
            self.news_errors = [("News", str(exc))]
            self.news_changed.emit()

        run_in_background(lambda: news.fetch_feeds(feeds), done, failed)
        self.news_changed.emit()
        return True

    # read state
    def read_ids(self) -> set[str]:
        return {r[0] for r in self.ctx.db.query("SELECT article_id FROM news_read")}

    def mark_read(self, article_ids: list[str]) -> None:
        from src.services.dates import now_stamp

        with self.ctx.db.transaction():
            for aid in article_ids:
                self.ctx.db.execute("INSERT OR IGNORE INTO news_read (article_id, read_at) VALUES (?, ?)",
                                    (aid, now_stamp()))
            # keep the table small: read marks older than 60 days are no longer needed
            self.ctx.db.execute("DELETE FROM news_read WHERE read_at < ?",
                                ((datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S"),))
        self.news_changed.emit()

    def hide_source(self, publisher: str) -> None:
        hidden = list(self.ctx.settings.get("news.hidden_sources"))
        if publisher not in hidden:
            hidden.append(publisher[:120])
            self.ctx.settings.set("news.hidden_sources", hidden[-100:])
        self.news_changed.emit()
