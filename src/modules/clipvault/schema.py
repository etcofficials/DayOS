"""ClipVault schema (part of migration 5).

Clipboard history is private: ``cv_entries`` is never added to the universal search
index, is left out of JSON exports unless the user explicitly includes it, and is
never written to logs. Exclusion rules (``cv_rules``) are ordinary preferences.
"""

from __future__ import annotations

CLIP_KINDS: dict[str, str] = {
    "text": "Text",
    "url": "Link",
    "code": "Code",
    "command": "Command",
    "template": "Template",
}

RULE_KINDS: dict[str, str] = {
    "app": "Copied from app",
    "contains": "Text contains",
    "pattern": "Text matches pattern",
}

SCHEMA_V5_CLIP = """
CREATE TABLE cv_entries (
    id           INTEGER PRIMARY KEY,
    content      TEXT NOT NULL CHECK (length(content) > 0),
    content_hash TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL DEFAULT 'text' CHECK (kind IN ('text', 'url', 'code', 'command', 'template')),
    title        TEXT NOT NULL DEFAULT '',
    category     TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '',
    pinned       INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    favorite     INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
    origin       TEXT NOT NULL DEFAULT 'captured' CHECK (origin IN ('captured', 'manual')),
    source_app   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    use_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_cv_entries_recent ON cv_entries(pinned, last_used_at);

CREATE TABLE cv_rules (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('app', 'contains', 'pattern')),
    value      TEXT NOT NULL CHECK (length(trim(value)) > 0),
    enabled    INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (kind, value)
);
"""
