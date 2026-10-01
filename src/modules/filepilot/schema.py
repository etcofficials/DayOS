"""FilePilot schema (migration 6): scan summaries and the file-operation history.

Scan results themselves stay in memory (they can be rebuilt by rescanning);
every file operation DayOS performs is recorded so it can be reviewed or undone.
"""

from __future__ import annotations

SCHEMA_V6_FILEPILOT = """
CREATE TABLE fp_scans (
    id          INTEGER PRIMARY KEY,
    roots       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    files       INTEGER NOT NULL DEFAULT 0,
    bytes       INTEGER NOT NULL DEFAULT 0,
    errors      INTEGER NOT NULL DEFAULT 0,
    cancelled   INTEGER NOT NULL DEFAULT 0 CHECK (cancelled IN (0, 1))
);

CREATE TABLE fp_operations (
    id          INTEGER PRIMARY KEY,
    batch_id    TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('move', 'recycle', 'undo_move')),
    source      TEXT NOT NULL,
    destination TEXT NOT NULL DEFAULT '',
    size        INTEGER NOT NULL DEFAULT 0,
    reason      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL CHECK (status IN ('done', 'skipped', 'failed', 'undone')),
    message     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_fp_operations_batch ON fp_operations(batch_id);
"""

TABLES_V6 = ["fp_scans", "fp_operations"]
