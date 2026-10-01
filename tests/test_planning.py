"""DayOS v2 Home & planning: recurrence, tasks, events, search, reminders, workload, reviews, inbox, links."""

import unittest
from datetime import date, datetime, timedelta

from src.services import recurrence
from src.services.dates import ValidationError
from src.services.notifications import in_quiet_hours
from src.services.reviews import day_summary, week_summary
from src.services.search import build_match
from src.services.transfer import export_json, import_json, unexported_tables
from src.services.workload import day_workload, suggest_moves
from tests.helpers import FIXED_NOW, TempHomeTestCase

TODAY = FIXED_NOW.date()  # Sunday 27 Sep 2026


class RecurrenceTests(unittest.TestCase):
    def test_simple_rules(self):
        d = date(2026, 9, 28)  # Monday
        self.assertEqual(recurrence.next_date(d, "daily"), date(2026, 9, 29))
        self.assertEqual(recurrence.next_date(d, "daily", 3), date(2026, 10, 1))
        self.assertEqual(recurrence.next_date(d, "weekly"), date(2026, 10, 5))
        self.assertEqual(recurrence.next_date(date(2026, 10, 2), "weekdays"), date(2026, 10, 5))  # Fri -> Mon
        self.assertIsNone(recurrence.next_date(d, ""))

    def test_month_end_and_leap_day(self):
        jan31 = date(2026, 1, 31)
        self.assertEqual(recurrence.next_date(jan31, "monthly"), date(2026, 2, 28))
        self.assertEqual(recurrence.next_date(jan31, "monthly", after=date(2026, 2, 28)), date(2026, 3, 31))
        leap = date(2028, 2, 29)
        self.assertEqual(recurrence.next_date(leap, "yearly"), date(2029, 2, 28))
        self.assertTrue(recurrence.occurs_on(jan31, "monthly", 1, date(2026, 4, 30)))
        self.assertFalse(recurrence.occurs_on(jan31, "monthly", 1, date(2026, 4, 29)))

    def test_occurrences_are_bounded(self):
        d = date(2026, 1, 1)
        days = recurrence.occurrences(d, "weekly", 2, date(2026, 1, 1), date(2026, 3, 1))
        self.assertEqual(days[:3], [date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 29)])
        self.assertEqual(recurrence.occurrences(d, "daily", 1, d, d + timedelta(days=9), until=d + timedelta(days=4)),
                         [d + timedelta(days=i) for i in range(5)])
        self.assertEqual(recurrence.describe("weekly", 2), "Every 2 weeks")


class TaskPlanningTests(TempHomeTestCase):
    def test_tags_projects_and_filters(self):
        pid = self.ctx.projects.create("Website")
        t1 = self.ctx.tasks.create("Draft homepage", tags="#web, writing, Web", project_id=pid, due_date=TODAY)
        self.ctx.tasks.create("Groceries", tags="home", due_date=TODAY + timedelta(days=3))
        self.assertEqual(self.ctx.tasks.get(t1).tags, "web, writing")
        self.assertEqual([t.title for t in self.ctx.tasks.list("all", tag="web")], ["Draft homepage"])
        self.assertEqual([t.title for t in self.ctx.tasks.list("all", project_id=pid)], ["Draft homepage"])
        self.assertEqual(len(self.ctx.tasks.list("week", ref=TODAY)), 2)
        self.assertEqual(self.ctx.tasks.get(t1).project_name, "Website")
        self.assertEqual(self.ctx.tasks.tags(), ["home", "web", "writing"])
        self.assertEqual(self.ctx.projects.get(pid).open_tasks, 1)

    def test_completing_a_repeating_task_creates_the_next_once(self):
        tid = self.ctx.tasks.create("Water plants", due_date=TODAY, recurrence="weekly")
        self.ctx.tasks.replace_subtasks(tid, [("indoor", True), ("balcony", False)])
        nxt = self.ctx.tasks.set_completed(tid, True)
        self.assertIsNotNone(nxt)
        new = self.ctx.tasks.get(nxt)
        self.assertEqual((new.title, new.due, new.done), ("Water plants", TODAY + timedelta(days=7), False))
        self.assertEqual([(s.title, s.done) for s in self.ctx.tasks.subtasks(nxt)], [("indoor", 0), ("balcony", 0)])
        self.ctx.tasks.set_completed(tid, False)
        self.assertIsNone(self.ctx.tasks.set_completed(tid, True))  # reopen + complete again: no duplicate
        self.assertEqual(len(self.ctx.tasks.list("all")), 2)

    def test_repeating_task_needs_a_due_date(self):
        with self.assertRaises(ValidationError):
            self.ctx.tasks.create("Floating", recurrence="daily")

    def test_dependencies_reject_cycles(self):
        a = self.ctx.tasks.create("A")
        b = self.ctx.tasks.create("B")
        c = self.ctx.tasks.create("C")
        self.ctx.tasks.set_dependencies(b, [a])
        self.ctx.tasks.set_dependencies(c, [b])
        self.assertEqual(self.ctx.tasks.get(c).blocked_by, 1)
        with self.assertRaises(ValidationError):
            self.ctx.tasks.set_dependencies(a, [c])
        self.ctx.tasks.set_completed(b, True)
        self.assertEqual(self.ctx.tasks.get(c).blocked_by, 0)

    def test_actual_time(self):
        tid = self.ctx.tasks.create("Essay")
        self.ctx.tasks.add_minutes(tid, 25)
        self.ctx.tasks.add_minutes(tid, 20)
        self.assertEqual(self.ctx.tasks.get(tid).actual_minutes, 45)


