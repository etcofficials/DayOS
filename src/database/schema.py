"""Schema definition and versioned migrations.

The schema version is stored in ``PRAGMA user_version``. Each migration runs in
its own transaction; an existing database is backed up before it is upgraded.

Conventions
-----------
* Dates are local calendar dates stored as ``YYYY-MM-DD`` text.
* Times are local wall-clock times stored as ``HH:MM`` text.
* Timestamps are local date-times stored as ``YYYY-MM-DD HH:MM:SS`` text.
  DayOS deliberately never mixes UTC into stored values.
"""

from __future__ import annotations

import logging
from typing import Callable

from src.database.connection import Database, DatabaseError

log = logging.getLogger(__name__)

SCHEMA_V1 = """
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE subjects (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0),
    color      TEXT NOT NULL DEFAULT '',
    archived   INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE goals (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description   TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT '',
    target_date   TEXT,
    target_value  REAL CHECK (target_value IS NULL OR target_value > 0),
    current_value REAL NOT NULL DEFAULT 0,
    unit          TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'paused')),
    created_at    TEXT NOT NULL,
    completed_at  TEXT
);

CREATE TABLE goal_progress (
    id         INTEGER PRIMARY KEY,
    goal_id    INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    value      REAL NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_goal_progress_goal ON goal_progress(goal_id, date);

CREATE TABLE tasks (
    id               INTEGER PRIMARY KEY,
    title            TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description      TEXT NOT NULL DEFAULT '',
    due_date         TEXT,
    due_time         TEXT,
    priority         INTEGER NOT NULL DEFAULT 1 CHECK (priority IN (0, 1, 2)),
    category         TEXT NOT NULL DEFAULT '',
    subject_id       INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    goal_id          INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    estimate_minutes INTEGER CHECK (estimate_minutes IS NULL OR estimate_minutes > 0),
    created_at       TEXT NOT NULL,
    completed_at     TEXT,
    CHECK (due_time IS NULL OR due_date IS NOT NULL)
);
CREATE INDEX idx_tasks_due ON tasks(due_date);
CREATE INDEX idx_tasks_completed ON tasks(completed_at);
CREATE INDEX idx_tasks_goal ON tasks(goal_id);

CREATE TABLE subtasks (
    id       INTEGER PRIMARY KEY,
    task_id  INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    title    TEXT NOT NULL CHECK (length(trim(title)) > 0),
    done     INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1)),
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_subtasks_task ON subtasks(task_id, position);

CREATE TABLE notes (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    pinned     INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_notes_updated ON notes(pinned, updated_at);

CREATE TABLE habits (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    weekdays    INTEGER NOT NULL DEFAULT 127 CHECK (weekdays BETWEEN 1 AND 127),
    start_date  TEXT NOT NULL,
    archived    INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE habit_logs (
    habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
    date     TEXT NOT NULL,
    PRIMARY KEY (habit_id, date)
);
CREATE INDEX idx_habit_logs_date ON habit_logs(date);

CREATE TABLE journal (
    date       TEXT PRIMARY KEY,
    intention  TEXT NOT NULL DEFAULT '',
    reflection TEXT NOT NULL DEFAULT '',
    went_well  TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE events (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL CHECK (length(trim(title)) > 0),
    kind        TEXT NOT NULL DEFAULT 'event' CHECK (kind IN ('event', 'deadline')),
    date        TEXT NOT NULL,
    start_time  TEXT,
    end_time    TEXT,
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    subject_id  INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    CHECK (end_time IS NULL OR (start_time IS NOT NULL AND end_time > start_time))
);
CREATE INDEX idx_events_date ON events(date);

CREATE TABLE timetable (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL CHECK (length(trim(title)) > 0),
    subject_id  INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    weekday     INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    location    TEXT NOT NULL DEFAULT '',
    valid_from  TEXT,
    valid_until TEXT,
    created_at  TEXT NOT NULL,
    CHECK (end_time > start_time),
    CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from)
);
CREATE INDEX idx_timetable_weekday ON timetable(weekday);

CREATE TABLE timetable_skips (
    entry_id INTEGER NOT NULL REFERENCES timetable(id) ON DELETE CASCADE,
    date     TEXT NOT NULL,
    PRIMARY KEY (entry_id, date)
);

CREATE TABLE study_sessions (
    id              INTEGER PRIMARY KEY,
    session_uid     TEXT NOT NULL UNIQUE,
    subject_id      INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    date            TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    ended_at        TEXT NOT NULL,
    planned_minutes INTEGER,
    actual_seconds  INTEGER NOT NULL CHECK (actual_seconds > 0),
    completed       INTEGER NOT NULL DEFAULT 1 CHECK (completed IN (0, 1)),
    source          TEXT NOT NULL DEFAULT 'timer' CHECK (source IN ('timer', 'manual', 'recovered')),
    note            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_study_date ON study_sessions(date);
CREATE INDEX idx_study_subject ON study_sessions(subject_id, date);

CREATE TABLE exams (
    id         INTEGER PRIMARY KEY,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    title      TEXT NOT NULL CHECK (length(trim(title)) > 0),
    exam_date  TEXT NOT NULL,
    exam_time  TEXT,
    syllabus   TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_exams_date ON exams(exam_date);

CREATE TABLE chapters (
    id            INTEGER PRIMARY KEY,
    exam_id       INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    name          TEXT NOT NULL CHECK (length(trim(name)) > 0),
    status        TEXT NOT NULL DEFAULT 'not_started'
                  CHECK (status IN ('not_started', 'learning', 'needs_revision', 'revised', 'mastered')),
    last_reviewed TEXT,
    next_review   TEXT,
    interval_days INTEGER NOT NULL DEFAULT 0,
    review_count  INTEGER NOT NULL DEFAULT 0,
    position      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_chapters_exam ON chapters(exam_id, position);
CREATE INDEX idx_chapters_next ON chapters(next_review);

CREATE TABLE revision_logs (
    id         INTEGER PRIMARY KEY,
    chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    outcome    TEXT NOT NULL CHECK (outcome IN ('hard', 'okay', 'easy')),
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_revision_logs_chapter ON revision_logs(chapter_id, date);

CREATE TABLE mistakes (
    id         INTEGER PRIMARY KEY,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
    question   TEXT NOT NULL CHECK (length(trim(question)) > 0),
    correction TEXT NOT NULL DEFAULT '',
    resolved   INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE mock_tests (
    id         INTEGER PRIMARY KEY,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    exam_id    INTEGER REFERENCES exams(id) ON DELETE SET NULL,
    title      TEXT NOT NULL CHECK (length(trim(title)) > 0),
    date       TEXT NOT NULL,
    marks      REAL NOT NULL CHECK (marks >= 0),
    max_marks  REAL NOT NULL CHECK (max_marks > 0),
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    CHECK (marks <= max_marks)
);
CREATE INDEX idx_mock_tests_date ON mock_tests(date);
"""

