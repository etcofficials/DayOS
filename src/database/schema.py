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


V1_PAGES = ["today", "tasks", "calendar", "study", "exams", "notes", "habits", "goals", "insights"]
V1_DATA_TABLES = ("tasks", "notes", "habits", "goals", "events", "timetable", "study_sessions", "exams", "journal")


def _migrate_v2(db: Database) -> None:
    """DayOS 2 foundation: carry v1 preferences over to the new theme and navigation system.

    * ``theme`` "light"/"dark" become the equivalent v2 themes (Paper & Sage / Midnight Focus).
    * A database that already holds v1 records keeps exactly the v1 sidebar pages, so upgrading
      never hides anything the user was using, and skips the first-run welcome.
    No user records are modified.
    """
    db.execute("""UPDATE settings SET value = '"paper"' WHERE key = 'theme' AND value = '"light"'""")
    db.execute("""UPDATE settings SET value = '"midnight"' WHERE key = 'theme' AND value = '"dark"'""")
    has_data = any(db.scalar(f"SELECT EXISTS (SELECT 1 FROM {t})", default=0) for t in V1_DATA_TABLES)
    if has_data:
        import json

        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('nav.modules', ?)", (json.dumps(V1_PAGES),))
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('onboarded', 'true')")


# -- search index ----------------------------------------------------------------------
# One FTS5 table indexes searchable records from every module. Each record gets a
# fixed rowid of ``id * 64 + kind code`` so triggers can update it in O(1).
SEARCH_KINDS = {
    "task": 1, "note": 2, "event": 3, "goal": 4, "exam": 5, "project": 6, "inbox": 7, "chapter": 8,
    "question": 9, "course": 10, "skill": 11, "flashcard": 12, "material": 13, "mistake": 14,
    "project_log": 15, "milestone": 16, "subscription": 17,
}


def search_triggers(table: str, kind: str, title_sql: str, body_sql: str, where_sql: str = "1") -> list[str]:
    """SQL for triggers that keep ``search_index`` in step with ``table``.

    ``title_sql`` / ``body_sql`` / ``where_sql`` are expressions over the row, written with a
    ``{r}.`` prefix that is replaced by ``new`` (or by the table name for the backfill).
    """
    code = SEARCH_KINDS[kind]
    t_new, b_new, w_new = (x.replace("{r}", "new") for x in (title_sql, body_sql, where_sql))
    insert = (f"INSERT INTO search_index (rowid, kind, ref_id, title, body) "
              f"SELECT new.id * 64 + {code}, '{kind}', new.id, {t_new}, {b_new} WHERE {w_new}")
    delete = f"DELETE FROM search_index WHERE rowid = old.id * 64 + {code}"
    return [
        f"CREATE TRIGGER {table}_ai_search AFTER INSERT ON {table} BEGIN {insert}; END",
        f"CREATE TRIGGER {table}_au_search AFTER UPDATE ON {table} BEGIN {delete}; {insert}; END",
        f"CREATE TRIGGER {table}_ad_search AFTER DELETE ON {table} BEGIN {delete}; END",
    ]


def search_backfill(table: str, kind: str, title_sql: str, body_sql: str, where_sql: str = "1") -> str:
    code = SEARCH_KINDS[kind]
    t, b, w = (x.replace("{r}", table) for x in (title_sql, body_sql, where_sql))
    return (f"INSERT INTO search_index (rowid, kind, ref_id, title, body) "
            f"SELECT {table}.id * 64 + {code}, '{kind}', {table}.id, {t}, {b} FROM {table} WHERE {w}")


SEARCH_SOURCES_V3 = [
    ("tasks", "task", "{r}.title", "{r}.description || ' ' || {r}.category || ' ' || {r}.tags"),
    ("notes", "note", "{r}.title", "{r}.content || ' ' || {r}.tags"),
    ("events", "event", "{r}.title", "{r}.description || ' ' || {r}.category || ' ' || {r}.location"),
    ("goals", "goal", "{r}.title", "{r}.description || ' ' || {r}.category"),
    ("exams", "exam", "{r}.title", "{r}.syllabus || ' ' || {r}.notes"),
    ("chapters", "chapter", "{r}.name", "''"),
    ("projects", "project", "{r}.name", "{r}.description || ' ' || {r}.repo_url"),
    ("inbox", "inbox", "{r}.text", "{r}.url", "{r}.processed_at IS NULL"),
    ("mistakes", "mistake", "{r}.question", "{r}.correction"),
]