class EventRecurrenceTests(TempHomeTestCase):
    def test_repeating_events_expand_and_skip(self):
        eid = self.ctx.schedule.create_event(title="Choir", date=TODAY, start_time="18:00", end_time="19:00",
                                             recurrence="weekly", location="Hall")
        events = self.ctx.schedule.events_between(TODAY, TODAY + timedelta(days=20))
        self.assertEqual([e.date for e in events], [str(TODAY + timedelta(days=7 * i)) for i in range(3)])
        self.ctx.schedule.skip_event_occurrence(eid, TODAY + timedelta(days=7))
        self.assertEqual(len(self.ctx.schedule.events_between(TODAY, TODAY + timedelta(days=20))), 2)
        self.ctx.schedule.end_event_series(eid, TODAY + timedelta(days=1))
        self.assertEqual(len(self.ctx.schedule.events_between(TODAY, TODAY + timedelta(days=20))), 1)
        agenda = self.ctx.schedule.day_agenda(TODAY)
        self.assertTrue(agenda[0].recurring)
        self.assertIn("Hall", agenda[0].detail)

    def test_conflicts_are_reported(self):
        self.ctx.schedule.create_event(title="Dentist", date=TODAY, start_time="10:00", end_time="11:00")
        self.ctx.schedule.create_event(title="Call", date=TODAY, start_time="10:30", end_time="10:45")
        found = self.ctx.schedule.conflicts_between(TODAY, TODAY)
        self.assertEqual(len(found), 1)
        self.assertEqual({found[0][1].title, found[0][2].title}, {"Dentist", "Call"})

    def test_reminder_needs_start_time(self):
        with self.assertRaises(ValidationError):
            self.ctx.schedule.create_event(title="All day", date=TODAY, remind_minutes=10)


class SearchTests(TempHomeTestCase):
    def test_finds_records_across_modules_and_stays_in_sync(self):
        self.ctx.tasks.create("Photosynthesis worksheet")
        nid = self.ctx.notes.create("Biology", "Notes on photosynthesis and chlorophyll")
        self.ctx.projects.create("Greenhouse sensors", description="Photo resistor experiments")
        hits = self.ctx.search.search("photo")
        self.assertEqual({h.kind for h in hits}, {"task", "note", "project"})
        self.ctx.notes.delete(nid)
        self.assertNotIn("note", {h.kind for h in self.ctx.search.search("photo")})
        self.assertEqual(self.ctx.search.search('"; DROP TABLE tasks; --'), [])  # quoted safely
        self.assertEqual(self.ctx.search.rebuild(), 2)

    def test_match_builder(self):
        self.assertEqual(build_match("hello wor"), '"hello"* "wor"*')
        self.assertIsNone(build_match("  ...  "))


