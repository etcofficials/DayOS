"""Insight calculations computed from stored records only.

Date boundaries: a range [start, end] is inclusive and uses local calendar
dates. Tasks count on the local date of ``completed_at``; study time counts on
the local date the session started.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.database import Database
from src.services.dates import MONTH_NAMES, WEEKDAY_SHORT, date_range, iso, today, week_start


@dataclass(frozen=True)
class Bucket:
    label: str
    start: date
    end: date
    value: float


def bucket_kind(start: date, end: date) -> str:
    return "day" if (end - start).days < 35 else "week"


def aggregate(daily: dict[date, float], start: date, end: date, first_weekday: int = 0) -> list[Bucket]:
    """Group per-day values into day buckets (≤ 5 weeks) or week buckets."""
    if end < start:
        return []
    if bucket_kind(start, end) == "day":
        short = (end - start).days < 8
        return [
            Bucket(WEEKDAY_SHORT[d.weekday()] if short else f"{d.day}/{d.month}", d, d, float(daily.get(d, 0)))
            for d in date_range(start, end)
        ]
    buckets: list[Bucket] = []
    cursor = week_start(start, first_weekday)
    while cursor <= end:
        b_start = max(cursor, start)
        b_end = min(cursor + timedelta(days=6), end)
        total = sum(daily.get(d, 0) for d in date_range(b_start, b_end))
        label = f"{b_start.day} {MONTH_NAMES[b_start.month - 1][:3]}"
        buckets.append(Bucket(label, b_start, b_end, float(total)))
        cursor += timedelta(days=7)
    return buckets


def tasks_completed_daily(db: Database, start: date, end: date) -> dict[date, float]:
    rows = db.query(
        """SELECT substr(completed_at, 1, 10) AS d, COUNT(*) FROM tasks
           WHERE completed_at IS NOT NULL AND substr(completed_at, 1, 10) BETWEEN ? AND ?
           GROUP BY d""",
        (iso(start), iso(end)),
    )
    return {date.fromisoformat(r[0]): float(r[1]) for r in rows}


def tasks_summary(db: Database, start: date, end: date) -> dict[str, int]:
    row = db.query_one(
        """SELECT
             SUM(substr(created_at, 1, 10) BETWEEN ? AND ?) AS created,
             SUM(completed_at IS NOT NULL AND substr(completed_at, 1, 10) BETWEEN ? AND ?) AS completed,
             SUM(completed_at IS NULL AND due_date IS NOT NULL AND due_date < ?) AS overdue_now
           FROM tasks""",
        (iso(start), iso(end), iso(start), iso(end), iso(today())),
    )
    return {k: int(row[k] or 0) for k in row.keys()} if row else {"created": 0, "completed": 0, "overdue_now": 0}


def study_daily_minutes(db: Database, start: date, end: date) -> dict[date, float]:
    rows = db.query(
        "SELECT date, SUM(actual_seconds) FROM study_sessions WHERE date BETWEEN ? AND ? GROUP BY date",
        (iso(start), iso(end)),
    )
    return {date.fromisoformat(r[0]): r[1] / 60.0 for r in rows}


def study_summary(db: Database, start: date, end: date) -> dict[str, float]:
    row = db.query_one(
        "SELECT COUNT(*) AS sessions, COALESCE(SUM(actual_seconds), 0) AS seconds, "
        "COUNT(DISTINCT date) AS days FROM study_sessions WHERE date BETWEEN ? AND ?",
        (iso(start), iso(end)),
    )
    sessions, seconds, days = int(row["sessions"]), int(row["seconds"]), int(row["days"])
    return {"sessions": sessions, "seconds": seconds, "days": days}


def recent_activity(db: Database, limit: int = 12) -> list[tuple[str, str, str]]:
    """Latest things that happened: (timestamp, kind, description)."""
    rows = db.query(
        """
        SELECT completed_at AS ts, 'task' AS kind, 'Completed task: ' || title AS text
          FROM tasks WHERE completed_at IS NOT NULL
        UNION ALL
        SELECT ended_at, 'study', 'Studied ' || (actual_seconds / 60) || ' min' ||
               COALESCE(' · ' || (SELECT name FROM subjects s WHERE s.id = subject_id), '')
          FROM study_sessions
        UNION ALL
        SELECT created_at, 'goal', 'Progress on goal: ' || (SELECT title FROM goals g WHERE g.id = goal_id)
          FROM goal_progress
        UNION ALL
        SELECT created_at, 'test', 'Test result: ' || title FROM mock_tests
        UNION ALL
        SELECT created_at, 'revision', 'Revised: ' || (SELECT name FROM chapters c WHERE c.id = chapter_id)
          FROM revision_logs
        UNION ALL
        SELECT updated_at, 'note', 'Edited note: ' || CASE WHEN title = '' THEN 'Untitled' ELSE title END FROM notes
        ORDER BY ts DESC LIMIT ?
        """,
        (limit,),
    )
    return [(r[0], r[1], r[2]) for r in rows]
