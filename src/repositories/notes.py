from __future__ import annotations

import re

from src.models import Note, from_row
from src.repositories.base import Repository, clean_text
from src.services.dates import ValidationError, now_stamp

MAX_CONTENT = 1_000_000

NOTE_KINDS = ("note", "bookmark", "snippet", "command", "idea", "troubleshooting", "study", "reference")
NOTE_FORMATS = ("plain", "markdown")
UNFILED = -1  # ``collection_id`` filter for notes that are in no collection

_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_DOMAIN = re.compile(r"^(localhost|[\w-]+(\.[\w-]+)+)(:\d+)?([/?#].*)?$", re.UNICODE)


def normalize_tags(tags: str | list[str]) -> str:
    items = tags if isinstance(tags, list) else str(tags).split(",")
    seen: list[str] = []
    for tag in items:
        tag = tag.strip().lstrip("#").strip()
        if tag and tag.lower() not in (t.lower() for t in seen):
            seen.append(tag[:40])
    return ", ".join(seen)


def normalize_url(url: str) -> str:
    """Accept http(s) links only; ``example.com/page`` becomes ``https://example.com/page``."""
    url = str(url or "").strip()
    if not url:
        return ""
    if len(url) > 2000 or any(c.isspace() for c in url):
        raise ValidationError("That doesn't look like a web address.")
    if not _SCHEME.match(url):
        if not _DOMAIN.match(url):
            raise ValidationError("That doesn't look like a web address.")
        url = "https://" + url
    scheme = url.split(":", 1)[0].lower()
    if scheme not in ("http", "https"):
        raise ValidationError("Only web links (http or https) can be saved as bookmarks.")
    if len(url.split("://", 1)) != 2 or not url.split("://", 1)[1].strip("/"):
        raise ValidationError("That doesn't look like a web address.")
    return url


def _content(content: str, keep_indent: bool = False) -> str:
    if not keep_indent:
        return clean_text(content, field="Note", max_len=MAX_CONTENT)
    text = "" if content is None else str(content).strip("\r\n").rstrip()
    if len(text) > MAX_CONTENT:
        raise ValidationError(f"Note is too long (maximum {MAX_CONTENT} characters).")
    return text


