"""Optional morning and evening checklists (e.g. "pack bag", "phone on charge")."""

from __future__ import annotations

from datetime import date

from src.models import RoutineItem, from_row
from src.repositories.base import Repository, clean_text
from src.services.dates import ValidationError, iso, now_stamp, today

ROUTINES = {"morning": "Morning checklist", "evening": "Evening wind-down"}


class RoutineRepository(Repository):
    def items(self, routine: str) -> list[RoutineItem]:
        rows = self.db.query("SELECT * FROM routine_items WHERE routine = ? AND archived = 0 ORDER BY position, id",
                             (routine,))
        return [from_row(RoutineItem, r) for r in rows]

    def add(self, routine: str, title: str) -> int:
        if routine not in ROUTINES:
            raise ValidationError("Unknown routine.")
        title = clean_text(title, field="Checklist item", required=True, max_len=120)
        position = int(self.db.scalar("SELECT COALESCE(MAX(position), -1) + 1 FROM routine_items WHERE routine = ?",
                                      (routine,), 0))
        with self.db.transaction():
            return self.db.insert("INSERT INTO routine_items (routine, title, position, created_at) VALUES (?, ?, ?, ?)",
                                  (routine, title, position, now_stamp()))

    def rename(self, item_id: int, title: str) -> None:
        title = clean_text(title, field="Checklist item", required=True, max_len=120)
        with self.db.transaction():
            self.db.execute("UPDATE routine_items SET title = ? WHERE id = ?", (title, item_id))

    def remove(self, item_id: int) -> None:
        """Archive the item so past check-offs stay meaningful."""
        with self.db.transaction():
            self.db.execute("UPDATE routine_items SET archived = 1 WHERE id = ?", (item_id,))

    def set_done(self, item_id: int, day: date, done: bool) -> None:
        if day > today():
            raise ValidationError("Checklists can't be ticked for future days.")
        with self.db.transaction():
            if done:
                self.db.execute("INSERT OR IGNORE INTO routine_logs (item_id, date) VALUES (?, ?)", (item_id, iso(day)))
            else:
                self.db.execute("DELETE FROM routine_logs WHERE item_id = ? AND date = ?", (item_id, iso(day)))

    def done_on(self, day: date) -> set[int]:
        return {int(r[0]) for r in self.db.query("SELECT item_id FROM routine_logs WHERE date = ?", (iso(day),))}