class InboxAndLinkTests(TempHomeTestCase):
    def test_inbox_conversion_marks_processed(self):
        iid = self.ctx.inbox.add("idea", "Start a reading club")
        self.assertEqual(self.ctx.inbox.count_open(), 1)
        tid = self.ctx.tasks.create("Start a reading club")
        self.ctx.inbox.mark_processed(iid, "task", tid)
        self.assertEqual(self.ctx.inbox.count_open(), 0)
        with self.assertRaises(ValidationError):
            self.ctx.inbox.add("link", "x", url="javascript:alert(1)")

    def test_links_are_bidirectional_and_deduplicated(self):
        tid = self.ctx.tasks.create("Write report")
        nid = self.ctx.notes.create("Report outline", "")
        self.ctx.links.link("task", tid, "note", nid)
        self.assertIsNone(self.ctx.links.link("note", nid, "task", tid))
        self.assertEqual([(l.kind, l.title) for l in self.ctx.links.links_for("task", tid)], [("note", "Report outline")])
        self.assertEqual([(l.kind, l.title) for l in self.ctx.links.links_for("note", nid)], [("task", "Write report")])
        self.ctx.tasks.delete(tid)
        self.assertEqual(self.ctx.links.links_for("note", nid), [])
        self.assertEqual(self.ctx.links.prune(), 1)


class ReminderTests(TempHomeTestCase):
    def test_due_snooze_dismiss(self):
        rid = self.ctx.reminders.add("Call grandma", FIXED_NOW - timedelta(minutes=5))
        notices = self.ctx.notifications.due(FIXED_NOW)
        self.assertEqual([n.title for n in notices], ["Call grandma"])
        self.ctx.notifications.snooze(notices[0], 30)
        self.assertEqual(self.ctx.notifications.due(FIXED_NOW), [])
        self.assertEqual([n.title for n in self.ctx.notifications.due(FIXED_NOW + timedelta(minutes=31))], ["Call grandma"])
        self.ctx.reminders.dismiss(rid)
        self.assertEqual(self.ctx.notifications.due(FIXED_NOW + timedelta(hours=2)), [])

    def test_event_and_habit_reminders(self):
        self.ctx.schedule.create_event(title="Piano", date=TODAY, start_time="10:20", end_time="11:00", remind_minutes=15)
        hid = self.ctx.habits.create("Stretch", remind_time="09:30")
        self.ctx.settings.set("notify.habit", True)
        due = self.ctx.notifications.due(FIXED_NOW + timedelta(minutes=10))  # 10:10
        self.assertEqual({n.category for n in due}, {"event", "habit"})
        self.ctx.habits.set_done(hid, TODAY, True)
        due = self.ctx.notifications.due(FIXED_NOW + timedelta(minutes=10))
        self.assertEqual([n.category for n in due], ["event"])
        self.ctx.notifications.dismiss(due[0])
        self.assertEqual(self.ctx.notifications.due(FIXED_NOW + timedelta(minutes=10)), [])
        self.ctx.settings.set("notify.event", False)
        self.assertEqual(self.ctx.notifications.upcoming(FIXED_NOW - timedelta(hours=1)), [])

    def test_next_wakeup_and_quiet_hours(self):
        self.ctx.reminders.add("Later", FIXED_NOW + timedelta(hours=3))
        self.assertEqual(self.ctx.notifications.next_wakeup(FIXED_NOW), FIXED_NOW + timedelta(hours=3))
        self.assertTrue(in_quiet_hours(datetime(2026, 9, 27, 23, 0), "22:00", "07:00"))
        self.assertTrue(in_quiet_hours(datetime(2026, 9, 27, 6, 59), "22:00", "07:00"))
        self.assertFalse(in_quiet_hours(datetime(2026, 9, 27, 7, 0), "22:00", "07:00"))
        self.assertTrue(in_quiet_hours(datetime(2026, 9, 27, 13, 0), "12:00", "14:00"))

    def test_task_reminder_is_replaced(self):
        tid = self.ctx.tasks.create("Submit form")
        self.ctx.reminders.set_task_reminder(tid, "Submit form", FIXED_NOW + timedelta(hours=1))
        self.ctx.reminders.set_task_reminder(tid, "Submit form", FIXED_NOW + timedelta(hours=2))
        self.assertEqual(len(self.ctx.reminders.upcoming()), 1)
        self.ctx.reminders.set_task_reminder(tid, "Submit form", None)
        self.assertEqual(self.ctx.reminders.upcoming(), [])


