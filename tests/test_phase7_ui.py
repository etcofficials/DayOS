"""Briefing, money, skills and projects through the real widgets (offscreen, no network)."""

import os
import time
import unittest
from datetime import timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel  # noqa: E402

from src.modules.briefing import news, weather  # noqa: E402
from src.services import http  # noqa: E402
from tests.helpers import FIXED_NOW, TempHomeTestCase  # noqa: E402
from tests.test_phase7_data import FORECAST  # noqa: E402

app = QApplication.instance() or QApplication([])
TODAY = FIXED_NOW.date()


def pump(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def texts(widget) -> str:
    return " ".join(w.text() for w in widget.findChildren(QLabel))


class Phase7UiTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow
        from src.ui.theme import theme

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.ctx.settings.set("capture.global", False)
        self.window = MainWindow(self.ctx)
        self.window.resize(1300, 860)
        self.window.show()
        pump(20)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        pump(20)
        super().tearDown()

    def wait(self, cond, timeout=5.0):
        end = time.time() + timeout
        while not cond() and time.time() < end:
            pump(20)
        self.assertTrue(cond())

    def test_weather_is_off_by_default_then_cached_and_offline_honest(self):
        controller = self.window.briefing
        with mock.patch.object(weather, "fetch") as fetch:
            self.assertFalse(controller.refresh_weather(force=True))
            fetch.assert_not_called()  # nothing is requested while weather is off
        self.ctx.settings.set("dashboard.widgets", ["weather", "news"])
        self.ctx.settings.set("weather.place", weather.Place("Pune", 18.52, 73.86, "", "India").to_setting())
        self.ctx.settings.set("weather.enabled", True)
        report = weather.parse_forecast(FORECAST, weather.Place("Pune", 18.52, 73.86, "", "India"), "metric")
        with mock.patch.object(weather, "fetch", return_value=report):
            self.assertTrue(controller.refresh_weather(force=True))
            self.wait(lambda: not controller.weather_busy)
        self.window.navigate("briefing")
        page = self.window.page("briefing")
        page.refresh()
        shown = texts(page.weather_card)
        self.assertIn("27°C", shown)
        self.assertIn("Feels like 30°C", shown)
        self.assertIn("Open-Meteo.com", shown)
        with mock.patch.object(weather, "fetch", side_effect=http.HttpError("offline", "No internet connection.")):
            controller.refresh_weather(force=True)
            self.wait(lambda: not controller.weather_busy)
        page._fill_weather()
        self.assertIn("offline", texts(page.weather_card))
        self.assertIn("27°C", texts(page.weather_card))  # last real data, labelled, never invented
        with mock.patch.object(weather, "fetch") as fetch:
            self.assertFalse(controller.refresh_weather())  # failed recently: no automatic retry loop
            fetch.assert_not_called()

    def test_news_briefing_read_state_and_hidden_sources(self):
        controller = self.window.briefing
        self.ctx.settings.set("news.enabled", True)
        self.ctx.settings.set("news.topics", ["technology"])
        now_iso = (FIXED_NOW - timedelta(hours=2)).astimezone().isoformat()
        articles = [news.Article("a1", "Chip news", "https://example.com/1", "Ars Technica", "technology", now_iso,
                                 "A summary."),
                    news.Article("a2", "Gadget news", "https://example.com/2", "The Verge", "technology", now_iso)]
        with mock.patch.object(news, "fetch_feeds", return_value=news.FetchResult(articles, [("X", "offline")])):
            controller.refresh_news(force=True)
            self.wait(lambda: not controller.news_busy)
        with mock.patch.object(news, "recent", side_effect=lambda a, *x, **k: a):
            self.window.navigate("briefing")
            page = self.window.page("briefing")
            page.refresh()
            shown = texts(page.news_card)
            self.assertIn("Publisher's description: A summary.", shown)
            self.assertIn("1 source(s) unavailable", shown)
            controller.mark_read(["a1"])
            self.assertEqual(controller.read_ids(), {"a1"})
            controller.hide_source("The Verge")
            self.assertEqual([a.id for a in controller.articles()[0]], ["a1"])

    def test_money_currency_entries_subscriptions_and_widget(self):
        from src.modules.money.ui.page import EntryDialog, SubscriptionDialog

        self.window.navigate("money")
        page = self.window.page("money")
        self.assertTrue(page.setup.isVisibleTo(page))  # asks for a currency; nothing assumed
        page.currency_combo.setCurrentIndex(page.currency_combo.findData("INR"))
        page._set_currency()
        page.refresh()
        self.assertFalse(page.setup.isVisibleTo(page))
        dlg = EntryDialog(page, "expense")
        dlg.amount.setText("1,250.50")
        dlg.note.setText("Books")
        dlg._on_save()
        self.assertFalse(dlg.error.isVisibleTo(dlg))
        bad = EntryDialog(page, "expense")
        bad.amount.setText("abc")
        bad._on_save()
        self.assertTrue(bad.error.isVisibleTo(bad))
        sub = SubscriptionDialog(page)
        sub.name.setText("Cloud storage")
        sub.amount.setText("130")
        sub.next_date.set_value(TODAY + timedelta(days=2))
        sub._on_save()
        self.assertFalse(sub.error.isVisibleTo(sub))
        page.refresh()
        self.assertIn("₹1,250.50", texts(page.overview_holder))
        self.ctx.settings.set("dashboard.widgets", ["money"])
        today = self.window.page("today")
        today.refresh()
        card = today.cards["money"]
        self.assertIn("Cloud storage", texts(card))
        bills = [n for n in self.ctx.notifications.due() if n.category == "bill"]
        self.assertEqual([n.title for n in bills], [f"Cloud storage renews on {(TODAY + timedelta(days=2)):%d %b}"])
        self.ctx.settings.set("notify.bill", False)
        self.assertEqual([n for n in self.ctx.notifications.due() if n.category == "bill"], [])

    def test_skills_and_projects_pages(self):
        from src.modules.skills.ui.page import SkillDialog

        self.window.navigate("skills")
        skills = self.window.page("skills")
        dlg = SkillDialog(skills)
        dlg.name.setText("Spanish")
        dlg.goal.setPlainText("Hold a 10-minute conversation")
        dlg._on_save()
        self.assertIsNotNone(dlg.saved_id)
        skills.open_skill(dlg.saved_id)
        repo = skills.skills
        repo.add_item(dlg.saved_id, "milestone", "Order food in Spanish")
        repo.log(dlg.saved_id, "practice", 20, "Conversation app")
        skills.refresh()
        boxes = [c.text() for c in skills.detail_holder.findChildren(QCheckBox)]
        self.assertIn("Order food in Spanish", boxes)
        skills.view.set_current("week")
        skills.refresh()
        self.assertIn("Practice 20 min", texts(skills.week_holder))
        pid = self.ctx.projects.create("DayOS", repo_url="https://github.com/etcofficials/DayOS")
        self.window.navigate("projects")
        projects = self.window.page("projects")
        projects.open_project(pid)
        from src.modules.projects import github

        info = github.RepoInfo("etcofficials/DayOS", releases=[{"name": "v1.1.0", "tag": "v1.1.0",
                                                                "url": "https://github.com/x", "published": "2026-09-29",
                                                                "draft": False, "prerelease": False}])
        with mock.patch.object(github, "fetch_repo", return_value=info), \
                mock.patch.object(github, "saved_token", return_value=None):
            projects.load_github(pid, "etcofficials", "DayOS")
            self.wait(lambda: pid not in projects.github_busy)
        self.assertIn("etcofficials/DayOS", texts(projects.holder))
        title = mock.Mock()
        title.text.return_value = "Write release notes"
        projects._add_task(pid, title)
        self.assertEqual([t.title for t in self.ctx.tasks.list("all", project_id=pid)], ["Write release notes"])

    def test_settings_sections_build(self):
        self.window.navigate("settings")
        settings = self.window.page("settings")
        for key in ("briefing", "github", "secondbrain", "clipvault"):
            settings.show_section(key, animate=False)
            self.assertIn(key, settings._built)


if __name__ == "__main__":
    unittest.main()