class NoteRepository(Repository):
    def create(self, title: str = "", content: str = "", tags: str = "", pinned: bool = False, *,
               kind: str = "note", format: str = "plain", collection_id: int | None = None, url: str = "",
               language: str = "", source: str = "") -> int:
        if kind not in NOTE_KINDS:
            raise ValidationError(f"Unknown note type: {kind}")
        if format not in NOTE_FORMATS:
            raise ValidationError(f"Unknown note format: {format}")
        stamp = now_stamp()
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO notes (title, content, tags, pinned, created_at, updated_at, kind, format, "
                "collection_id, url, language, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    clean_text(title, field="Title", max_len=200),
                    _content(content, keep_indent=kind in ("snippet", "command")),
                    normalize_tags(tags),
                    int(pinned),
                    stamp,
                    stamp,
                    kind,
                    format,
                    collection_id,
                    normalize_url(url),
                    clean_text(language, field="Language", max_len=40),
                    clean_text(source, field="Source", max_len=200),
                ),
            )

    def save(self, note_id: int, title: str, content: str, tags: str) -> str:
        """Save editor contents; returns the new updated_at stamp."""
        stamp = now_stamp()
        with self.db.transaction():
            self.db.execute(
                "UPDATE notes SET title = ?, content = ?, tags = ?, updated_at = ? WHERE id = ?",
                (
                    clean_text(title, field="Title", max_len=200),
                    str(content)[:MAX_CONTENT],
                    normalize_tags(tags),
                    stamp,
                    note_id,
                ),
            )
        return stamp

    def update_meta(self, note_id: int, **fields) -> str:
        """Change kind, format, collection, URL, language or archived state. Returns updated_at."""
        allowed = {"kind", "format", "collection_id", "url", "language", "archived"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown note fields: {', '.join(sorted(unknown))}")
        if "kind" in fields and fields["kind"] not in NOTE_KINDS:
            raise ValidationError(f"Unknown note type: {fields['kind']}")
        if "format" in fields and fields["format"] not in NOTE_FORMATS:
            raise ValidationError(f"Unknown note format: {fields['format']}")
        if "url" in fields:
            fields["url"] = normalize_url(fields["url"])
        if "language" in fields:
            fields["language"] = clean_text(fields["language"], field="Language", max_len=40)
        if "archived" in fields:
            fields["archived"] = int(bool(fields["archived"]))
        if "collection_id" in fields and fields["collection_id"] is not None:
            fields["collection_id"] = int(fields["collection_id"])
            if not self.db.scalar("SELECT 1 FROM sb_collections WHERE id = ?", (fields["collection_id"],)):
                raise ValidationError("That collection no longer exists.")
        stamp = now_stamp()
        if not fields:
            return stamp
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.db.transaction():
            self.db.execute(f"UPDATE notes SET {sets}, updated_at = ? WHERE id = ?",
                            (*fields.values(), stamp, note_id))
        return stamp

    def set_pinned(self, note_id: int, pinned: bool) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE notes SET pinned = ? WHERE id = ?", (int(pinned), note_id))

    def get(self, note_id: int) -> Note | None:
        row = self.db.query_one("SELECT * FROM notes WHERE id = ?", (note_id,))
        return from_row(Note, row) if row else None

    def delete(self, note_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def list(self, search: str = "", tag: str = "", limit: int = 1000, *, kind: str | None = None,
             collection_id: int | None = None, archived: bool | None = False) -> list[Note]:
        """Notes, pinned first then most recently updated.

        ``collection_id`` may be :data:`UNFILED`; ``archived=None`` includes archived notes.
        """
        where: list[str] = []
        params: list = []
        if search.strip():
            like = f"%{search.strip()}%"
            where.append("(title LIKE ? OR content LIKE ? OR tags LIKE ? OR url LIKE ?)")
            params.extend([like, like, like, like])
        if tag:
            where.append("(',' || replace(tags, ', ', ',') || ',') LIKE ?")
            params.append(f"%,{tag},%")
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if collection_id == UNFILED:
            where.append("collection_id IS NULL")
        elif collection_id is not None:
            where.append("collection_id = ?")
            params.append(int(collection_id))
        if archived is not None:
            where.append("archived = ?")
            params.append(int(archived))
        sql = "SELECT * FROM notes"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY pinned DESC, updated_at DESC, id DESC LIMIT ?"
        params.append(limit)
        return [from_row(Note, r) for r in self.db.query(sql, params)]

    def find_by_url(self, url: str) -> Note | None:
        row = self.db.query_one("SELECT * FROM notes WHERE url = ? ORDER BY id LIMIT 1", (url,))
        return from_row(Note, row) if row else None

    def find_by_title(self, title: str) -> Note | None:
        """Exact (case-insensitive) title match, used to resolve [[wiki links]]."""
        title = str(title or "").strip()
        if not title:
            return None
        row = self.db.query_one(
            "SELECT * FROM notes WHERE title = ? COLLATE NOCASE ORDER BY archived, updated_at DESC LIMIT 1", (title,))
        return from_row(Note, row) if row else None

    def all_tags(self) -> list[str]:
        tags: dict[str, str] = {}
        for row in self.db.query("SELECT tags FROM notes WHERE tags != ''"):
            for tag in row[0].split(","):
                tag = tag.strip()
                if tag:
                    tags.setdefault(tag.lower(), tag)
        return sorted(tags.values(), key=str.lower)

    def kind_counts(self) -> dict[str, int]:
        return {r[0]: int(r[1]) for r in
                self.db.query("SELECT kind, COUNT(*) FROM notes WHERE archived = 0 GROUP BY kind")}

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM notes", default=0))
