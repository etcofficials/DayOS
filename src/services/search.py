"""Universal local search over every module, backed by one SQLite FTS5 index.

The index (``search_index``) is maintained by database triggers, so it is always
consistent with the records. Clipboard history is never indexed; it is searched
only when the user allows it (see ``ClipVault``), through an extra provider.
Nothing here touches the network.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable

from src.database import Database

log = logging.getLogger(__name__)

KIND_LABELS = {
    "task": "Task", "note": "Note", "event": "Event", "goal": "Goal", "exam": "Exam", "project": "Project",
    "inbox": "Inbox", "chapter": "Chapter", "question": "Question", "course": "Course", "skill": "Skill",
    "flashcard": "Flashcard", "material": "Study material", "mistake": "Mistake", "project_log": "Project log",
    "milestone": "Milestone", "subscription": "Subscription", "clip": "Clipboard", "file": "File",
}

KIND_ICONS = {
    "task": "tasks", "note": "notes", "event": "calendar", "goal": "goals", "exam": "exams", "project": "folder",
    "inbox": "inbox", "chapter": "book", "question": "exams", "course": "subject", "skill": "chart",
    "flashcard": "book", "material": "book", "mistake": "mistake", "project_log": "folder", "milestone": "flag",
    "subscription": "money", "clip": "clipboard", "file": "folder",
}


@dataclass(frozen=True)
class SearchHit:
    kind: str
    ref_id: int
    title: str
    snippet: str = ""
    score: float = 0.0

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind.title())


_TOKEN = re.compile(r"\w+", re.UNICODE)


def build_match(text: str, max_tokens: int = 8) -> str | None:
    """Turn free text into a safe FTS5 query: every word must match as a prefix."""
    tokens = _TOKEN.findall(text or "")[:max_tokens]
    if not tokens:
        return None
    return " ".join(f'"{t}"*' for t in tokens)


Provider = Callable[[str, int], list[SearchHit]]


class SearchService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._providers: dict[str, Provider] = {}

    def add_provider(self, name: str, provider: Provider) -> None:
        """Extra search sources that are not in the index (e.g. clipboard history when allowed)."""
        self._providers[name] = provider

    def remove_provider(self, name: str) -> None:
        self._providers.pop(name, None)

    def search(self, text: str, kinds: set[str] | None = None, limit: int = 40) -> list[SearchHit]:
        match = build_match(text)
        if match is None:
            return []
        hits: list[SearchHit] = []
        try:
            rows = self.db.query(
                "SELECT kind, ref_id, title, snippet(search_index, 3, '', '', '…', 12) AS snip, "
                "bm25(search_index, 0, 0, 6.0, 1.0) AS score FROM search_index WHERE search_index MATCH ? "
                "ORDER BY score LIMIT ?", (match, int(limit) * 2))
        except sqlite3.Error:
            log.warning("Search query failed", exc_info=True)
            rows = []
        for row in rows:
            if kinds and row["kind"] not in kinds:
                continue
            title = (row["title"] or "").strip() or "Untitled"
            hits.append(SearchHit(row["kind"], int(row["ref_id"]), title[:160], (row["snip"] or "")[:200],
                                  float(row["score"])))
        for name, provider in list(self._providers.items()):
            try:
                extra = provider(text, limit)
            except Exception:
                log.warning("Search provider %s failed", name, exc_info=True)
                continue
            hits.extend(h for h in extra if not kinds or h.kind in kinds)
        return hits[:limit]

    def rebuild(self) -> int:
        """Recreate the whole index from the records (Settings → Data → Rebuild search index)."""
        from src.database.schema import ALL_SEARCH_SOURCES, search_backfill

        existing = {r[0] for r in self.db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
        with self.db.transaction():
            self.db.execute("DELETE FROM search_index")
            for source in ALL_SEARCH_SOURCES:
                if source[0] in existing:
                    self.db.execute(search_backfill(*source))
        return int(self.db.scalar("SELECT COUNT(*) FROM search_index", default=0))
