import unittest
from datetime import date, datetime, timedelta

from src.repositories.notes import normalize_tags
from src.services.dates import ValidationError
from src.services.quickadd import parse_quick_task
from tests.helpers import FIXED_NOW, TempHomeTestCase

TODAY = FIXED_NOW.date()


class TaskTests(TempHomeTestCase):
    def test_create_edit_and_read_back(self):
        sid = self.ctx.subjects.create("Maths")
        tid = self.ctx.tasks.create("Homework", description="p. 12", due_date=TODAY, due_time="14:30",
                                    priority=2, subject_id=sid, category="School", estimate_minutes=40)
        task = self.ctx.tasks.get(tid)
        self.assertEqual((task.title, task.due_date, task.due_time, task.priority), ("Homework", "2026-09-27", "14:30", 2))
        self.assertEqual(task.subject_name, "Maths")
        self.ctx.tasks.update(tid, title="Homework v2", priority=0)
        self.assertEqual(self.ctx.tasks.get(tid).title, "Homework v2")
        self.assertEqual(self.ctx.tasks.get(tid).priority, 0)

    def test_complete_and_reopen_sets_timestamps(self):
        tid = self.ctx.tasks.create("Essay", due_date=TODAY)
        self.ctx.tasks.set_completed(tid, True)
        task = self.ctx.tasks.get(tid)
        self.assertEqual(task.completed_at, "2026-09-27 10:00:00")
        # completing again keeps the original completion time
        self.set_now(FIXED_NOW + timedelta(hours=2))
        self.ctx.tasks.set_completed(tid, True)
        self.assertEqual(self.ctx.tasks.get(tid).completed_at, "2026-09-27 10:00:00")
        self.ctx.tasks.set_completed(tid, False)
        self.assertIsNone(self.ctx.tasks.get(tid).completed_at)

    def test_validation(self):
        with self.assertRaises(ValidationError):
            self.ctx.tasks.create("   ")
        with self.assertRaises(ValidationError):
            self.ctx.tasks.create("Timed", due_time="09:00")  # time without date
        with self.assertRaises(ValidationError):
            self.ctx.tasks.create("Bad date", due_date="2026-02-30")
        with self.assertRaises(ValidationError):
            self.ctx.tasks.create("Bad time", due_date=TODAY, due_time="25:61")
        with self.assertRaises(ValidationError):
            self.ctx.tasks.create("Bad estimate", estimate_minutes=-5)
        tid = self.ctx.tasks.create("Dated", due_date=TODAY, due_time="09:00")
        with self.assertRaises(ValidationError):
            self.ctx.tasks.update(tid, due_date=None)  # would orphan the time

    def test_filters_and_counts(self):
        overdue = self.ctx.tasks.create("Overdue", due_date=TODAY - timedelta(days=1))
        self.ctx.tasks.create("Today", due_date=TODAY)
        self.ctx.tasks.create("Later", due_date=TODAY + timedelta(days=3))
        self.ctx.tasks.create("Someday")
        done = self.ctx.tasks.create("Done today", due_date=TODAY)
        self.ctx.tasks.set_completed(done, True)
        names = lambda f: {t.title for t in self.ctx.tasks.list(f, ref=TODAY)}
        self.assertEqual(names("overdue"), {"Overdue"})
        self.assertEqual(names("today"), {"Today", "Done today"})
        self.assertEqual(names("upcoming"), {"Later"})
        self.assertEqual(names("nodate"), {"Someday"})
        self.assertEqual(names("completed"), {"Done today"})
        self.assertEqual(len(names("all")), 5)
        counts = self.ctx.tasks.counts(TODAY)
        self.assertEqual((counts["overdue"], counts["today"], counts["completed"], counts["total"]), (1, 2, 1, 5))
        self.assertTrue(self.ctx.tasks.get(overdue).is_overdue(TODAY))
        # a completed overdue task is no longer overdue
        self.ctx.tasks.set_completed(overdue, True)
        self.assertEqual(names("overdue"), set())

    def test_search_and_sort(self):
        self.ctx.tasks.create("banana", priority=0, due_date=TODAY + timedelta(days=2))
        self.ctx.tasks.create("apple", priority=2, due_date=TODAY + timedelta(days=5))
        self.ctx.tasks.create("cherry pie", description="bake")
        self.assertEqual([t.title for t in self.ctx.tasks.list("all", sort="title")], ["apple", "banana", "cherry pie"])
        self.assertEqual([t.title for t in self.ctx.tasks.list("all", sort="due")][:2], ["banana", "apple"])
        self.assertEqual(self.ctx.tasks.list("all", sort="priority")[0].title, "apple")
        self.assertEqual([t.title for t in self.ctx.tasks.list("all", search="BAKE")], ["cherry pie"])
        self.assertEqual(self.ctx.tasks.list("all", search="'; DROP TABLE tasks; --"), [])
        self.assertEqual(len(self.ctx.tasks.list("all")), 3)

    def test_delete_undo_and_isolation(self):
        sid = self.ctx.subjects.create("Physics")
        gid = self.ctx.goals.create("Goal")
        tid = self.ctx.tasks.create("With checklist", subject_id=sid, goal_id=gid)
        self.ctx.tasks.replace_subtasks(tid, [("one", True), ("two", False)])
        other = self.ctx.tasks.create("Unrelated", subject_id=sid)
        snapshot = self.ctx.tasks.delete(tid)
        self.assertIsNone(self.ctx.tasks.get(tid))
        self.assertEqual(self.ctx.db.scalar("SELECT COUNT(*) FROM subtasks"), 0)
        # nothing unrelated was removed
        self.assertIsNotNone(self.ctx.tasks.get(other))
        self.assertIsNotNone(self.ctx.subjects.get(sid))
        self.assertIsNotNone(self.ctx.goals.get(gid))
        restored = self.ctx.tasks.restore(snapshot)
        self.assertEqual(restored, tid)
        self.assertEqual([(s.title, s.done) for s in self.ctx.tasks.subtasks(tid)], [("one", 1), ("two", 0)])
        self.assertEqual(self.ctx.tasks.get(tid).goal_id, gid)

    def test_deleting_goal_or_subject_unlinks_tasks(self):
        sid = self.ctx.subjects.create("Chemistry")
        gid = self.ctx.goals.create("Big goal")
        tid = self.ctx.tasks.create("Linked", subject_id=sid, goal_id=gid)
        self.ctx.goals.delete(gid)
        self.ctx.subjects.delete(sid)
        task = self.ctx.tasks.get(tid)
        self.assertIsNotNone(task)
        self.assertIsNone(task.goal_id)
        self.assertIsNone(task.subject_id)

    def test_completed_on_uses_local_date(self):
        tid = self.ctx.tasks.create("Late night")
        self.set_now(datetime(2026, 9, 27, 23, 59, 30))
        self.ctx.tasks.set_completed(tid, True)
        self.assertEqual(self.ctx.tasks.completed_on(date(2026, 9, 27)), 1)
        self.assertEqual(self.ctx.tasks.completed_on(date(2026, 9, 28)), 0)


