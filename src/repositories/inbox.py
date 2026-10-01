"""The capture inbox: quick thoughts saved now and organised later.

Converting an item creates the real record (task, note, reminder, project …)
and marks the inbox item processed, pointing at the result, so content is never
duplicated in two live places. Nothing is interpreted automatically: dates or
kinds suggested by the capture window are only applied after the user confirms.
"""

from __future__ import annotations

from src.models import InboxItem, from_row
from src.repositories.base import Repository, clean_text
from src.services.dates import ValidationError, now_stamp

KINDS = {
    "task": "Task", "reminder": "Reminder", "note": "Note", "idea": "Idea", "link": "Link",
    "snippet": "Code snippet", "project": "Project action", "study": "Study topic",
}


def clean_url(url: str) -> str:
    url = (url or "").strip()
    if url and not url.lower().startswith(("http://", "https://")):
        raise ValidationError("Links must start with http:// or https://")
    return url[:2000]


class InboxRepository(Repository):
    def add(self, kind: str, text: str, url: str = "") -> int:
        if kind not in KINDS:
            raise ValidationError("Unknown capture type.")
        text = clean_text(text, field="Capture", required=True, max_len=20000)
        with self.db.transaction():
            return self.db.insert("INSERT INTO inbox (kind, text, url, created_at) VALUES (?, ?, ?, ?)",
                                  (kind, text, clean_url(url), now_stamp()))

    def get(self, item_id: int) -> InboxItem | None:
        row = self.db.query_one("SELECT * FROM inbox WHERE id = ?", (item_id,))
        return from_row(InboxItem, row) if row else None

    def open_items(self, limit: int = 500) -> list[InboxItem]:
        rows = self.db.query("SELECT * FROM inbox WHERE processed_at IS NULL ORDER BY created_at DESC, id DESC LIMIT ?",
                             (limit,))
        return [from_row(InboxItem, r) for r in rows]

    def processed(self, limit: int = 100) -> list[InboxItem]:
        rows = self.db.query("SELECT * FROM inbox WHERE processed_at IS NOT NULL ORDER BY processed_at DESC LIMIT ?",
                             (limit,))
        return [from_row(InboxItem, r) for r in rows]

    def count_open(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM inbox WHERE processed_at IS NULL", default=0))

    def update(self, item_id: int, kind: str, text: str, url: str = "") -> None:
        if kind not in KINDS:
            raise ValidationError("Unknown capture type.")
        text = clean_text(text, field="Capture", required=True, max_len=20000)
        with self.db.transaction():
            self.db.execute("UPDATE inbox SET kind = ?, text = ?, url = ? WHERE id = ?",
                            (kind, text, clean_url(url), item_id))

    def mark_processed(self, item_id: int, result_kind: str | None = None, result_id: int | None = None) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE inbox SET processed_at = ?, result_kind = ?, result_id = ? WHERE id = ?",
                            (now_stamp(), result_kind, result_id, item_id))

    def reopen(self, item_id: int) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE inbox SET processed_at = NULL, result_kind = NULL, result_id = NULL WHERE id = ?",
                            (item_id,))

    def delete(self, item_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM inbox WHERE id = ?", (item_id,))
