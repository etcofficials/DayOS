"""Add, rename and remove SecondBrain collections (removing one never deletes notes)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem, QVBoxLayout

from src.ui.widgets.common import FadeDialog, button, confirm, guarded, label


class CollectionsDialog(FadeDialog):
    def __init__(self, brain, parent=None) -> None:
        super().__init__(parent)
        self.brain = brain
        self.setWindowTitle("Collections")
        self.setModal(True)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(12)
        lay.addWidget(label("Collections", "section"))
        lay.addWidget(label("Group notes into collections such as Work, Recipes or Linux. Removing a collection "
                            "keeps its notes; they simply become unfiled.", "muted", wrap=True))
        self.list = QListWidget()
        self.list.setAccessibleName("Collections")
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button("Add…", "soft", "plus", self.add))
        row.addWidget(button("Rename…", "ghost", "edit", self.rename))
        row.addWidget(button("Remove", "ghost", "trash", self.remove))
        row.addStretch(1)
        row.addWidget(button("Done", "primary", on_click=self.accept))
        lay.addLayout(row)
        self.fill()

    def fill(self) -> None:
        self.list.clear()
        for c in self.brain.collections.list():
            item = QListWidgetItem(f"{c.name}  ·  {c.count} note{'s' if c.count != 1 else ''}")
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, c.name)
            self.list.addItem(item)

    def _selected(self):
        item = self.list.currentItem()
        return (int(item.data(Qt.ItemDataRole.UserRole)), str(item.data(Qt.ItemDataRole.UserRole + 1))) if item else None

    def add(self) -> None:
        name, ok = QInputDialog.getText(self, "New collection", "Collection name")
        if ok and name.strip() and guarded(self, lambda: self.brain.collections.add(name)):
            self.fill()

    def rename(self) -> None:
        sel = self._selected()
        if sel is None:
            return
        name, ok = QInputDialog.getText(self, "Rename collection", "Collection name", text=sel[1])
        if ok and name.strip() and guarded(self, lambda: self.brain.collections.rename(sel[0], name)):
            self.fill()

    def remove(self) -> None:
        sel = self._selected()
        if sel is None:
            return
        if confirm(self, "Remove collection?", f"“{sel[1]}” will be removed. Its notes are kept and become unfiled.",
                   "Remove collection") and guarded(self, lambda: self.brain.collections.delete(sel[0])):
            self.fill()
