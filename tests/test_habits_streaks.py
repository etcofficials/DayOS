import unittest
from datetime import date, timedelta

from src.services import streaks
from src.services.dates import ValidationError
from tests.helpers import FIXED_NOW, TempHomeTestCase

TODAY = FIXED_NOW.date()  # Sunday 2026-09-27
DAILY = 127
MWF = 0b0010101  # Mon, Wed, Fri


def days_ago(*ns: int) -> set[date]:
    return {TODAY - timedelta(days=n) for n in ns}


class StreakRuleTests(unittest.TestCase):
    def test_daily_current_streak_counts_back_from_today(self):
        start = TODAY - timedelta(days=30)
        self.assertEqual(streaks.current_streak(DAILY, start, days_ago(0, 1, 2), TODAY), 3)

    def test_today_pending_does_not_break_streak(self):
        start = TODAY - timedelta(days=30)
        self.assertEqual(streaks.current_streak(DAILY, start, days_ago(1, 2, 3), TODAY), 3)

    def test_missed_yesterday_breaks_streak(self):
        start = TODAY - timedelta(days=30)
        self.assertEqual(streaks.current_streak(DAILY, start, days_ago(0, 2, 3), TODAY), 1)

    def test_unscheduled_days_are_skipped(self):
        # Sunday today; Fri (2 days ago), Wed (4), Mon (6) scheduled.
        start = TODAY - timedelta(days=30)
        self.assertEqual(streaks.current_streak(MWF, start, days_ago(2, 4, 6), TODAY), 3)
        # an unscheduled completion (Saturday) neither extends nor breaks the streak
        self.assertEqual(streaks.current_streak(MWF, start, days_ago(1, 2, 4, 6), TODAY), 3)
        # missing Wednesday breaks it
        self.assertEqual(streaks.current_streak(MWF, start, days_ago(2, 6), TODAY), 1)

    def test_longest_streak(self):
        start = TODAY - timedelta(days=20)
        done = days_ago(20, 19, 18, 17, 15, 14, 1, 0)
        self.assertEqual(streaks.longest_streak(DAILY, start, done, TODAY), 4)
        self.assertEqual(streaks.streaks(DAILY, start, done, TODAY), streaks.StreakInfo(current=2, longest=4))

    def test_never_counts_future_or_pre_start(self):
        start = TODAY
        self.assertEqual(streaks.current_streak(DAILY, start, set(), TODAY), 0)
        self.assertEqual(streaks.completion_rate(DAILY, start, set(), TODAY - timedelta(days=10), TODAY + timedelta(days=10), TODAY), (0, 0))

    def test_completion_rate_excludes_pending_today(self):
        start = TODAY - timedelta(days=6)
        week = (TODAY - timedelta(days=6), TODAY)
        self.assertEqual(streaks.completion_rate(DAILY, start, days_ago(1, 2, 3), *week, TODAY), (3, 6))
        self.assertEqual(streaks.completion_rate(DAILY, start, days_ago(0, 1, 2, 3), *week, TODAY), (4, 7))
        self.assertEqual(streaks.completion_rate(MWF, start, days_ago(2), *week, TODAY), (1, 3))

    def test_backfilled_log_before_start_extends_tracking(self):
        start = TODAY
        done = days_ago(0, 1, 2)
        self.assertEqual(streaks.current_streak(DAILY, start, done, TODAY), 3)


class HabitRepositoryTests(TempHomeTestCase):
    def test_crud_archive_and_logs(self):
        hid = self.ctx.habits.create("Read", "20 min", DAILY, start=TODAY - timedelta(days=10))
        self.ctx.habits.update(hid, "Read books", "", MWF)
        habit = self.ctx.habits.get(hid)
        self.assertEqual((habit.name, habit.weekdays), ("Read books", MWF))
        with self.assertRaises(ValidationError):
            self.ctx.habits.update(hid, "Read", "", 0)
        self.ctx.habits.set_archived(hid, True)
        self.assertEqual(self.ctx.habits.list(), [])
        self.assertEqual(len(self.ctx.habits.list(include_archived=True)), 1)

    def test_duplicate_completion_is_ignored(self):
        hid = self.ctx.habits.create("Walk")
        for _ in range(3):
            self.ctx.habits.set_done(hid, TODAY, True)
        self.assertEqual(self.ctx.db.scalar("SELECT COUNT(*) FROM habit_logs"), 1)
        self.ctx.habits.set_done(hid, TODAY, False)
        self.assertFalse(self.ctx.habits.is_done(hid, TODAY))

    def test_future_dates_rejected_and_history_corrections_allowed(self):
        hid = self.ctx.habits.create("Stretch", start=TODAY - timedelta(days=5))
        with self.assertRaises(ValidationError):
            self.ctx.habits.set_done(hid, TODAY + timedelta(days=1), True)
        self.ctx.habits.set_done(hid, TODAY - timedelta(days=3), True)
        self.assertTrue(self.ctx.habits.is_done(hid, TODAY - timedelta(days=3)))

    def test_streak_info_from_records(self):
        hid = self.ctx.habits.create("Water", start=TODAY - timedelta(days=10))
        for n in (0, 1, 2, 5, 6):
            self.ctx.habits.set_done(hid, TODAY - timedelta(days=n), True)
        info = self.ctx.habits.streak_info(self.ctx.habits.get(hid))
        self.assertEqual((info.current, info.longest), (3, 3))

    def test_scheduled_on_and_delete_cascades(self):
        weekday_habit = self.ctx.habits.create("Class prep", weekdays=0b0011111)  # Mon-Fri
        self.ctx.habits.create("Daily")
        self.assertEqual([h.name for h in self.ctx.habits.scheduled_on(TODAY)], ["Daily"])  # Sunday
        self.ctx.habits.set_done(weekday_habit, TODAY, True)
        self.ctx.habits.delete(weekday_habit)
        self.assertEqual(self.ctx.db.scalar("SELECT COUNT(*) FROM habit_logs"), 0)


if __name__ == "__main__":
    unittest.main()
