"""Redesign behaviour: motion helpers, theme switching, navigation pill, dashboard timer, data folder."""

import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QElapsedTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from src import config  # noqa: E402
from src.ui import anim  # noqa: E402
from src.ui.bus import bus  # noqa: E402
from src.ui.theme import DARK, LIGHT, theme  # noqa: E402
from tests.helpers import FIXED_NOW, TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms: int) -> None:
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()


class MotionHelperTests(unittest.TestCase):
    def tearDown(self):
        anim.set_motion_provider(lambda: True)

    def test_tween_reaches_end_value(self):
        owner = QWidget()
        values = []
        anim.tween(owner, 0.0, 1.0, 60, values.append)
        pump(200)
        self.assertAlmostEqual(values[-1], 1.0)
        self.assertGreater(len(values), 1)

    def test_reduced_motion_applies_final_value_immediately(self):
        anim.set_motion_provider(lambda: False)
        owner = QWidget()
        values = []
        finished = []
        anim.tween(owner, 0.0, 1.0, 5000, values.append, lambda: finished.append(True))
        self.assertEqual(values, [1.0])
        self.assertEqual(finished, [True])

    def test_snapshot_overlay_is_removed_and_mouse_transparent(self):
        host = QWidget()
        host.resize(200, 120)
        host.show()
        pump(20)
        anim.snapshot_fade(host, 80)
        overlays = [c for c in host.findChildren(QLabel)]
        self.assertEqual(len(overlays), 1)
        from PySide6.QtCore import Qt

        self.assertTrue(overlays[0].testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        pump(300)
        app.sendPostedEvents(None, 52)  # QEvent.DeferredDelete
        self.assertEqual([c for c in host.findChildren(QLabel) if c.isVisible()], [])
        host.close()


class PaletteTests(unittest.TestCase):
    def test_palettes_define_the_same_tokens(self):
        self.assertEqual(set(LIGHT), set(DARK))

    def test_specified_brand_colours(self):
        self.assertEqual((LIGHT["bg"], LIGHT["sidebar"], LIGHT["surface"]), ("#F5F2E9", "#E9EDE3", "#FFFDF7"))
        self.assertEqual((LIGHT["accent"], LIGHT["accent_dark"], LIGHT["terracotta"]), ("#71896C", "#425845", "#C77D59"))
        self.assertEqual((DARK["bg"], DARK["surface"], DARK["accent"]), ("#191D1A", "#272E28", "#A6BE9B"))


class RedesignUiTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow

        theme.set_asset_dir(self.paths.cache_dir)
        self.ctx.settings.subscribe(lambda key, value: theme.apply(value) if key == "theme" else None)
        theme.apply(self.ctx.settings.get("theme"))
        self.window = MainWindow(self.ctx)
        self.window.resize(1400, 900)
        self.window.show()
        pump(50)

    def tearDown(self):
        study = self.window.pages["study"]
        if study.timer.is_active:
            study._reset()
        self.window.close()
        self.window.deleteLater()
        pump(20)
        super().tearDown()

    def test_light_theme_is_the_first_launch_default(self):
        self.assertEqual(self.ctx.settings.get("theme"), "light")
        self.assertEqual(theme.mode, "light")

    def test_dashboard_theme_toggle_switches_and_persists(self):
        today = self.window.pages["today"]
        today.toggle_theme()
        pump(50)
        self.assertEqual(theme.mode, "dark")
        self.window.close()
        pump(20)
        self.reopen()
        self.assertEqual(self.ctx.settings.get("theme"), "dark")
        theme.apply("light")

    def test_navigation_moves_the_selection_pill(self):
        sidebar = self.window.sidebar
        self.window.navigate("notes")
        pump(400)
        target = self.window.nav_buttons["notes"]
        top = target.mapTo(sidebar, target.rect().topLeft()).y()
        self.assertAlmostEqual(sidebar._pill.y(), top + 1.5, delta=1.0)
        self.assertTrue(target.isChecked())

    def test_dashboard_study_nook_drives_the_real_timer(self):
        today = self.window.pages["today"]
        study = self.window.pages["study"]
        today.nook.mode.set_current("focus")
        today.nook._start()
        self.assertEqual(study.timer.state, "running")
        pump(60)
        self.assertEqual(today.nook.start.text(), "Pause")
        self.assertFalse(today.nook.subject.isEnabled())
        today.nook._start()
        self.assertEqual(study.timer.state, "paused")
        study._reset()
        self.assertEqual(today.nook.start.text(), "Start focus")

    def test_task_completion_from_dashboard_row(self):
        tid = self.ctx.tasks.create("Water the plants", due_date=FIXED_NOW.date())
        bus.notify("tasks")
        pump(60)
        today = self.window.pages["today"]
        from src.ui.pages.today import PlanRow
        from src.ui.widgets.common import RoundCheck

        row = next(r for r in today.plan_card.findChildren(PlanRow) if r.task.id == tid)
        row.findChild(RoundCheck).click()
        self.assertTrue(self.ctx.tasks.get(tid).done)
        pump(450)  # list refresh waits for the tick animation
        self.assertEqual(today.plan_count.text(), "1 of 1 done")
        self.assertAlmostEqual(today.plan_progress.value(), 1.0)

    def test_intention_edit_in_place(self):
        today = self.window.pages["today"]
        today.intention.start_edit()
        today.intention.edit.setText("Rest well and read")
        today.intention.finish()
        self.assertEqual(self.ctx.journal.get(FIXED_NOW.date()).intention, "Rest well and read")
        self.assertEqual(today.intention.text.text(), "Rest well and read")

    def test_empty_database_shows_empty_states_not_sample_data(self):
        today = self.window.pages["today"]
        texts = {w.text() for w in today.findChildren(QLabel)}
        self.assertIn("A clear page", texts)
        self.assertIn("No rituals yet", texts)
        self.assertEqual(self.ctx.tasks.counts()["total"], 0)


class DataFolderTests(unittest.TestCase):
    def test_frozen_app_uses_portable_folder_next_to_exe(self):
        base = Path(__file__).resolve().parent / ".tmp" / "frozen-app"
        base.mkdir(parents=True, exist_ok=True)
        exe = base / "DayOS.exe"
        with mock.patch.object(config.sys, "frozen", True, create=True), \
                mock.patch.object(config.sys, "executable", str(exe)), \
                mock.patch.dict(os.environ, {"DAYOS_HOME": ""}):
            self.assertEqual(config.default_home(), base / "DayOS Data")

    def test_environment_override_wins(self):
        with mock.patch.dict(os.environ, {"DAYOS_HOME": str(Path(__file__).resolve().parent / ".tmp" / "x")}):
            self.assertTrue(str(config.default_home()).endswith("x"))


if __name__ == "__main__":
    unittest.main()
