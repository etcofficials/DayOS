import unittest
from datetime import date, datetime, timedelta

from src.repositories.study import new_session_uid
from src.services import revision
from src.services.dates import ValidationError
from src.services.timer import FOCUS, FocusTimer
from tests.helpers import FIXED_NOW, TempHomeTestCase

TODAY = FIXED_NOW.date()  # Sunday


class ScheduleTests(TempHomeTestCase):
    def test_event_validation(self):
        with self.assertRaises(ValidationError):
            self.ctx.schedule.create_event(title="Late party", date=TODAY, start_time="22:00", end_time="01:00")
        with self.assertRaises(ValidationError):
            self.ctx.schedule.create_event(title="End only", date=TODAY, end_time="10:00")
        with self.assertRaises(ValidationError):
            self.ctx.schedule.create_event(title="", date=TODAY)
        with self.assertRaises(ValidationError):
            self.ctx.schedule.create_event(title="No date", date="")
        eid = self.ctx.schedule.create_event(title="All day", date=TODAY)
        self.assertIsNone(self.ctx.schedule.get_event(eid).start_time)

    def test_event_crud(self):
        eid = self.ctx.schedule.create_event(title="Dentist", date=TODAY, start_time="15:00", end_time="15:30")
        self.ctx.schedule.update_event(eid, title="Dentist (moved)", date=TODAY + timedelta(days=1), start_time="09:00")
        ev = self.ctx.schedule.get_event(eid)
        self.assertEqual((ev.title, ev.date, ev.start_time, ev.end_time), ("Dentist (moved)", "2026-09-28", "09:00", None))
        self.ctx.schedule.delete_event(eid)
        self.assertIsNone(self.ctx.schedule.get_event(eid))

    def test_recurring_timetable_skip_and_window(self):
        monday = TODAY + timedelta(days=1)
        eid = self.ctx.schedule.create_entry(title="Maths", weekday=0, start_time="09:00", end_time="10:00",
                                             valid_from=monday)
        agenda = self.ctx.schedule.agenda(TODAY, TODAY + timedelta(days=21), include_tasks=False)
        mondays = sorted(d for d, items in agenda.items() if any(i.kind == "class" for i in items))
        self.assertEqual(mondays, [monday, monday + timedelta(days=7), monday + timedelta(days=14)])
        self.ctx.schedule.skip_occurrence(eid, monday + timedelta(days=7))
        agenda = self.ctx.schedule.agenda(TODAY, TODAY + timedelta(days=21), include_tasks=False)
        self.assertNotIn(monday + timedelta(days=7), agenda)
        self.ctx.schedule.unskip_occurrence(eid, monday + timedelta(days=7))
        self.ctx.schedule.end_series(eid, monday + timedelta(days=7))
        agenda = self.ctx.schedule.agenda(TODAY, TODAY + timedelta(days=21), include_tasks=False)
        self.assertEqual(sorted(agenda), [monday, monday + timedelta(days=7)])
        with self.assertRaises(ValidationError):
            self.ctx.schedule.create_entry(title="Bad", weekday=1, start_time="10:00", end_time="09:00")

    def test_agenda_combines_kinds_and_sorts(self):
        self.ctx.schedule.create_event(title="Party", date=TODAY, start_time="18:00", end_time="20:00")
        self.ctx.schedule.create_event(title="Report", kind="deadline", date=TODAY)
        self.ctx.schedule.create_entry(title="Choir", weekday=6, start_time="08:00", end_time="09:00")
        self.ctx.exams.create_exam(title="Final", exam_date=TODAY, exam_time="12:00")
        self.ctx.tasks.create("Due task", due_date=TODAY)
        items = self.ctx.schedule.day_agenda(TODAY, include_tasks=True)
        self.assertEqual({i.kind for i in items}, {"event", "deadline", "class", "exam", "task"})
        timed = [i.start_time for i in items if i.start_time]
        self.assertEqual(timed, sorted(timed))

    def test_overlap_detection(self):
        self.ctx.schedule.create_entry(title="Physics", weekday=6, start_time="09:00", end_time="10:00")
        eid = self.ctx.schedule.create_event(title="Call", date=TODAY, start_time="11:00", end_time="12:00")
        self.assertEqual(len(self.ctx.schedule.event_conflicts(TODAY, "09:30", "11:15")), 2)
        self.assertEqual(self.ctx.schedule.event_conflicts(TODAY, "10:00", "11:00"), [])  # touching is fine
        self.assertEqual(self.ctx.schedule.event_conflicts(TODAY, "11:00", "12:00", exclude_id=eid), [])
        self.assertEqual(len(self.ctx.schedule.entry_conflicts(6, "09:45", "10:30")), 1)


