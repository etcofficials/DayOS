from __future__ import annotations

from src.models import Note, from_row
from src.repositories.base import Repository, clean_text
from src.services.dates import now_stamp

MAX_CONTENT = 1_000_000


def normalize_tags(tags: str | list[str]) -> str:
    items = tags if isinstance(tags, list) else str(tags).split(",")
    seen: list[str] = []
    for tag in items:
        tag = tag.strip().lstrip("#").strip()
        if tag and tag.lower() not in (t.lower() for t in seen):
            seen.append(tag[:40])
    return ", ".join(seen)


class NoteRepository(Repository):
    def create(self, title: str = "", content: str = "", tags: str = "", pinned: bool = False) -> int:
        stamp = now_stamp()
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO notes (title, content, tags, pinned, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    clean_text(title, field="Title", max_len=200),
                    clean_text(content, field="Note", max_len=MAX_CONTENT),
                    normalize_tags(tags),
                    int(pinned),
                    stamp,
                    stamp,
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

    def set_pinned(self, note_id: int, pinned: bool) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE notes SET pinned = ? WHERE id = ?", (int(pinned), note_id))

    def get(self, note_id: int) -> Note | None:
        row = self.db.query_one("SELECT * FROM notes WHERE id = ?", (note_id,))
        return from_row(Note, row) if row else None

    def delete(self, note_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def list(self, search: str = "", tag: str = "", limit: int = 1000) -> list[Note]:
        where: list[str] = []
        params: list = []
        if search.strip():
            like = f"%{search.strip()}%"
            where.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
            params.extend([like, like, like])
        if tag:
            where.append("(',' || replace(tags, ', ', ',') || ',') LIKE ?")
            params.append(f"%,{tag},%")
        sql = "SELECT * FROM notes"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY pinned DESC, updated_at DESC, id DESC LIMIT ?"
        params.append(limit)
        return [from_row(Note, r) for r in self.db.query(sql, params)]

    def all_tags(self) -> list[str]:
        tags: dict[str, str] = {}
        for row in self.db.query("SELECT tags FROM notes WHERE tags != ''"):
            for tag in row[0].split(","):
                tag = tag.strip()
                if tag:
                    tags.setdefault(tag.lower(), tag)
        return sorted(tags.values(), key=str.lower)

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM notes", default=0))
