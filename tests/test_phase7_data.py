"""Weather, news, HTTP, credentials, money and skills — data layers (no network)."""

import io
import os
import unittest
import urllib.error
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from src.modules.briefing import news, weather
from src.modules.money.repository import MoneyRepository, add_cycle, format_amount, parse_amount
from src.modules.skills.repository import SkillRepository
from src.services import credentials, http
from src.services.dates import ValidationError
from tests.helpers import FIXED_NOW, TempHomeTestCase

TODAY = FIXED_NOW.date()

FORECAST = {
    "current": {"time": "2026-09-27T10:00", "temperature_2m": 27.4, "apparent_temperature": 30.1,
                "relative_humidity_2m": 78, "precipitation": 0.0, "weather_code": 2, "wind_speed_10m": 11.2,
                "wind_direction_10m": 250, "is_day": 1},
    "hourly": {"time": ["2026-09-27T09:00", "2026-09-27T10:00"], "precipitation_probability": [10, 35]},
    "daily": {"time": ["2026-09-27", "2026-09-28"], "weather_code": [2, 63], "temperature_2m_max": [30.0, 28.5],
              "temperature_2m_min": [22.1, 21.0], "precipitation_probability_max": [40, 90]},
}

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Example</title>
<item><title>Big &amp; small news</title><link>https://example.com/a</link>
<pubDate>Sun, 27 Sep 2026 08:00:00 GMT</pubDate>
<description>&lt;p&gt;The &lt;b&gt;publisher's&lt;/b&gt; own summary.&lt;/p&gt;</description></item>
<item><title>Old story</title><link>https://example.com/old</link><pubDate>Mon, 01 Jan 2024 08:00:00 GMT</pubDate></item>
<item><title>Bad link</title><link>javascript:alert(1)</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title>
<entry><title>Atom post</title><link rel="alternate" href="https://blog.example.org/p1"/>
<updated>2026-09-26T12:00:00Z</updated><summary>Short &amp; sweet</summary></entry></feed>"""


class WeatherNewsTests(unittest.TestCase):
    def test_forecast_parsing_never_invents_values(self):
        place = weather.Place("Pune", 18.52, 73.86, "Maharashtra", "India")
        report = weather.parse_forecast(FORECAST, place, "metric")
        self.assertEqual((report.temperature, report.feels_like, report.humidity, report.rain_chance),
                         (27.4, 30.1, 78, 35))
        self.assertEqual(weather.describe(report.code)[0], "Partly cloudy")
        self.assertEqual(weather.compass(report.wind_direction), "W")
        self.assertEqual([d.rain_chance for d in report.days], [40, 90])
        sparse = {"current": {"time": "2026-09-27T10:00", "temperature_2m": 20}}
        r2 = weather.parse_forecast(sparse, place, "metric")
        self.assertEqual((r2.feels_like, r2.humidity, r2.rain_chance, r2.days), (None, None, None, []))
        with self.assertRaises(http.HttpError):
            weather.parse_forecast({}, place, "metric")
        restored = weather.WeatherReport.from_cache(report.to_cache())
        self.assertEqual(restored.days[1].high, 28.5)
        self.assertIn("temperature_unit=fahrenheit", weather.forecast_url(place, "imperial"))
        self.assertEqual(weather.Place.from_setting(place.to_setting()).label, "Pune, Maharashtra, India")

    def test_rss_and_atom_parsing(self):
        feed = news.Feed("technology", "Example", "https://example.com/rss")
        items = news.parse_feed(RSS, feed)
        self.assertEqual([a.title for a in items], ["Big & small news", "Old story"])  # unsafe link dropped
        self.assertEqual(items[0].summary, "The publisher's own summary.")
        self.assertEqual(items[0].published, "2026-09-27T08:00:00+00:00")
        now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
        self.assertEqual([a.title for a in news.recent(items, now)], ["Big & small news"])
        atom = news.parse_feed(ATOM, news.Feed("programming", "Blog", "https://blog.example.org/feed"))
        self.assertEqual((atom[0].title, atom[0].link, atom[0].summary), ("Atom post", "https://blog.example.org/p1",
                                                                           "Short & sweet"))
        with self.assertRaises(ValueError):
            news.parse_feed(b"<html><body>not a feed", feed)
        self.assertLessEqual(len(news.plain_text("word " * 200)), news.SUMMARY_CHARS + 1)

    def test_feed_selection_and_failures_are_reported(self):
        feeds = news.feeds_for(["gaming"], [{"name": "My Town", "url": "https://town.example/rss", "topic": "gaming"}],
                               ["polygon"])
        self.assertEqual([f.name for f in feeds], ["Rock Paper Shotgun", "My Town"])
        with mock.patch.object(http, "request", side_effect=http.HttpError("offline", "No internet")):
            result = news.fetch_feeds(feeds)
        self.assertEqual(result.articles, [])  # nothing invented when offline
        self.assertEqual(len(result.errors), 2)

    def test_http_rate_limits_and_bad_urls(self):
        with self.assertRaises(http.HttpError) as err:
            http.request("file:///C:/Windows/win.ini")
        self.assertEqual(err.exception.kind, "bad_url")
        host = f"rl-{uuid.uuid4().hex[:6]}.example"
        error = urllib.error.HTTPError(f"https://{host}/x", 429, "Too Many", {"Retry-After": "120"}, io.BytesIO())
        with mock.patch("urllib.request.urlopen", side_effect=error) as opener:
            with self.assertRaises(http.HttpError) as err:
                http.request(f"https://{host}/x")
            self.assertEqual(err.exception.kind, "rate_limited")
            with self.assertRaises(http.HttpError):
                http.request(f"https://{host}/y")  # waits instead of asking again
            self.assertEqual(opener.call_count, 1)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
            with self.assertRaises(http.HttpError) as err:
                http.request("https://offline.example/")
        self.assertEqual(err.exception.kind, "offline")

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_credentials_round_trip_and_mask(self):
        name = f"test-{uuid.uuid4().hex[:8]}"
        try:
            credentials.save(name, "not-a-real-key-ABCD")
            self.assertEqual(credentials.load(name), "not-a-real-key-ABCD")
            self.assertEqual(credentials.mask("not-a-real-key-ABCD"), "••••••••ABCD")
        finally:
            credentials.delete(name)
        self.assertIsNone(credentials.load(name))


class HttpCacheTests(TempHomeTestCase):
    def test_cache_ages(self):
        cache = http.HttpCache(self.ctx.db)
        cache.put("weather:x", {"a": 1})
        value, when = cache.get("weather:x")
        self.assertEqual(value, {"a": 1})
        self.assertIsNotNone(cache.get("weather:x", timedelta(minutes=5)))
        with mock.patch("src.services.http.datetime") as dt:
            dt.now.return_value = datetime.now() + timedelta(hours=2)
            dt.fromisoformat = datetime.fromisoformat
            self.assertIsNone(cache.get("weather:x", timedelta(hours=1)))
        self.assertEqual(http.describe_age(datetime.now() - timedelta(minutes=5)), "5 min ago")


class MoneyTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.money = MoneyRepository(self.ctx.db)

    def test_amounts_are_exact(self):
        self.assertEqual(parse_amount("1,299.5"), 129950)
        self.assertEqual(parse_amount("₹250"), 25000)
        for bad in ("", "abc", "-5", "1.234", "0"):
            with self.assertRaises(ValidationError, msg=bad):
                parse_amount(bad)
        self.assertEqual(format_amount(123456789, "INR"), "₹12,34,567.89")
        self.assertEqual(format_amount(150000, "USD"), "$1,500")
        self.assertEqual(format_amount(-250, "EUR"), "−€2.50")
        self.assertEqual(add_cycle(date(2026, 1, 31), "monthly"), date(2026, 2, 28))
        self.assertEqual(add_cycle(date(2026, 11, 15), "quarterly"), date(2027, 2, 15))

    def test_entries_totals_budgets_and_csv(self):
        food = next(c.id for c in self.money.categories("expense") if c.name == "Food & groceries")
        self.money.add_entry("income", 5000000, TODAY, note="Salary")
        self.money.add_entry("expense", 120000, TODAY, food, "Groceries")
        self.money.add_entry("expense", 30000, TODAY - timedelta(days=40), food)
        month = TODAY.strftime("%Y-%m")
        self.assertEqual(self.money.month_totals(month), {"income": 5000000, "expense": 120000, "net": 4880000})
        self.assertEqual(self.money.by_category(month)[0][:2], ("Food & groceries", 120000))
        self.money.set_budget(food, 500000)
        self.money.set_budget(food, 400000)
        self.assertEqual(self.money.budgets(), {food: 400000})
        self.assertEqual(len(self.money.history(3)), 3)
        path = self.money.export_csv(self.paths.exports_dir)
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("Groceries", text)
        self.assertIn("1200.00", text)
        self.money.delete_category(food)
        self.assertEqual(self.money.entries(month)[0].category_id, None)  # entries kept

    def test_subscriptions_reminders_and_renewal(self):
        sid = self.money.save_subscription(None, name="Music", amount=11900, cycle="monthly",
                                           next_date=TODAY + timedelta(days=3), remind_days=3)
        start = datetime.combine(TODAY, datetime.min.time())
        notices = self.money.upcoming_bills(start, start + timedelta(days=1))
        self.assertEqual([n.category for n in notices], ["bill"])
        nxt = self.money.mark_paid(sid)
        self.assertEqual(nxt, add_cycle(TODAY + timedelta(days=3), "monthly"))
        self.assertEqual(self.money.entries()[0].note, "Music")
        hits = self.ctx.search.search("music")
        self.assertEqual([(h.kind, h.ref_id) for h in hits], [("subscription", sid)])
        with self.assertRaises(ValidationError):
            self.money.save_subscription(None, name="X", amount=100, cycle="daily", next_date=TODAY)


class SkillTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.skills = SkillRepository(self.ctx.db)

    def test_roadmap_prerequisites_and_weekly_review(self):
        py = self.skills.save(None, name="Python", category="Programming", baseline="Basics", goal="Build a web app")
        web = self.skills.save(None, name="Web development")
        self.skills.add_prerequisite(web, py)
        with self.assertRaises(ValidationError):
            self.skills.add_prerequisite(py, web)  # no cycles
        with self.assertRaises(ValidationError):
            self.skills.save(None, name="python")
        m = self.skills.add_item(py, "milestone", "Finish the tutorial")
        self.skills.add_item(py, "resource", "Docs", "docs.python.org")
        self.skills.set_item_done(m, True)
        self.skills.log(py, "learn", 60, "Read chapter 3")
        self.skills.log(py, "build", 90, "Made a CLI", "https://github.com/me/cli")
        with self.assertRaises(ValidationError):
            self.skills.log(py, "learn")  # nothing recorded
        week = self.skills.week_summary(TODAY - timedelta(days=TODAY.weekday()))
        self.assertEqual(week["totals"]["learn"], 60)
        self.assertEqual(week["totals"]["build"], 90)
        self.assertEqual(week["totals"]["evidence"], 1)
        self.assertEqual(week["totals"]["milestones"], 1)
        self.assertEqual(self.ctx.search.search("web app")[0].kind, "skill")
        self.assertEqual([s.name for s in self.skills.prerequisites(web)], ["Python"])


if __name__ == "__main__":
    unittest.main()