class WorkloadAndReviewTests(TempHomeTestCase):
    def test_workload_needs_available_time_and_suggests_moves(self):
        self.ctx.tasks.create("Essay", due_date=TODAY, estimate_minutes=120, priority=2)
        self.ctx.tasks.create("Tidy desk", due_date=TODAY, estimate_minutes=30, priority=0)
        self.ctx.tasks.create("Read", due_date=TODAY)
        self.ctx.schedule.create_event(title="Club", date=TODAY, start_time="15:00", end_time="16:30")
        load = day_workload(self.ctx, TODAY)
        self.assertIsNone(load.available_minutes)
        self.assertEqual((load.scheduled_minutes, load.task_minutes, load.unestimated_tasks), (90, 150, 1))
        self.assertEqual(load.over_by, 0)  # nothing to compare against yet
        self.ctx.settings.set("workload.weekend_hours", 3.0)
        load = day_workload(self.ctx, TODAY)
        self.assertEqual(load.over_by, 60)
        self.assertEqual([t.title for t in load.suggestions], ["Tidy desk", "Essay"])

    def test_suggest_moves_prefers_low_priority(self):
        from src.models import Task

        tasks = [Task(1, "big", priority=2, estimate_minutes=90), Task(2, "small", priority=0, estimate_minutes=20)]
        self.assertEqual([t.title for t in suggest_moves(tasks, 15)], ["small"])

    def test_day_and_week_summaries(self):
        tid = self.ctx.tasks.create("Done thing", due_date=TODAY)
        self.ctx.tasks.set_completed(tid, True)
        self.ctx.tasks.create("Open thing", due_date=TODAY)
        self.ctx.journal.save(TODAY, improve="Start earlier")
        day = day_summary(self.ctx, TODAY)
        self.assertEqual((day.completed, day.still_open), (["Done thing"], ["Open thing"]))
        self.assertEqual(self.ctx.journal.get(TODAY).improve, "Start earlier")
        week = week_summary(self.ctx, TODAY - timedelta(days=6))
        self.assertEqual(week.tasks_completed, 1)
        self.assertEqual(week.tasks_carried_over, ["Open thing"])
        self.ctx.weekly.save(TODAY - timedelta(days=6), wins="Kept going")
        self.assertEqual(self.ctx.weekly.get(TODAY - timedelta(days=6)).wins, "Kept going")


class MilestoneRoutineTests(TempHomeTestCase):
    def test_goal_and_project_milestones(self):
        gid = self.ctx.goals.create("Learn guitar")
        pid = self.ctx.projects.create("Album")
        m1 = self.ctx.milestones.add("goal", gid, "Ten chords", TODAY + timedelta(days=30))
        self.ctx.milestones.add("project", pid, "Demo recorded")
        self.ctx.milestones.set_done("goal", m1, True)
        self.assertEqual(self.ctx.milestones.counts("goal", gid), (1, 1))
        self.assertEqual([m.title for m in self.ctx.milestones.list("project", pid)], ["Demo recorded"])

    def test_routines(self):
        iid = self.ctx.routines.add("morning", "Pack bag")
        self.ctx.routines.set_done(iid, TODAY, True)
        self.assertEqual(self.ctx.routines.done_on(TODAY), {iid})
        with self.assertRaises(ValidationError):
            self.ctx.routines.set_done(iid, TODAY + timedelta(days=1), True)


class ExportCoverageTests(TempHomeTestCase):
    def test_every_table_is_exported_and_round_trips(self):
        self.assertEqual(unexported_tables(self.ctx.db.conn), [])
        pid = self.ctx.projects.create("Thesis", repo_url="https://example.org/repo")
        tid = self.ctx.tasks.create("Chapter 1", project_id=pid, tags="writing", recurrence="weekly", due_date=TODAY)
        self.ctx.inbox.add("idea", "Interview a librarian")
        self.ctx.milestones.add("project", pid, "Outline")
        nid = self.ctx.notes.create("Sources", "")
        self.ctx.links.link("task", tid, "note", nid)
        out = self.home / "export.json"
        export_json(self.paths.db_path, out)
        self.ctx.tasks.create("Will be replaced")
        import_json(self.ctx.db, out, self.paths.backups_dir)
        self.assertEqual([t.title for t in self.ctx.tasks.list("all")], ["Chapter 1"])
        self.assertEqual(self.ctx.tasks.get(tid).project_name, "Thesis")
        self.assertEqual(len(self.ctx.links.links_for("task", tid)), 1)
        self.assertEqual([h.kind for h in self.ctx.search.search("chapter")], ["task"])

    def test_project_links_must_be_web_addresses(self):
        with self.assertRaises(ValidationError):
            self.ctx.projects.create("Bad", repo_url="file:///C:/Windows")


if __name__ == "__main__":
    unittest.main()