SCHEMA_V3 = """
CREATE TABLE projects (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('idea', 'active', 'paused', 'done', 'archived')),
    goal_id     INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    repo_url    TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT '',
    start_date  TEXT,
    target_date TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE project_milestones (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title      TEXT NOT NULL CHECK (length(trim(title)) > 0),
    due_date   TEXT,
    done_at    TEXT,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_project_milestones ON project_milestones(project_id, position);

CREATE TABLE project_logs (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('note', 'changelog', 'release', 'time')),
    date       TEXT NOT NULL,
    minutes    INTEGER CHECK (minutes IS NULL OR minutes > 0),
    version    TEXT NOT NULL DEFAULT '',
    text       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_project_logs ON project_logs(project_id, date);

ALTER TABLE tasks ADD COLUMN tags TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN actual_minutes INTEGER CHECK (actual_minutes IS NULL OR actual_minutes >= 0);
ALTER TABLE tasks ADD COLUMN recurrence TEXT NOT NULL DEFAULT ''
    CHECK (recurrence IN ('', 'daily', 'weekdays', 'weekly', 'monthly', 'yearly'));
ALTER TABLE tasks ADD COLUMN recur_interval INTEGER NOT NULL DEFAULT 1 CHECK (recur_interval BETWEEN 1 AND 365);
ALTER TABLE tasks ADD COLUMN next_task_id INTEGER;
CREATE INDEX idx_tasks_project ON tasks(project_id);

CREATE TABLE task_dependencies (
    task_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, depends_on),
    CHECK (task_id != depends_on)
);

ALTER TABLE events ADD COLUMN recurrence TEXT NOT NULL DEFAULT ''
    CHECK (recurrence IN ('', 'daily', 'weekdays', 'weekly', 'monthly', 'yearly'));
ALTER TABLE events ADD COLUMN recur_until TEXT;
ALTER TABLE events ADD COLUMN remind_minutes INTEGER CHECK (remind_minutes IS NULL OR remind_minutes BETWEEN 0 AND 10080);
ALTER TABLE events ADD COLUMN location TEXT NOT NULL DEFAULT '';
ALTER TABLE events ADD COLUMN task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL;

CREATE TABLE event_skips (
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    date     TEXT NOT NULL,
    PRIMARY KEY (event_id, date)
);

ALTER TABLE habits ADD COLUMN remind_time TEXT;
ALTER TABLE habits ADD COLUMN weekly_target INTEGER CHECK (weekly_target IS NULL OR weekly_target BETWEEN 1 AND 7);

CREATE TABLE goal_milestones (
    id          INTEGER PRIMARY KEY,
    goal_id     INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    title       TEXT NOT NULL CHECK (length(trim(title)) > 0),
    target_date TEXT,
    done_at     TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_goal_milestones ON goal_milestones(goal_id, position);

ALTER TABLE journal ADD COLUMN improve TEXT NOT NULL DEFAULT '';

CREATE TABLE weekly_reviews (
    week_start TEXT PRIMARY KEY,
    wins       TEXT NOT NULL DEFAULT '',
    challenges TEXT NOT NULL DEFAULT '',
    priorities TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE inbox (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL DEFAULT 'idea'
                 CHECK (kind IN ('task', 'reminder', 'note', 'idea', 'link', 'snippet', 'project', 'study')),
    text         TEXT NOT NULL CHECK (length(trim(text)) > 0),
    url          TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    processed_at TEXT,
    result_kind  TEXT,
    result_id    INTEGER
);
CREATE INDEX idx_inbox_open ON inbox(processed_at, created_at);

CREATE TABLE reminders (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL CHECK (length(trim(title)) > 0),
    due_at        TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'custom' CHECK (kind IN ('custom', 'task')),
    ref_id        INTEGER,
    note          TEXT NOT NULL DEFAULT '',
    snoozed_until TEXT,
    dismissed_at  TEXT,
    notified_at   TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_reminders_due ON reminders(dismissed_at, due_at);

CREATE TABLE notification_state (
    key           TEXT PRIMARY KEY,
    snoozed_until TEXT,
    dismissed_at  TEXT,
    notified_at   TEXT
);

CREATE TABLE entity_links (
    id         INTEGER PRIMARY KEY,
    src_kind   TEXT NOT NULL,
    src_id     INTEGER NOT NULL,
    dst_kind   TEXT NOT NULL,
    dst_id     INTEGER NOT NULL,
    label      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (src_kind, src_id, dst_kind, dst_id)
);
CREATE INDEX idx_links_dst ON entity_links(dst_kind, dst_id);

CREATE TABLE file_refs (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL CHECK (length(trim(path)) > 0),
    label      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE routine_items (
    id         INTEGER PRIMARY KEY,
    routine    TEXT NOT NULL CHECK (routine IN ('morning', 'evening')),
    title      TEXT NOT NULL CHECK (length(trim(title)) > 0),
    position   INTEGER NOT NULL DEFAULT 0,
    archived   INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE routine_logs (
    item_id INTEGER NOT NULL REFERENCES routine_items(id) ON DELETE CASCADE,
    date    TEXT NOT NULL,
    PRIMARY KEY (item_id, date)
);

ALTER TABLE study_sessions ADD COLUMN task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL;
ALTER TABLE study_sessions ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE study_sessions ADD COLUMN kind TEXT NOT NULL DEFAULT 'study'
    CHECK (kind IN ('study', 'practice', 'work', 'reading', 'other'));

CREATE TABLE http_cache (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE search_index USING fts5(
    kind UNINDEXED, ref_id UNINDEXED, title, body, tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3'
)
"""