class StudyTests(TempHomeTestCase):
    def test_record_is_idempotent(self):
        uid = new_session_uid()
        started = datetime(2026, 9, 27, 9, 0)
        self.assertTrue(self.ctx.study.record(session_uid=uid, subject_id=None, started_at=started, actual_seconds=1500))
        self.assertFalse(self.ctx.study.record(session_uid=uid, subject_id=None, started_at=started, actual_seconds=1500))
        self.assertEqual(self.ctx.db.scalar("SELECT COUNT(*) FROM study_sessions"), 1)
        self.assertTrue(self.ctx.study.exists(uid))

    def test_totals_and_boundaries(self):
        sid = self.ctx.subjects.create("Biology")
        self.ctx.study.record(session_uid=new_session_uid(), subject_id=sid, started_at=datetime(2026, 9, 27, 8), actual_seconds=1800)
        self.ctx.study.record(session_uid=new_session_uid(), subject_id=None, started_at=datetime(2026, 9, 26, 23, 50), actual_seconds=1200)
        self.assertEqual(self.ctx.study.seconds_on(TODAY), 1800)
        self.assertEqual(self.ctx.study.seconds_on(TODAY - timedelta(days=1)), 1200)  # counted on the start date
        self.assertEqual(self.ctx.study.seconds_between(TODAY - timedelta(days=6), TODAY), 3000)
        self.assertEqual(dict(self.ctx.study.by_subject(TODAY - timedelta(days=6), TODAY)), {"Biology": 1800, "No subject": 1200})

    def test_manual_validation(self):
        self.assertTrue(self.ctx.study.record_manual(None, TODAY, "07:30", 45, "notes"))
        with self.assertRaises(ValidationError):
            self.ctx.study.record_manual(None, TODAY + timedelta(days=1), "07:30", 45)
        with self.assertRaises(ValidationError):
            self.ctx.study.record_manual(None, TODAY, "07:30", 0)
        with self.assertRaises(ValidationError):
            self.ctx.study.record(session_uid="x", subject_id=None, started_at=FIXED_NOW, actual_seconds=0)
        self.assertEqual(self.ctx.study.history()[0].source, "manual")


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class TimerTests(unittest.TestCase):
    def test_elapsed_uses_clock_not_ticks(self):
        clock = FakeClock()
        timer = FocusTimer(clock=clock)
        timer.start(25 * 60, FOCUS, "uid")
        clock.t += 600  # ten minutes pass with no ticks at all (e.g. window minimized)
        self.assertAlmostEqual(timer.remaining(), 15 * 60)
        timer.pause()
        clock.t += 3600  # paused time does not count
        self.assertAlmostEqual(timer.elapsed(), 600)
        timer.resume()
        clock.t += 900
        self.assertTrue(timer.check_finished())
        self.assertFalse(timer.check_finished())  # completion fires once
        self.assertEqual(timer.state, "finished")
        self.assertEqual(timer.elapsed(), 25 * 60)  # never exceeds the planned length

    def test_pause_immediately_after_start_is_paused(self):
        clock = FakeClock()
        timer = FocusTimer(clock=clock)
        timer.start(600, FOCUS, "uid")
        timer.pause()  # zero elapsed time (coarse clocks) must still count as paused, not idle
        self.assertEqual(timer.state, "paused")
        self.assertTrue(timer.is_active)
        timer.reset()
        self.assertEqual(timer.state, "idle")

    def test_pause_at_excludes_sleep_time(self):
        clock = FakeClock()
        timer = FocusTimer(clock=clock)
        timer.start(1800, FOCUS, "uid")
        clock.t += 300
        last_tick = clock.t
        clock.t += 7200  # computer asleep for two hours
        timer.pause_at(last_tick)
        self.assertEqual(timer.state, "paused")
        self.assertAlmostEqual(timer.elapsed(), 300)

    def test_checkpoint_only_for_active_focus(self):
        clock = FakeClock()
        timer = FocusTimer(clock=clock)
        self.assertIsNone(timer.checkpoint())
        timer.start(600, FOCUS, "abc", subject_id=3)
        clock.t += 120
        cp = timer.checkpoint()
        self.assertEqual((cp["session_uid"], cp["subject_id"], cp["elapsed_s"]), ("abc", 3, 120.0))
        timer.reset()
        self.assertIsNone(timer.checkpoint())
        timer.start(300, "short_break")
        self.assertIsNone(timer.checkpoint())


