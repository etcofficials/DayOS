from __future__ import annotations

import sqlite3

from src.models import Subject, from_row
from src.repositories.base import Repository, clean_text
from src.services.dates import ValidationError, now_stamp

SUBJECT_COLORS = ["#8FAE88", "#7F9CB5", "#C98E73", "#B9A56E", "#9C8DB3", "#6FA3A0", "#B97F8F", "#8C9A6B"]


class SubjectRepository(Repository):
    def list(self, include_archived: bool = False) -> list[Subject]:
        sql = "SELECT * FROM subjects"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY name COLLATE NOCASE"
        return [from_row(Subject, r) for r in self.db.query(sql)]

    def get(self, subject_id: int) -> Subject | None:
        row = self.db.query_one("SELECT * FROM subjects WHERE id = ?", (subject_id,))
        return from_row(Subject, row) if row else None

    def create(self, name: str, color: str = "") -> int:
        name = clean_text(name, field="Subject name", required=True, max_len=60)
        if not color:
            count = self.db.scalar("SELECT COUNT(*) FROM subjects", default=0)
            color = SUBJECT_COLORS[count % len(SUBJECT_COLORS)]
        try:
            with self.db.transaction():
                return self.db.insert(
                    "INSERT INTO subjects (name, color, created_at) VALUES (?, ?, ?)",
                    (name, color, now_stamp()),
                )
        except sqlite3.IntegrityError:
            raise ValidationError(f"A subject called '{name}' already exists.") from None

    def get_or_create(self, name: str) -> int:
        name = clean_text(name, field="Subject name", required=True, max_len=60)
        row = self.db.query_one("SELECT id, archived FROM subjects WHERE name = ?", (name,))
        if row:
            if row["archived"]:
                self.set_archived(row["id"], False)
            return int(row["id"])
        return self.create(name)

    def rename(self, subject_id: int, name: str) -> None:
        name = clean_text(name, field="Subject name", required=True, max_len=60)
        try:
            with self.db.transaction():
                self.db.execute("UPDATE subjects SET name = ? WHERE id = ?", (name, subject_id))
        except sqlite3.IntegrityError:
            raise ValidationError(f"A subject called '{name}' already exists.") from None

    def set_color(self, subject_id: int, color: str) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE subjects SET color = ? WHERE id = ?", (color, subject_id))

    def set_archived(self, subject_id: int, archived: bool) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE subjects SET archived = ? WHERE id = ?", (int(archived), subject_id))

    def usage(self, subject_id: int) -> dict[str, int]:
        """How many records reference a subject (shown before deleting)."""
        tables = ["tasks", "events", "timetable", "study_sessions", "exams", "mistakes", "mock_tests"]
        return {
            t: int(self.db.scalar(f"SELECT COUNT(*) FROM {t} WHERE subject_id = ?", (subject_id,), 0))
            for t in tables
        }

    def delete(self, subject_id: int) -> None:
        """Delete a subject. Linked records are kept; their subject is cleared."""
        with self.db.transaction():
            self.db.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
