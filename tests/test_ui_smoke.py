"""Builds the real main window offscreen and exercises key flows."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.ui.bus import bus  # noqa: E402
from src.ui.theme import theme  # noqa: E402
from tests.helpers import FIXED_NOW, TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])


class UiSmokeTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("dark")
        self.window = MainWindow(self.ctx)
        self.window.show()
        app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        app.processEvents()
        super().tearDown()

    def test_every_page_opens_in_every_theme(self):
        from src.ui.themes import THEME_IDS

        for theme_id in THEME_IDS:
            theme.apply(theme_id)
            for key in self.window.page_keys():
                self.window.navigate(key)
                app.processEvents()
                self.assertIs(self.window.stack.currentWidget(), self.window.pages[key])
                if key in self.window.nav_buttons:
                    self.assertTrue(self.window.nav_buttons[key].isChecked())

    def test_dashboard_reflects_new_data_without_restart(self):
        self.window.navigate("today")
        today_page = self.window.pages["today"]
        self.ctx.tasks.create("Dashboard task", due_date=FIXED_NOW.date())
        bus.notify("tasks")
        for _ in range(3):  # refresh is queued; new child widgets are shown on the next pass
            app.processEvents()
        from PySide6.QtWidgets import QLabel

        texts = [w.text() for w in today_page.plan_card.findChildren(QLabel) if w.isVisible()]
        self.assertIn("Dashboard task", texts)
        self.assertIn("0 of 1 done", texts)

    def test_notes_autosave_flushes_on_leave(self):
        self.window.navigate("notes")
        page = self.window.pages["notes"]
        page.new_item()
        page.title_edit.setText("Unsaved title")
        page.title_edit.textEdited.emit("Unsaved title")
        page.editor.setPlainText("typed but not yet autosaved")
        self.window.navigate("today")  # leaving the page must save immediately
        app.processEvents()
        notes = self.ctx.notes.list()
        self.assertEqual([(n.title, n.content) for n in notes], [("Unsaved title", "typed but not yet autosaved")])

    def test_empty_new_note_is_discarded(self):
        self.window.navigate("notes")
        self.window.pages["notes"].new_item()
        self.window.navigate("tasks")
        app.processEvents()
        self.assertEqual(self.ctx.notes.count(), 0)

    def test_sidebar_collapse_persists(self):
        self.window.set_sidebar_collapsed(True, animate=False)
        self.assertTrue(self.ctx.settings.get("sidebar_collapsed"))
        self.window.set_sidebar_collapsed(False, animate=False)
        self.assertFalse(self.ctx.settings.get("sidebar_collapsed"))

    def test_study_timer_start_pause_reset(self):
        self.window.navigate("study")
        page = self.window.pages["study"]
        page._start_pause()
        self.assertEqual(page.timer.state, "running")
        self.assertIsNotNone(self.ctx.settings.get("state.study.active"))
        page._start_pause()
        self.assertEqual(page.timer.state, "paused")
        page._reset()  # under a minute: resets without asking
        self.assertEqual(page.timer.state, "idle")
        self.assertIsNone(self.ctx.settings.get("state.study.active"))


if __name__ == "__main__":
    unittest.main()