# Ordered list of (version, migration callable). Append new migrations; never edit old ones.
Migration = Callable[[Database], None]


def _migrate_v1(db: Database) -> None:
    # Statements run one by one: executescript() would COMMIT the open transaction.
    for statement in _split_sql(SCHEMA_V1):
        db.execute(statement)


MIGRATIONS: list[tuple[int, Migration]] = [
    (1, _migrate_v1),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def _split_sql(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]


def migrate(
    db: Database,
    migrations: list[tuple[int, Migration]] | None = None,
    before_upgrade: Callable[[int, int], None] | None = None,
) -> int:
    """Bring the database up to the latest schema version.

    ``before_upgrade(current, target)`` is called once, only when an existing
    database with user data is about to be upgraded (used to take a backup).
    Returns the resulting schema version.
    """
    migrations = migrations or MIGRATIONS
    latest = migrations[-1][0]
    current = db.user_version
    if current > latest:
        raise DatabaseError(
            f"This database was created by a newer version of DayOS (schema {current}; "
            f"this version understands up to {latest}). Update DayOS to open it."
        )
    if current == latest:
        return current
    if current > 0 and before_upgrade is not None:
        before_upgrade(current, latest)
    for version, func in migrations:
        if version <= current:
            continue
        log.info("Applying database migration %s", version)
        with db.transaction():
            func(db)
            db.execute(f"PRAGMA user_version = {int(version)}")
        current = version
    return current
