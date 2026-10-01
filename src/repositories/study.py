from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from src.models import StudySession, from_row
from src.repositories.base import Repository, clean_text, optional_id
from src.services.dates import ValidationError, iso, now, stamp

_SELECT = ("SELECT ss.*, s.name AS subject_name, t.title AS task_title, p.name AS project_name "
           "FROM study_sessions ss LEFT JOIN subjects s ON s.id = ss.subject_id "
           "LEFT JOIN tasks t ON t.id = ss.task_id LEFT JOIN projects p ON p.id = ss.project_id")
KINDS = {"study": "Study", "practice": "Practice", "work": "Work", "reading": "Reading", "other": "Other"}

MAX_SESSION_SECONDS = 16 * 3600


def new_session_uid() -> str:
    return uuid.uuid4().hex


class StudyRepository(Repository):
    def record(
        self,
        *,
        session_uid: str,
        subject_id: int | None,
        started_at: datetime,
        actual_seconds: int,
        planned_minutes: int | None = None,
        completed: bool = True,
        source: str = "timer",
        note: str = "",
        task_id: int | None = None,
        project_id: int | None = None,
        kind: str = "study",
        node_id: int | None = None,
    ) -> bool:
        """Save a session. Returns False if this session was already saved.

        The unique ``session_uid`` makes saving idempotent, so a timer that
        completes and is then closed can never produce duplicate records.
        """
        actual_seconds = int(actual_seconds)
        if actual_seconds <= 0:
            raise ValidationError("A study session must last at least one second.")
        if actual_seconds > MAX_SESSION_SECONDS:
            raise ValidationError("A single study session can't be longer than 16 hours.")
        if source not in ("timer", "manual", "recovered"):
            raise ValidationError("Unknown session source.")
        if kind not in KINDS:
            raise ValidationError("Unknown session type.")
        ended_at = started_at + timedelta(seconds=actual_seconds)
        with self.db.transaction():
            cur = self.db.execute(
                """
                INSERT OR IGNORE INTO study_sessions
                    (session_uid, subject_id, date, started_at, ended_at, planned_minutes,
                     actual_seconds, completed, source, note, task_id, project_id, kind, node_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_uid,
                    optional_id(subject_id),
                    iso(started_at.date()),
                    stamp(started_at),
                    stamp(ended_at),
                    planned_minutes,
                    actual_seconds,
                    int(completed),
                    source,
                    clean_text(note, field="Note", max_len=500),
                    optional_id(task_id),
                    optional_id(project_id),
                    kind,
                    optional_id(node_id),
                ),
            )
            saved = cur.rowcount == 1
            if saved and task_id:
                self.db.execute("UPDATE tasks SET actual_minutes = COALESCE(actual_minutes, 0) + ? WHERE id = ?",
                                (actual_seconds // 60, task_id))
            return saved

    def record_manual(self, subject_id: int | None, day: date, start_hhmm: str, minutes: int, note: str = "") -> bool:
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            raise ValidationError("Duration must be a whole number of minutes.") from None
        if minutes <= 0:
            raise ValidationError("Duration must be at least one minute.")
        if day > now().date():
            raise ValidationError("You can't record a study session in the future.")
        hour, minute = (int(x) for x in start_hhmm.split(":")[:2])
        started = datetime(day.year, day.month, day.day, hour, minute)
        return self.record(
            session_uid=new_session_uid(),
            subject_id=subject_id,
            started_at=started,
            actual_seconds=minutes * 60,
            planned_minutes=None,
            completed=True,
            source="manual",
            note=note,
        )

    def delete(self, session_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM study_sessions WHERE id = ?", (session_id,))

    def exists(self, session_uid: str) -> bool:
        return bool(self.db.scalar("SELECT 1 FROM study_sessions WHERE session_uid = ?", (session_uid,)))

    def history(self, limit: int = 100, subject_id: int | None = None) -> list[StudySession]:
        sql = _SELECT
        params: list = []
        if subject_id:
            sql += " WHERE ss.subject_id = ?"
            params.append(subject_id)
        sql += " ORDER BY ss.started_at DESC LIMIT ?"
        params.append(limit)
        return [from_row(StudySession, r) for r in self.db.query(sql, params)]

    def seconds_on(self, day: date) -> int:
        return int(self.db.scalar("SELECT SUM(actual_seconds) FROM study_sessions WHERE date = ?", (iso(day),), 0))

    def seconds_between(self, start: date, end: date) -> int:
        return int(
            self.db.scalar(
                "SELECT SUM(actual_seconds) FROM study_sessions WHERE date BETWEEN ? AND ?", (iso(start), iso(end)), 0
            )
        )

    def daily_seconds(self, start: date, end: date) -> dict[date, int]:
        rows = self.db.query(
            "SELECT date, SUM(actual_seconds) FROM study_sessions WHERE date BETWEEN ? AND ? GROUP BY date",
            (iso(start), iso(end)),
        )
        return {date.fromisoformat(r[0]): int(r[1]) for r in rows}

    def by_subject(self, start: date, end: date) -> list[tuple[str, int]]:
        rows = self.db.query(
            """
            SELECT COALESCE(s.name, 'No subject') AS name, SUM(ss.actual_seconds) AS secs
            FROM study_sessions ss LEFT JOIN subjects s ON s.id = ss.subject_id
            WHERE ss.date BETWEEN ? AND ? GROUP BY name ORDER BY secs DESC
            """,
            (iso(start), iso(end)),
        )
        return [(r[0], int(r[1])) for r in rows]
