from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from src.context import AppContext
from src.ui.bus import bus
from src.ui.widgets.common import button, confirm, guarded, label


class SubjectsDialog(QDialog):
    """Add, rename, archive and delete subjects."""

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Subjects")
        self.setMinimumSize(440, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Subjects", "section"))
        lay.addWidget(label("Used by tasks, study sessions, exams, classes and test results.", "muted", wrap=True))
        add = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("New subject, e.g. Biology")
        self.name.returnPressed.connect(self._add)
        add.addWidget(self.name, 1)
        add.addWidget(button("Add", "primary", "plus", self._add))
        lay.addLayout(add)
        self.list = QListWidget()
        self.list.setAccessibleName("Subjects")
        self.list.itemDoubleClicked.connect(lambda _: self._rename())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button("Rename", "ghost", "edit", self._rename))
        self.archive_btn = button("Archive", "ghost", "archive", self._archive)
        row.addWidget(self.archive_btn)
        row.addWidget(button("Delete", "ghost", "trash", self._delete))
        row.addStretch(1)
        row.addWidget(button("Done", "", on_click=self.accept))
        lay.addLayout(row)
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self._reload()
        self.name.setFocus()

    def _reload(self) -> None:
        current = self._selected()
        self.list.clear()
        for s in self.ctx.subjects.list(include_archived=True):
            item = QListWidgetItem(s.name + ("  (archived)" if s.archived else ""))
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, s.archived)
            self.list.addItem(item)
            if s.id == current:
                self.list.setCurrentItem(item)
        self._update_buttons()

    def _selected(self) -> int | None:
        item = self.list.currentItem() if hasattr(self, "list") else None
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _update_buttons(self) -> None:
        item = self.list.currentItem()
        self.archive_btn.setText("Restore" if item and item.data(Qt.ItemDataRole.UserRole + 1) else "Archive")

    def _add(self) -> None:
        name = self.name.text()
        if guarded(self, lambda: self.ctx.subjects.create(name), "Couldn't add the subject"):
            self.name.clear()
            bus.notify("subjects")
            self._reload()

    def _rename(self) -> None:
        sid = self._selected()
        subject = self.ctx.subjects.get(sid) if sid else None
        if not subject:
            return
        text, ok = QInputDialog.getText(self, "Rename subject", "New name:", text=subject.name)
        if ok and guarded(self, lambda: self.ctx.subjects.rename(subject.id, text), "Couldn't rename"):
            bus.notify("subjects", "tasks", "study", "exams", "schedule")
            self._reload()

    def _archive(self) -> None:
        sid = self._selected()
        subject = self.ctx.subjects.get(sid) if sid else None
        if subject and guarded(self, lambda: self.ctx.subjects.set_archived(subject.id, not subject.archived)):
            bus.notify("subjects")
            self._reload()

    def _delete(self) -> None:
        sid = self._selected()
        subject = self.ctx.subjects.get(sid) if sid else None
        if not subject:
            return
        usage = {k: v for k, v in self.ctx.subjects.usage(subject.id).items() if v}
        detail = ""
        if usage:
            detail = ("\n\nIt is used by: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in usage.items())
                      + ". Those records are kept — they just won't have a subject. Archiving hides it instead.")
        if confirm(self, "Delete subject?", f"“{subject.name}” will be deleted.{detail}"):
            if guarded(self, lambda: self.ctx.subjects.delete(subject.id)):
                bus.notify("subjects", "tasks", "study", "exams", "schedule")
                self._reload()