def _migrate_v3(db: Database) -> None:
    """Home & planning: projects, richer tasks/events/habits, reviews, inbox, reminders, links, search."""
    for statement in _split_sql(SCHEMA_V3):
        db.execute(statement)
    for source in SEARCH_SOURCES_V3:
        for statement in search_triggers(*source):
            db.execute(statement)
        db.execute(search_backfill(*source))


def _migrate_v4(db: Database) -> None:
    """StudyForge: courses, documents, question bank, blueprints, tests, revision state, flashcards."""
    from src.modules.studyforge.schema import SCHEMA_V4, SEARCH_SOURCES_V4

    for statement in _split_sql(SCHEMA_V4):
        db.execute(statement)
    for source in SEARCH_SOURCES_V4:
        for statement in search_triggers(*source):
            db.execute(statement)
        db.execute(search_backfill(*source))


def _migrate_v5(db: Database) -> None:
    """SecondBrain (note kinds, formats, collections, attachments) and ClipVault (private history, rules)."""
    from src.modules.brain.schema import SCHEMA_V5_BRAIN, SEARCH_SOURCES_V5
    from src.modules.clipvault.schema import SCHEMA_V5_CLIP

    for statement in _split_sql(SCHEMA_V5_BRAIN) + _split_sql(SCHEMA_V5_CLIP):
        db.execute(statement)
    # notes are re-indexed with their new searchable fields
    for table, kind, *_ in SEARCH_SOURCES_V5:
        for suffix in ("ai", "au", "ad"):
            db.execute(f"DROP TRIGGER IF EXISTS {table}_{suffix}_search")
        db.execute(f"DELETE FROM search_index WHERE rowid IN (SELECT id * 64 + {SEARCH_KINDS[kind]} FROM {table})")
    for source in SEARCH_SOURCES_V5:
        for statement in search_triggers(*source):
            db.execute(statement)
        db.execute(search_backfill(*source))


def _migrate_v6(db: Database) -> None:
    """FilePilot: scan summaries and the file-operation history."""
    from src.modules.filepilot.schema import SCHEMA_V6_FILEPILOT

    for statement in _split_sql(SCHEMA_V6_FILEPILOT):
        db.execute(statement)


def _migrate_v7(db: Database) -> None:
    """AudioDock: saved audio profiles, with four starting profiles (no devices chosen yet)."""
    from src.modules.audiodock.schema import SCHEMA_V7_AUDIO, STARTER_PROFILES

    db.execute(SCHEMA_V7_AUDIO)
    from src.services.dates import now_stamp

    for position, (name, kind, comms, notes) in enumerate(STARTER_PROFILES, start=1):
        db.execute("INSERT INTO ad_profiles (name, kind, communications, notes, position, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?)", (name, kind, comms, notes, position, now_stamp()))


def _all_search_sources() -> list:
    """The current definition of every search source; a later migration's definition of a table wins."""
    from src.modules.brain.schema import SEARCH_SOURCES_V5
    from src.modules.studyforge.schema import SEARCH_SOURCES_V4

    by_table: dict[str, tuple] = {}
    for source in list(SEARCH_SOURCES_V3) + list(SEARCH_SOURCES_V4) + list(SEARCH_SOURCES_V5):
        by_table[source[0]] = source
    return list(by_table.values())


# Every search source, across all migrations (used to rebuild the index).
ALL_SEARCH_SOURCES = _all_search_sources()

MIGRATIONS: list[tuple[int, Migration]] = [
    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
    (4, _migrate_v4),
    (5, _migrate_v5),
    (6, _migrate_v6),
    (7, _migrate_v7),
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
