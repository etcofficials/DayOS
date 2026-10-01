"""DayOS v2 shell & Home UI: command palette, quick capture, inbox, notifications, dialogs, focus, dashboard."""

import os
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.ui.bus import bus  # noqa: E402
from src.ui.shell.commands import CommandRegistry, Command, fuzzy_score  # noqa: E402
from src.ui.theme import theme  # noqa: E402
from tests.helpers import FIXED_NOW, TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])
TODAY = FIXED_NOW.date()


def pump(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class CommandRegistryTests(unittest.TestCase):
    def test_fuzzy_matching_prefers_word_starts(self):
        self.assertGreater(fuzzy_score("new t", "New task"), fuzzy_score("new t", "Renew item tag"))
        self.assertEqual(fuzzy_score("xyz", "New task"), 0)
        reg = CommandRegistry()
        ran = []
        reg.add(Command("a", "Start focus session", run=lambda: ran.append("a")))
        reg.add(Command("b", "Open settings", keywords=("preferences",), run=lambda: ran.append("b")))
        self.assertEqual([c.id for c in reg.match("prefer")], ["b"])
        self.assertEqual(reg.match("sfs")[0].id, "a")
        self.assertTrue(reg.run("a"))
        self.assertEqual(ran, ["a"])


class ShellUiTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.ctx.settings.set("capture.global", False)  # never grab real system shortcuts in tests
        self.window = MainWindow(self.ctx)
        self.window.resize(1300, 860)
        self.window.show()
        pump(50)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        pump(20)
        super().tearDown()

    def test_palette_lists_commands_and_records_and_runs_them(self):
        from src.ui.shell.palette import CommandPalette

        self.ctx.tasks.create("Write the lab report")
        palette = CommandPalette(self.window)
        palette.edit.setText("lab report")
        palette._fill()
        texts = [palette.list.item(i).data(0x0100) for i in range(palette.list.count())]
        hits = [t for t in texts if t is not None and getattr(t, "kind", None) == "task"]
        self.assertEqual(len(hits), 1)
        palette.edit.setText("open insights")
        palette._fill()
        palette._run_item(palette.list.currentItem())
        pump(250)
        self.assertEqual(self.window.current_key(), "insights")

    def test_quick_capture_goes_to_inbox_and_converts_without_duplicates(self):
        from src.ui.shell.capture import CaptureWindow

        cap = CaptureWindow(self.window)
        cap.kind.set_current("idea")
        cap._kind_changed("idea")
        cap.text.setPlainText("Ask about the science fair")
        cap._save()
        self.assertEqual([i.text for i in self.ctx.inbox.open_items()], ["Ask about the science fair"])
        self.window.navigate("inbox")
        page = self.window.page("inbox")
        item = self.ctx.inbox.open_items()[0]
        page.convert(item, "note")
        self.assertEqual(self.ctx.inbox.count_open(), 0)
        notes = self.ctx.notes.list()
        self.assertEqual(len(notes), 1)
        self.assertIn("science fair", notes[0].content)
        self.assertEqual(self.ctx.inbox.processed()[0].result_kind, "note")

    def test_capture_suggests_dates_but_only_applies_them_when_ticked(self):
        from src.ui.shell.capture import CaptureWindow

        cap = CaptureWindow(self.window)
        cap.kind.set_current("task")
        cap._kind_changed("task")
        cap.text.setPlainText("Buy poster board tomorrow")
        self.assertTrue(cap.date_hint.isVisibleTo(cap))
        self.assertFalse(cap.date_hint.isChecked())
        cap._create_now()
        task = self.ctx.tasks.list("all")[0]
        self.assertIsNone(task.due_date)  # not applied without consent
        cap2 = CaptureWindow(self.window)
        cap2.kind.set_current("task")
        cap2._kind_changed("task")
        cap2.text.setPlainText("Return library book tomorrow")
        cap2.date_hint.setChecked(True)
        cap2._create_now()
        due = {t.title: t.due for t in self.ctx.tasks.list("all")}
        self.assertEqual(due["Return library book"], TODAY + timedelta(days=1))

    def test_notification_center_and_badge(self):
        from src.ui.shell.notifier import NotificationCenter

        self.ctx.reminders.add("Feed the cat", FIXED_NOW - timedelta(minutes=1))
        self.window.notifier.check()
        self.assertEqual(len(self.window.notifier.due), 1)
        self.assertTrue(self.ctx.notifications.was_notified(self.window.notifier.due[0]))
        center = NotificationCenter(self.window)
        labels = [w.text() for w in center.findChildren(QLabel)]
        self.assertIn("Feed the cat", labels)
        center._dismiss(self.window.notifier.due[0])
        self.assertEqual(self.ctx.notifications.due(), [])

    def test_task_dialog_saves_v2_fields(self):
        from src.ui.dialogs import TaskDialog

        pid = self.ctx.projects.create("Garden")
        blocker = self.ctx.tasks.create("Buy seeds")
        dlg = TaskDialog(self.ctx, self.window, default_due=TODAY)
        dlg.title_edit.setText("Plant tomatoes")
        dlg.project.set_current_id(pid)
        dlg.tags.setText("outdoor, spring")
        dlg.repeat.setCurrentIndex(dlg.repeat.findData("weekly"))
        dlg.remind.setChecked(True)
        dlg.remind_at.setDateTime(FIXED_NOW + timedelta(hours=2))
        dlg.waiting._ids.append((blocker, "Buy seeds"))
        nid = self.ctx.notes.create("Planting guide", "")
        dlg.links.pending.append(("note", nid, "Planting guide"))
        dlg._on_save()
        self.assertFalse(dlg.error.isVisibleTo(dlg))
        task = self.ctx.tasks.get(dlg.saved_id)
        self.assertEqual((task.project_name, task.tags, task.recurrence, task.blocked_by),
                         ("Garden", "outdoor, spring", "weekly", 1))
        self.assertIsNotNone(self.ctx.reminders.for_task(task.id))
        self.assertEqual([l.title for l in self.ctx.links.links_for("task", task.id)], ["Planting guide"])

    def test_event_dialog_repeat_and_reminder(self):
        from src.ui.pages.calendar import EventDialog

        dlg = EventDialog(self.ctx, self.window, day=TODAY)
        dlg.title_edit.setText("Swimming")
        dlg.repeat.setCurrentIndex(dlg.repeat.findData("weekly"))
        dlg.remind.setCurrentIndex(dlg.remind.findData(15))
        dlg.location.setText("Pool")
        dlg._on_save()
        self.assertFalse(dlg.error.isVisibleTo(dlg))
        events = self.ctx.schedule.events_between(TODAY, TODAY + timedelta(days=14))
        self.assertEqual(len(events), 3)
        self.assertEqual((events[0].remind_minutes, events[0].location), (15, "Pool"))
        # editing an expanded occurrence edits the series without moving its start
        edit = EventDialog(self.ctx, self.window, events[1])
        self.assertEqual(edit.day.value(), TODAY)

    def test_focus_session_linked_to_task_records_time(self):
        study = self.window.page("study")
        tid = self.ctx.tasks.create("Practise scales", due_date=TODAY)
        study.refresh()
        study.link_task(tid)
        study.kind_combo.setCurrentIndex(study.kind_combo.findData("practice"))
        study.session_note.setText("C major")
        study.start_pause()
        study.timer.accumulated = 600  # pretend ten minutes passed
        study._finish_early()
        session = self.ctx.study.history()[0]
        self.assertEqual((session.task_id, session.kind, session.note), (tid, "practice", "C major"))
        self.assertEqual(self.ctx.tasks.get(tid).actual_minutes, 10)

    def test_focus_mode_and_presets(self):
        study = self.window.page("study")
        self.window.navigate("study")
        study.apply_preset(50, 10)
        self.assertEqual((self.ctx.settings.get("study.focus_minutes"), self.ctx.settings.get("study.short_break")), (50, 10))
        study.toggle_focus_mode(True)
        self.assertTrue(self.window._collapsed)
        self.assertFalse(study.stats_card.isVisible())
        study.toggle_focus_mode(False)
        self.assertTrue(study.stats_card.isVisible())

    def test_dashboard_widgets_follow_settings(self):
        today = self.window.page("today")
        self.ctx.settings.set("dashboard.widgets", ["workload", "inbox", "plan"])
        today.refresh()
        self.assertEqual(today.board.widgets(), [today.workload_card, today.inbox_card, today.plan_card])
        self.ctx.settings.set("workload.hours", 1.0)
        self.ctx.settings.set("workload.weekend_hours", 1.0)
        self.ctx.tasks.create("Long essay", due_date=TODAY, estimate_minutes=120)
        today.refresh()
        texts = " ".join(w.text() for w in today.workload_card.findChildren(QLabel))
        self.assertIn("fuller than your time", texts)

    def test_weekly_review_saves(self):
        self.window.navigate("goals")
        goals = self.window.page("goals")
        goals.show_weekly_review()
        goals.weekly.fields["wins"].setPlainText("Finished the model")
        goals.weekly.save()
        from src.services.dates import week_start

        self.assertEqual(self.ctx.weekly.get(week_start(TODAY, 0)).wins, "Finished the model")

    def test_calendar_day_view_and_conflicts(self):
        self.ctx.schedule.create_event(title="A", date=TODAY, start_time="09:00", end_time="10:00")
        self.ctx.schedule.create_event(title="B", date=TODAY, start_time="09:30", end_time="10:30")
        self.window.navigate("calendar")
        cal = self.window.page("calendar")
        cal._day_anchor = TODAY
        cal.view.set_current("day")
        cal.refresh()
        self.assertEqual(len(cal.timeline.items), 2)
        self.assertTrue(cal.conflict_banner.isVisibleTo(cal))
        from src.ui.widgets.day_timeline import layout_columns

        self.assertEqual(sorted(c for _, c, _ in layout_columns(cal.timeline.items)), [0, 1])


if __name__ == "__main__":
    unittest.main()
