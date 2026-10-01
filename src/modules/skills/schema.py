"""Skills schema (part of migration 8): skills, prerequisites, roadmap items and activity logs.

There are no scores: progress is shown through milestones you complete and evidence
you record (time learning vs. practising vs. building).
"""

SCHEMA_V8_SKILLS = """
CREATE TABLE skills (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) > 0),
    category    TEXT NOT NULL DEFAULT '',
    baseline    TEXT NOT NULL DEFAULT '',
    goal        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'done')),
    review_date TEXT,
    notes       TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE skill_prereqs (
    skill_id    INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    requires_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY (skill_id, requires_id),
    CHECK (skill_id != requires_id)
);

CREATE TABLE skill_items (
    id         INTEGER PRIMARY KEY,
    skill_id   INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('milestone', 'resource', 'practice')),
    title      TEXT NOT NULL CHECK (length(trim(title)) > 0),
    url        TEXT NOT NULL DEFAULT '',
    done_at    TEXT,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_skill_items ON skill_items(skill_id, kind, position);

CREATE TABLE skill_logs (
    id           INTEGER PRIMARY KEY,
    skill_id     INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    minutes      INTEGER CHECK (minutes IS NULL OR minutes > 0),
    mode         TEXT NOT NULL DEFAULT 'practice' CHECK (mode IN ('learn', 'practice', 'build')),
    note         TEXT NOT NULL DEFAULT '',
    evidence_url TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_skill_logs ON skill_logs(skill_id, date)
"""

SEARCH_SOURCES_V8_SKILLS = [
    ("skills", "skill", "{r}.name", "{r}.category || ' ' || {r}.goal || ' ' || {r}.notes"),
]
