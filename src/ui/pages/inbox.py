"""Inbox: everything captured quickly, waiting to become a task, note, reminder or project."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QMenu, QVBoxLayout, QWidget

from src.repositories.inbox import KINDS
from src.services.dates import format_date
from src.ui.bus import bus
from src.ui.pages.base import Page
from src.ui.widgets.common import (
    EmptyState,
    PageHeader,
    SegmentBar,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
    tool_button,
)

KIND_TONES = {"task": "accent", "reminder": "amber", "note": "blue", "idea": "", "link": "blue", "snippet": "",
              "project": "terracotta", "study": "accent"}


class InboxPage(Page):
    domains = ("inbox", "settings")
    title = "Inbox"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.header = PageHeader("Inbox", "", eyebrow="Captured for later")
        self.header.add_action(button("Capture", "primary", "plus", self.new_item, "Quick capture (Ctrl+Shift+Space)"))
        self.root.addWidget(self.header)
        self.root.addWidget(label("Turn each item into what it really is, or let it go. Converting moves the text "
                                  "into the new record — nothing is duplicated.", "caption", wrap=True))
        self.view = SegmentBar([("open", "To sort"), ("done", "Recently sorted")], "open")
        self.view.changed.connect(lambda _: self.refresh())
        self.root.addWidget(self.view)
        self.holder = QWidget()
        self.list = QVBoxLayout(self.holder)
        self.list.setContentsMargins(0, 0, 6, 0)
        self.list.setSpacing(10)
        self.root.addWidget(scroll_wrap(self.holder), 1)

    def refresh(self) -> None:
        clear_layout(self.list)
        open_n = self.ctx.inbox.count_open()
        self.header.set_subtitle(f"{open_n} item{'s' if open_n != 1 else ''} to sort" if open_n else "All sorted")
        self.main.set_badge("inbox", str(open_n) if open_n else "")
        if self.view.current() == "open":
            items = self.ctx.inbox.open_items()
            if not items:
                self.list.addWidget(EmptyState(
                    "inbox", "Nothing to sort",
                    "Press Ctrl+Shift+Space anywhere in DayOS (or your global shortcut) to capture a thought in "
                    "seconds. It lands here until you decide what it is.",
                    [("Capture something", self.new_item)]))
            for item in items:
                self.list.addWidget(self._card(item))
        else:
            items = self.ctx.inbox.processed(60)
            if not items:
                self.list.addWidget(label("Sorted items appear here for a while, so you can find what they became.",
                                          "muted", wrap=True))
            for item in items:
                self.list.addWidget(self._done_row(item))
        self.list.addStretch(1)

    def _card(self, item) -> QWidget:
        card = QFrame()
        card.setProperty("card", True)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 12, 14, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        kind = QComboBox()
        for key, text in KINDS.items():
            kind.addItem(text, key)
        kind.setCurrentIndex(max(0, kind.findData(item.kind)))
        kind.setAccessibleName("Capture type")
        kind.currentIndexChanged.connect(lambda _i, it=item, k=kind: self._retype(it, k.currentData()))
        top.addWidget(kind)
        created = datetime.fromisoformat(item.created_at)
        top.addWidget(label(f"captured {format_date(created.date(), self.date_style)} {created:%H:%M}", "caption"), 1)
        more = tool_button("more", "More")
        more.clicked.connect(lambda _=False, it=item, b=more: self._menu(it, b))
        top.addWidget(more)
        lay.addLayout(top)
        text = label(item.text, "", wrap=True, selectable=True)
        lay.addWidget(text)
        if item.url:
            lay.addWidget(label(item.url, "link", wrap=True, selectable=True))
        row = QHBoxLayout()
        row.setSpacing(6)
        primary = {"task": "Make it a task", "reminder": "Set a reminder", "note": "Save as note", "idea": "Save as note",
                   "link": "Save link as note", "snippet": "Save snippet as note", "project": "Start a project",
                   "study": "Add as study task"}[item.kind]
        row.addWidget(button(primary, "primary", "check", lambda it=item: self.convert(it, item.kind)))
        for target, text_ in (("task", "Task"), ("note", "Note"), ("project", "Project")):
            if target != item.kind and not (target == "note" and item.kind in ("idea", "link", "snippet")):
                row.addWidget(button(text_, "soft", on_click=lambda it=item, t=target: self.convert(it, t)))
        row.addStretch(1)
        row.addWidget(button("Done, no action", "ghost", on_click=lambda it=item: self._archive(it)))
        lay.addLayout(row)
        return card

    def _done_row(self, item) -> QWidget:
        w = QFrame()
        w.setProperty("inset", True)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 8, 10, 8)
        lay.addWidget(chip(KINDS.get(item.result_kind or "", "Sorted") if item.result_kind else "No action",
                           KIND_TONES.get(item.result_kind or "", "")))
        lay.addWidget(label(item.text.splitlines()[0][:140], "", wrap=True), 1)
        if item.result_kind and self.main.openers.can_open(item.result_kind) and item.result_id:
            lay.addWidget(button("Open", "link", "chev-right",
                                 lambda it=item: self.main.openers.open(it.result_kind, it.result_id)))
        lay.addWidget(button("Back to inbox", "link", on_click=lambda it=item: self._reopen(it)))
        return w

    # -- actions ------------------------------------------------------------------
    def convert(self, item, target: str) -> None:
        """Create the real record (via its normal dialog, prefilled) and mark the capture sorted."""
        from src.ui.dialogs import TaskDialog

        first_line = item.text.splitlines()[0][:200]
        result_kind, result_id = None, None
        if target in ("task", "study"):
            dlg = TaskDialog(self.ctx, self, default_title=first_line)
            if len(item.text) > len(first_line) or item.url:
                dlg.desc.setPlainText((item.text + ("\n" + item.url if item.url else "")).strip())
            if target == "study":
                dlg.category.setCurrentText("Study")
            if not dlg.exec():
                return
            result_kind, result_id = "task", getattr(dlg, "saved_id", None)
        elif target == "reminder":
            from src.ui.shell.reminder_dialog import ReminderDialog

            dlg = ReminderDialog(self.ctx, self, title=first_line, note=item.text if item.text != first_line else "")
            if not dlg.exec():
                return
            result_kind, result_id = "reminder", dlg.saved_id
        elif target == "project":
            from src.ui.pages.projects_dialog import ProjectDialog

            dlg = ProjectDialog(self.ctx, self, name=first_line, description=item.text)
            if not dlg.exec():
                return
            result_kind, result_id = "project", dlg.saved_id
        else:  # note, idea, link, snippet
            body = item.text + (f"\n\n{item.url}" if item.url and item.url not in item.text else "")
            title = first_line if len(item.text) > 80 or "\n" in item.text else ""

            def make() -> None:
                nonlocal result_id
                if item.kind == "link" and item.url:
                    result_id = self.ctx.services["brain"].add_bookmark(
                        item.url, title or (first_line if item.text != item.url else ""),
                        item.text if item.text != item.url else "")[0]
                    return
                kind = {"idea": "idea", "snippet": "snippet"}.get(item.kind, "note")
                fmt = "plain" if kind == "snippet" else str(self.ctx.settings.get("brain.default_format"))
                result_id = self.ctx.notes.create(title, body, "idea" if item.kind == "idea" else "", kind=kind,
                                                  format=fmt, source="Inbox")

            if not guarded(self, make, "Couldn't create the note"):
                return
            result_kind = "note"
            bus.notify("notes")
        if guarded(self, lambda: self.ctx.inbox.mark_processed(item.id, result_kind, result_id)):
            bus.notify("inbox")
            self.toast("Sorted", "Open" if result_id else None,
                       (lambda: self.main.openers.open(result_kind, result_id)) if result_id else None)

    def _retype(self, item, kind: str) -> None:
        if guarded(self, lambda: self.ctx.inbox.update(item.id, kind, item.text, item.url)):
            bus.notify("inbox")

    def _archive(self, item) -> None:
        if guarded(self, lambda: self.ctx.inbox.mark_processed(item.id)):
            bus.notify("inbox")
            self.toast("Marked as sorted", "Undo", lambda: self._reopen(item))

    def _reopen(self, item) -> None:
        if guarded(self, lambda: self.ctx.inbox.reopen(item.id)):
            bus.notify("inbox")

    def _menu(self, item, anchor) -> None:
        menu = QMenu(self)
        menu.addAction("Edit text…", lambda: self._edit(item))
        menu.addAction("Delete…", lambda: self._delete(item))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _edit(self, item) -> None:
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getMultiLineText(self, "Edit capture", "Text", item.text)
        if ok and text.strip() and guarded(self, lambda: self.ctx.inbox.update(item.id, item.kind, text, item.url)):
            bus.notify("inbox")

    def _delete(self, item) -> None:
        if confirm(self, "Delete capture?", "This captured item will be deleted permanently."):
            if guarded(self, lambda: self.ctx.inbox.delete(item.id)):
                bus.notify("inbox")

    def new_item(self) -> None:
        self.main.quick_capture()