class RevisionRuleTests(unittest.TestCase):
    def test_schedule_rules(self):
        d = date(2026, 9, 1)
        self.assertEqual(revision.schedule_next("hard", 10, d), revision.ReviewResult(1, date(2026, 9, 2), "needs_revision"))
        self.assertEqual(revision.schedule_next("okay", 0, d).interval_days, 2)
        self.assertEqual(revision.schedule_next("okay", 4, d).interval_days, 8)
        self.assertEqual(revision.schedule_next("okay", 20, d).interval_days, 30)
        easy = revision.schedule_next("easy", 7, d)
        self.assertEqual((easy.interval_days, easy.status), (21, "mastered"))
        self.assertEqual(revision.schedule_next("easy", 30, d).interval_days, 60)
        with self.assertRaises(ValueError):
            revision.schedule_next("great", 1, d)

    def test_review_pulled_before_exam(self):
        result = revision.schedule_next("okay", 10, date(2026, 9, 1), exam_date=date(2026, 9, 10))
        self.assertEqual(result.next_review, date(2026, 9, 9))


class ExamTests(TempHomeTestCase):
    def test_exam_chapters_revision_queue(self):
        sid = self.ctx.subjects.create("History")
        xid = self.ctx.exams.create_exam(title="History final", subject_id=sid, exam_date=TODAY + timedelta(days=10))
        self.assertEqual(self.ctx.exams.add_chapters(xid, ["Rome", "", "Greece", "Egypt"]), 3)
        rome, greece, egypt = self.ctx.exams.chapters(xid)
        self.ctx.exams.set_chapter_status(greece.id, "learning")
        # Rome was revised 3 days ago and rated hard -> overdue since 2 days
        self.ctx.exams.log_revision(rome.id, "hard", day=TODAY - timedelta(days=3))
        queue = self.ctx.exams.revision_queue(TODAY)
        self.assertEqual([c.name for c in queue], ["Rome", "Greece"])  # overdue first, then learning
        result = self.ctx.exams.log_revision(rome.id, "okay")
        self.assertEqual(result.next_review, TODAY + timedelta(days=2))
        rome = self.ctx.exams.get_chapter(rome.id)
        self.assertEqual((rome.status, rome.review_count, rome.last_reviewed), ("revised", 2, TODAY.isoformat()))
        self.assertEqual([c.name for c in self.ctx.exams.revision_queue(TODAY)], ["Greece"])
        self.assertEqual(len(self.ctx.exams.revision_logs(rome.id)), 2)
        with self.assertRaises(ValidationError):
            self.ctx.exams.log_revision(egypt.id, "easy", day=TODAY + timedelta(days=1))
        exam = self.ctx.exams.get_exam(xid)
        self.assertEqual((exam.chapter_total, exam.chapter_ready), (3, 1))

    def test_delete_exam_keeps_tests_and_mistakes(self):
        xid = self.ctx.exams.create_exam(title="Quiz", exam_date=TODAY)
        cid = self.ctx.exams.add_chapter(xid, "Topic")
        mid = self.ctx.exams.add_mistake("Sign error", "Check signs", None, cid)
        tid = self.ctx.exams.add_test(title="Practice", exam_id=xid, date=TODAY, marks=8, max_marks=10)
        self.ctx.exams.delete_exam(xid)
        self.assertIsNone(self.ctx.exams.get_exam(xid))
        self.assertEqual(self.ctx.db.scalar("SELECT COUNT(*) FROM chapters"), 0)
        mistake = self.ctx.exams.mistakes()[0]
        self.assertEqual((mistake.id, mistake.chapter_id), (mid, None))
        test = self.ctx.exams.tests()[0]
        self.assertEqual((test.id, test.exam_id, test.percent), (tid, None, 80.0))

    def test_mock_test_validation(self):
        base = dict(title="Mock", date=TODAY)
        for bad in ({"marks": 11, "max_marks": 10}, {"marks": -1, "max_marks": 10}, {"marks": 5, "max_marks": 0},
                    {"marks": "x", "max_marks": 10}):
            with self.assertRaises(ValidationError):
                self.ctx.exams.add_test(**base, **bad)
        with self.assertRaises(ValidationError):
            self.ctx.exams.add_test(title="Future", date=TODAY + timedelta(days=1), marks=1, max_marks=2)
        with self.assertRaises(ValidationError):
            self.ctx.exams.create_exam(title="No date", exam_date=None)

    def test_mistake_notebook(self):
        sid = self.ctx.subjects.create("Maths")
        mid = self.ctx.exams.add_mistake("Forgot +C", "Always add constant", sid)
        self.ctx.exams.set_mistake_resolved(mid, True)
        self.assertEqual(self.ctx.exams.mistakes(include_resolved=False), [])
        self.assertEqual(len(self.ctx.exams.mistakes(subject_id=sid, search="constant")), 1)
        with self.assertRaises(ValidationError):
            self.ctx.exams.add_mistake("   ")


if __name__ == "__main__":
    unittest.main()
