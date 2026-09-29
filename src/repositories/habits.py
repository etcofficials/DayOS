from __future__ import annotations

from datetime import date

from src.models import Habit, from_row
from src.repositories.base import Repository, clean_text
from src.services import streaks
from src.services.dates import ValidationError, iso, now_stamp, parse_date, today

DAILY = 127


class HabitRepository(Repository):
    def _check_weekdays(self, weekdays: int) -> int:
        weekdays = int(weekdays)
        if not 1 <= weekdays <= DAILY:
            raise ValidationError("Choose at least one day of the week for this habit.")
        return weekdays

    def create(self, name: str, description: str = "", weekdays: int = DAILY, start: date | None = None) -> int:
        name = clean_text(name, field="Habit name", required=True, max_len=80)
        description = clean_text(description, field="Description", max_len=500)
        weekdays = self._check_weekdays(weekdays)
        position = int(self.db.scalar("SELECT COALESCE(MAX(position), -1) + 1 FROM habits", default=0))
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO habits (name, description, weekdays, start_date, position, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, description, weekdays, iso(start or today()), position, now_stamp()),
            )

    def update(self, habit_id: int, name: str, description: str, weekdays: int) -> None:
        name = clean_text(name, field="Habit name", required=True, max_len=80)
        description = clean_text(description, field="Description", max_len=500)
        weekdays = self._check_weekdays(weekdays)
        with self.db.transaction():
            self.db.execute(
                "UPDATE habits SET name = ?, description = ?, weekdays = ? WHERE id = ?",
                (name, description, weekdays, habit_id),
            )

    def set_archived(self, habit_id: int, archived: bool) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE habits SET archived = ? WHERE id = ?", (int(archived), habit_id))

    def delete(self, habit_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM habits WHERE id = ?", (habit_id,))

    def get(self, habit_id: int) -> Habit | None:
        row = self.db.query_one("SELECT * FROM habits WHERE id = ?", (habit_id,))
        return from_row(Habit, row) if row else None

    def list(self, include_archived: bool = False) -> list[Habit]:
        sql = "SELECT * FROM habits"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY archived, position, id"
        return [from_row(Habit, r) for r in self.db.query(sql)]

    def scheduled_on(self, day: date) -> list[Habit]:
        return [h for h in self.list() if h.is_scheduled(day) and h.start <= day]

    # -- logs ---------------------------------------------------------------
    def set_done(self, habit_id: int, day: date, done: bool, ref: date | None = None) -> None:
        if day > (ref or today()):
            raise ValidationError("Habits can't be marked for future dates.")
        with self.db.transaction():
            if done:
                self.db.execute(
                    "INSERT OR IGNORE INTO habit_logs (habit_id, date) VALUES (?, ?)", (habit_id, iso(day))
                )
            else:
                self.db.execute("DELETE FROM habit_logs WHERE habit_id = ? AND date = ?", (habit_id, iso(day)))

    def is_done(self, habit_id: int, day: date) -> bool:
        return bool(
            self.db.scalar("SELECT 1 FROM habit_logs WHERE habit_id = ? AND date = ?", (habit_id, iso(day)))
        )

    def done_dates(self, habit_id: int, since: date | None = None) -> set[date]:
        sql = "SELECT date FROM habit_logs WHERE habit_id = ?"
        params: list = [habit_id]
        if since:
            sql += " AND date >= ?"
            params.append(iso(since))
        return {date.fromisoformat(r[0]) for r in self.db.query(sql, params)}

    def done_on(self, day: date) -> set[int]:
        return {int(r[0]) for r in self.db.query("SELECT habit_id FROM habit_logs WHERE date = ?", (iso(day),))}

    def streak_info(self, habit: Habit, ref: date | None = None) -> streaks.StreakInfo:
        ref = ref or today()
        return streaks.streaks(habit.weekdays, habit.start, self.done_dates(habit.id), ref)

    def rate(self, habit: Habit, period_start: date, period_end: date, ref: date | None = None) -> tuple[int, int]:
        ref = ref or today()
        done = self.done_dates(habit.id)
        return streaks.completion_rate(habit.weekdays, habit.start, done, period_start, period_end, ref)
