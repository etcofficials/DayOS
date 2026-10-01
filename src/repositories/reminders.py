"""User reminders, plus snooze/dismiss state for reminders computed from other records."""

from __future__ import annotations

from datetime import datetime

from src.models import Reminder, from_row
from src.repositories.base import Repository, clean_text
from src.services.dates import ValidationError, now, now_stamp, stamp


class ReminderRepository(Repository):
    def add(self, title: str, due_at: datetime, kind: str = "custom", ref_id: int | None = None,
            note: str = "") -> int:
        title = clean_text(title, field="Reminder", required=True, max_len=200)
        if kind not in ("custom", "task"):
            raise ValidationError("Unknown reminder type.")
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO reminders (title, due_at, kind, ref_id, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (title, stamp(due_at), kind, ref_id, clean_text(note, field="Note", max_len=1000), now_stamp()))

    def get(self, reminder_id: int) -> Reminder | None:
        row = self.db.query_one("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        return from_row(Reminder, row) if row else None

    def for_task(self, task_id: int) -> Reminder | None:
        row = self.db.query_one("SELECT * FROM reminders WHERE kind = 'task' AND ref_id = ? AND dismissed_at IS NULL "
                                "ORDER BY due_at LIMIT 1", (task_id,))
        return from_row(Reminder, row) if row else None

    def set_task_reminder(self, task_id: int, title: str, due_at: datetime | None) -> None:
        """Replace the (single) pending reminder of a task; ``None`` removes it."""
        with self.db.transaction():
            self.db.execute("DELETE FROM reminders WHERE kind = 'task' AND ref_id = ? AND dismissed_at IS NULL",
                            (task_id,))
            if due_at is not None:
                self.add(title, due_at, "task", task_id)

    def pending(self, until: datetime | None = None) -> list[Reminder]:
        """Reminders not dismissed whose (snoozed) time is due by ``until`` (default: now)."""
        limit = stamp(until or now())
        rows = self.db.query(
            "SELECT * FROM reminders WHERE dismissed_at IS NULL AND COALESCE(snoozed_until, due_at) <= ? "
            "ORDER BY due_at", (limit,))
        return [from_row(Reminder, r) for r in rows]

    def upcoming(self, limit: int = 50) -> list[Reminder]:
        rows = self.db.query("SELECT * FROM reminders WHERE dismissed_at IS NULL ORDER BY COALESCE(snoozed_until, due_at) "
                             "LIMIT ?", (limit,))
        return [from_row(Reminder, r) for r in rows]

    def next_due(self) -> datetime | None:
        value = self.db.scalar("SELECT MIN(COALESCE(snoozed_until, due_at)) FROM reminders WHERE dismissed_at IS NULL")
        return datetime.fromisoformat(value) if value else None

    def snooze(self, reminder_id: int, until: datetime) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE reminders SET snoozed_until = ?, notified_at = NULL WHERE id = ?",
                            (stamp(until), reminder_id))

    def dismiss(self, reminder_id: int) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE reminders SET dismissed_at = ? WHERE id = ?", (now_stamp(), reminder_id))

    def mark_notified(self, reminder_id: int) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE reminders SET notified_at = ? WHERE id = ?", (now_stamp(), reminder_id))

    def delete(self, reminder_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

    # -- state for computed notifications (events, habits, subscriptions …) ----------------
    def state(self, key: str) -> dict:
        row = self.db.query_one("SELECT * FROM notification_state WHERE key = ?", (key,))
        return dict(row) if row else {"key": key, "snoozed_until": None, "dismissed_at": None, "notified_at": None}

    def set_state(self, key: str, **fields: str | None) -> None:
        current = self.state(key)
        current.update({k: v for k, v in fields.items() if k in ("snoozed_until", "dismissed_at", "notified_at")})
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO notification_state (key, snoozed_until, dismissed_at, notified_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET snoozed_until = excluded.snoozed_until, "
                "dismissed_at = excluded.dismissed_at, notified_at = excluded.notified_at",
                (key, current["snoozed_until"], current["dismissed_at"], current["notified_at"]))

    def prune_state(self, before: datetime) -> None:
        """Forget snooze/dismiss state for computed reminders older than ``before`` (keeps the table small)."""
        cutoff = before.strftime("%Y-%m-%d")
        with self.db.transaction():
            self.db.execute("DELETE FROM notification_state WHERE substr(key, -10) < ?", (cutoff,))
