"""SecondBrain schema (part of migration 5).

Notes gain a kind (bookmark, snippet, command …), a format (plain or Markdown),
an optional collection, a URL, a language, an archived flag and a source. Existing
notes keep every field and simply become plain-text notes of kind "note".

Attachments are copied into the database (size-capped) so that backups, restores
and exports always include them; the original files are never touched.
"""

from __future__ import annotations

NOTE_KINDS: dict[str, str] = {
    "note": "Note",
    "bookmark": "Bookmark",
    "snippet": "Code snippet",
    "command": "Terminal command",
    "idea": "Project idea",
    "troubleshooting": "Troubleshooting",
    "study": "Study note",
    "reference": "Reference",
}

NOTE_KIND_ICONS: dict[str, str] = {
    "note": "notes", "bookmark": "link", "snippet": "code", "command": "terminal", "idea": "lightbulb",
    "troubleshooting": "mistake", "study": "book", "reference": "folder",
}

NOTE_FORMATS = ("plain", "markdown")

_KINDS_SQL = ", ".join(f"'{k}'" for k in NOTE_KINDS)

SCHEMA_V5_BRAIN = f"""
CREATE TABLE sb_collections (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) > 0),
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

ALTER TABLE notes ADD COLUMN kind TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ({_KINDS_SQL}));
ALTER TABLE notes ADD COLUMN format TEXT NOT NULL DEFAULT 'plain' CHECK (format IN ('plain', 'markdown'));
ALTER TABLE notes ADD COLUMN collection_id INTEGER REFERENCES sb_collections(id) ON DELETE SET NULL;
ALTER TABLE notes ADD COLUMN url TEXT NOT NULL DEFAULT '';
ALTER TABLE notes ADD COLUMN language TEXT NOT NULL DEFAULT '';
ALTER TABLE notes ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE notes ADD COLUMN source TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_notes_kind ON notes(kind, archived);
CREATE INDEX idx_notes_collection ON notes(collection_id);

CREATE TABLE sb_attachments (
    id         INTEGER PRIMARY KEY,
    note_id    INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    filename   TEXT NOT NULL CHECK (length(trim(filename)) > 0),
    mime       TEXT NOT NULL DEFAULT '',
    size       INTEGER NOT NULL CHECK (size >= 0),
    sha256     TEXT NOT NULL,
    data       BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_sb_attachments_note ON sb_attachments(note_id);
"""

# Notes are re-indexed so URLs and snippet languages are searchable too.
SEARCH_SOURCES_V5 = [
    ("notes", "note", "{r}.title", "{r}.content || ' ' || {r}.tags || ' ' || {r}.url || ' ' || {r}.language"),
]

TABLES_V5_BRAIN = ["sb_collections", "sb_attachments"]
