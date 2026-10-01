"""Cross-module links (note ↔ task ↔ project ↔ course …) and file references.

A link is stored once in ``entity_links`` and read in both directions. Kinds are
plain strings (``task``, ``note``, ``project``, ``goal``, ``event``, ``file``,
``course``, ``question`` …); a link to a deleted record is simply skipped and
cleaned up by :meth:`LinkRepository.prune`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.repositories.base import Repository, clean_text
from src.services.dates import ValidationError, now_stamp

# kind -> (table, title column) for resolving link titles
KIND_TABLES = {
    "task": ("tasks", "title"), "note": ("notes", "title"), "project": ("projects", "name"),
    "goal": ("goals", "title"), "event": ("events", "title"), "exam": ("exams", "title"),
    "file": ("file_refs", "label"), "habit": ("habits", "name"), "inbox": ("inbox", "text"),
}


def register_kind(kind: str, table: str, title_column: str) -> None:
    KIND_TABLES[kind] = (table, title_column)


@dataclass(frozen=True)
class LinkedItem:
    link_id: int
    kind: str
    ref_id: int
    title: str


class LinkRepository(Repository):
    def link(self, src_kind: str, src_id: int, dst_kind: str, dst_id: int, label: str = "") -> int | None:
        if (src_kind, src_id) == (dst_kind, dst_id):
            raise ValidationError("An item can't be linked to itself.")
        for kind in (src_kind, dst_kind):
            if kind not in KIND_TABLES:
                raise ValidationError(f"Unknown item type: {kind}")
        # store links in a canonical direction so a pair is never duplicated
        a, b = sorted([(src_kind, int(src_id)), (dst_kind, int(dst_id))])
        with self.db.transaction():
            cur = self.db.execute(
                "INSERT OR IGNORE INTO entity_links (src_kind, src_id, dst_kind, dst_id, label, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)", (a[0], a[1], b[0], b[1], clean_text(label, field="Label", max_len=80),
                                              now_stamp()))
            return int(cur.lastrowid) if cur.rowcount else None

    def unlink(self, link_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM entity_links WHERE id = ?", (link_id,))

    def links_for(self, kind: str, ref_id: int) -> list[LinkedItem]:
        rows = self.db.query(
            "SELECT id, dst_kind AS kind, dst_id AS ref FROM entity_links WHERE src_kind = ? AND src_id = ? "
            "UNION ALL SELECT id, src_kind, src_id FROM entity_links WHERE dst_kind = ? AND dst_id = ?",
            (kind, ref_id, kind, ref_id))
        out: list[LinkedItem] = []
        for row in rows:
            title = self.title_of(row["kind"], row["ref"])
            if title is not None:
                out.append(LinkedItem(int(row["id"]), row["kind"], int(row["ref"]), title))
        return sorted(out, key=lambda x: (x.kind, x.title.lower()))

    def title_of(self, kind: str, ref_id: int) -> str | None:
        if kind not in KIND_TABLES:
            return None
        table, column = KIND_TABLES[kind]
        if kind == "file":
            row = self.db.query_one("SELECT label, path FROM file_refs WHERE id = ?", (ref_id,))
            return (row["label"] or Path(row["path"]).name) if row else None
        value = self.db.scalar(f"SELECT {column} FROM {table} WHERE id = ?", (ref_id,))
        if value is None:
            return None
        text = str(value).strip() or "Untitled"
        return text if len(text) <= 120 else text[:117] + "…"

    def prune(self) -> int:
        """Remove links whose records no longer exist. Returns how many were removed."""
        removed = 0
        for row in self.db.query("SELECT id, src_kind, src_id, dst_kind, dst_id FROM entity_links"):
            if self.title_of(row["src_kind"], row["src_id"]) is None or self.title_of(row["dst_kind"], row["dst_id"]) is None:
                self.unlink(int(row["id"]))
                removed += 1
        return removed

    # -- file references --------------------------------------------------------------
    def add_file(self, path: str, label: str = "") -> int:
        path = clean_text(path, field="File path", required=True, max_len=1000)
        with self.db.transaction():
            return self.db.insert("INSERT INTO file_refs (path, label, created_at) VALUES (?, ?, ?)",
                                  (path, clean_text(label, field="Label", max_len=120), now_stamp()))

    def file_path(self, file_id: int) -> str | None:
        return self.db.scalar("SELECT path FROM file_refs WHERE id = ?", (file_id,))

    def attach_file(self, kind: str, ref_id: int, path: str, label: str = "") -> int:
        """Reference a file from a record (the file itself is never copied or modified)."""
        file_id = self.add_file(path, label)
        self.link(kind, ref_id, "file", file_id)
        return file_id
