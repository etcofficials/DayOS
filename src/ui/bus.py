"""Application-wide change notifications.

Repositories stay Qt-free; the UI announces what changed after a successful
write (``bus.notify("tasks")``) and pages that display that data refresh —
immediately when visible, otherwise lazily the next time they are shown.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

DOMAINS = (
    "tasks", "notes", "habits", "goals", "journal", "schedule", "study", "exams", "subjects", "settings",
    "projects", "inbox", "reminders", "links", "routines", "studyforge", "clips", "files", "money", "skills",
    "briefing", "all",
)


class DataBus(QObject):
    changed = Signal(str)

    def notify(self, *domains: str) -> None:
        for domain in domains:
            self.changed.emit(domain)


bus = DataBus()
