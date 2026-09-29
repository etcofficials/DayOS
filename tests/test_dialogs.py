"""Construct every dialog and save through the main ones (offscreen)."""

import os
import unittest
from datetime import timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from src.ui.theme import theme  # noqa: E402
from tests.helpers import FIXED_NOW, TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])
TODAY = FIXED_NOW.date()


class DialogTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("light")
        self.parent = QWidget()

    def tearDown(self):
        self.parent.deleteLater()
        app.processEvents()
        super().tearDown()

    def test_task_dialog_create_and_edit(self):
        from src.ui.dialogs import TaskDialog

        sid = self.ctx.subjects.create("Maths")
        dlg = TaskDialog(self.ctx, self.parent, default_due=TODAY)
        dlg.title_edit.setText("From dialog")
        dlg.subject.set_current_id(sid)
        dlg.priority.setCurrentIndex(2)
        dlg.checklist.add_row("step one", False)
        dlg.checklist.add_row("   ", False)  # blank rows are ignored
        dlg._on_save()
        self.assertFalse(dlg.error.isVisibleTo(dlg))
        task = self.ctx.tasks.list("all")[0]
        self.assertEqual((task.title, task.due_date, task.priority, task.subject_id, task.subtask_total),
                         ("From dialog", TODAY.isoformat(), 2, sid, 1))
        edit = TaskDialog(self.ctx, self.parent, task)
        edit.due.set_value(None)
        edit._on_save()
        self.assertIsNone(self.ctx.tasks.get(task.id).due_date)
        bad = TaskDialog(self.ctx, self.parent)
        bad._on_save()  # empty title
        self.assertTrue(bad.error.isVisibleTo(bad))
        self.assertEqual(len(self.ctx.tasks.list("all")), 1)

    def test_other_dialogs_construct_and_save(self):
        from src.ui.dialogs import DailyReviewDialog, ManualStudyDialog, QuickNoteDialog
        from src.ui.pages.calendar import EventDialog, TimetableDialog
        from src.ui.pages.exams import ChaptersDialog, ExamDialog, MistakeDialog, TestDialog
        from src.ui.pages.goals import GoalDialog, ProgressDialog
        from src.ui.pages.habits import HabitDialog
        from src.ui.subjects_dialog import SubjectsDialog

        note = QuickNoteDialog(self.ctx, self.parent)
        note.content.setPlainText("captured")
        note._on_save()
        self.assertEqual(self.ctx.notes.count(), 1)

        study = ManualStudyDialog(self.ctx, self.parent)
        study.minutes.setValue(40)
        study._on_save()
        self.assertEqual(self.ctx.study.history()[0].actual_seconds, 2400)

        review = DailyReviewDialog(self.ctx, self.parent)
        review.reflection.setPlainText("calm day")
        review._on_save()
        self.assertEqual(self.ctx.journal.get(TODAY).reflection, "calm day")

        habit = HabitDialog(self.ctx, self.parent)
        habit.name.setText("Journal")
        habit._preset(0b0011111)
        habit._on_save()
        self.assertEqual(self.ctx.habits.list()[0].weekdays, 0b0011111)

        goal = GoalDialog(self.ctx, self.parent)
        goal.title_edit.setText("Save money")
        goal.measurable.setChecked(True)
        goal.target.setValue(100)
        goal.start_value.setValue(10)
        goal._on_save()
        g = self.ctx.goals.list()[0]
        self.assertEqual((g.target_value, g.current_value, len(self.ctx.goals.history(g.id))), (100, 10, 1))
        progress = ProgressDialog(self.ctx, g, self.parent)
        progress.value.setValue(25)
        progress._on_save()
        self.assertEqual(self.ctx.goals.get(g.id).current_value, 25)

        event = EventDialog(self.ctx, self.parent, day=TODAY)
        event.title_edit.setText("Concert")
        event._on_save()
        self.assertEqual(self.ctx.schedule.events_between(TODAY, TODAY)[0].title, "Concert")

        entry = TimetableDialog(self.ctx, self.parent, weekday=2)
        entry.title_edit.setText("Art")
        entry._on_save()
        self.assertEqual(self.ctx.schedule.entries()[0].weekday, 2)

        exam = ExamDialog(self.ctx, self.parent)
        exam.title_edit.setText("Finals")
        exam.day.set_value(TODAY + timedelta(days=20))
        exam.chapters.setPlainText("One\nTwo\n\nThree")
        exam._on_save()
        x = self.ctx.exams.exams()[0]
        self.assertEqual(x.chapter_total, 3)
        chapters = ChaptersDialog(self.ctx, x, self.parent)
        chapters.text.setPlainText("Four")
        chapters._on_save()
        self.assertEqual(len(self.ctx.exams.chapters(x.id)), 4)

        mistake = MistakeDialog(self.ctx, self.parent)
        mistake.question.setPlainText("Wrong unit")
        mistake._on_save()
        self.assertEqual(len(self.ctx.exams.mistakes()), 1)

        test = TestDialog(self.ctx, self.parent)
        test.title_edit.setText("Mock")
        test.marks.setValue(120)
        test.max_marks.setValue(100)
        test._on_save()  # invalid: marks above maximum
        self.assertTrue(test.error.isVisibleTo(test))
        test.marks.setValue(80)
        test._on_save()
        self.assertEqual(self.ctx.exams.tests()[0].percent, 80.0)

        subjects = SubjectsDialog(self.ctx, self.parent)
        subjects.name.setText("Geography")
        subjects._add()
        self.assertIn("Geography", [s.name for s in self.ctx.subjects.list()])


if __name__ == "__main__":
    unittest.main()