class QuickAddTests(unittest.TestCase):
    def test_parsing(self):
        ref = date(2026, 9, 27)  # Sunday
        q = parse_quick_task("Revise algebra tomorrow !high #Maths", ref)
        self.assertEqual((q.title, q.due_date, q.priority, q.category), ("Revise algebra", date(2026, 9, 28), 2, "Maths"))
        q = parse_quick_task("Call grandma fri !low", ref)
        self.assertEqual((q.title, q.due_date, q.priority), ("Call grandma", date(2026, 10, 2), 0))
        self.assertEqual(parse_quick_task("Gym sunday", ref).due_date, date(2026, 10, 4))  # next week, not today
        self.assertEqual(parse_quick_task("today", ref).title, "today")  # never an empty title


class NoteTests(TempHomeTestCase):
    def test_crud_search_tags_pin(self):
        a = self.ctx.notes.create("Physics", "Newton's laws", "science, #Lecture, science")
        b = self.ctx.notes.create("Shopping", "milk")
        self.assertEqual(self.ctx.notes.get(a).tags, "science, Lecture")
        self.set_now(FIXED_NOW + timedelta(minutes=5))
        self.ctx.notes.save(b, "Shopping list", "milk, eggs", "home")
        self.assertEqual(self.ctx.notes.list()[0].id, b)  # most recently updated first
        self.ctx.notes.set_pinned(a, True)
        self.assertEqual(self.ctx.notes.list()[0].id, a)  # pinned first
        self.assertEqual([n.id for n in self.ctx.notes.list("eggs")], [b])
        self.assertEqual([n.id for n in self.ctx.notes.list(tag="Lecture")], [a])
        self.assertEqual(self.ctx.notes.all_tags(), ["home", "Lecture", "science"])
        note = self.ctx.notes.get(b)
        self.assertEqual(note.updated_at, "2026-09-27 10:05:00")
        self.assertEqual(note.created_at, "2026-09-27 10:00:00")
        self.ctx.notes.delete(a)
        self.assertIsNone(self.ctx.notes.get(a))
        self.reopen()
        self.assertEqual(self.ctx.notes.get(b).content, "milk, eggs")

    def test_normalize_tags(self):
        self.assertEqual(normalize_tags(" a, #b ,A,, c "), "a, b, c")


class GoalTests(TempHomeTestCase):
    def test_goal_progress_history_and_status(self):
        gid = self.ctx.goals.create("Read 12 books", target_value=12, unit="books", target_date=TODAY + timedelta(days=90))
        self.ctx.goals.log_progress(gid, 3, "first three")
        self.ctx.goals.log_progress(gid, 5)
        goal = self.ctx.goals.get(gid)
        self.assertEqual(goal.current_value, 5)
        self.assertAlmostEqual(goal.fraction, 5 / 12)
        self.assertEqual([h.value for h in self.ctx.goals.history(gid)], [5, 3])
        with self.assertRaises(ValidationError):
            self.ctx.goals.log_progress(gid, -1)
        with self.assertRaises(ValidationError):
            self.ctx.goals.log_progress(gid, "lots")
        with self.assertRaises(ValidationError):
            self.ctx.goals.create("Bad", target_value=0)
        self.ctx.goals.set_status(gid, "completed")
        self.assertEqual(self.ctx.goals.get(gid).status, "completed")
        self.assertIsNotNone(self.ctx.goals.get(gid).completed_at)
        self.ctx.goals.set_status(gid, "active")
        self.assertIsNone(self.ctx.goals.get(gid).completed_at)

    def test_linked_task_completion_does_not_complete_goal(self):
        gid = self.ctx.goals.create("Project")
        tid = self.ctx.tasks.create("Only step", goal_id=gid)
        self.ctx.tasks.set_completed(tid, True)
        goal = self.ctx.goals.get(gid)
        self.assertEqual((goal.status, goal.linked_tasks, goal.linked_done), ("active", 1, 1))

    def test_journal_merges_fields(self):
        self.ctx.journal.save(TODAY, intention="Be kind")
        self.ctx.journal.save(TODAY, reflection="Good day")
        entry = self.ctx.journal.get(TODAY)
        self.assertEqual((entry.intention, entry.reflection), ("Be kind", "Good day"))
        self.assertEqual(self.ctx.journal.get(TODAY + timedelta(days=1)).intention, "")
        self.assertEqual(len(self.ctx.journal.recent()), 1)


if __name__ == "__main__":
    unittest.main()
