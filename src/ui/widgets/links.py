"""Linking records across modules: a small panel of linked items and a searchable picker."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.services.search import KIND_ICONS, KIND_LABELS, SearchHit
from src.ui.icons import icon
from src.ui.widgets.common import FadeDialog, SearchField, button, clear_layout, label, show_error, tool_button

# Recent items shown in the picker before the user types (kind -> SQL returning id, title).
_RECENT_SQL = {
    "note": "SELECT id, CASE WHEN title = '' THEN substr(content, 1, 60) ELSE title END FROM notes "
            "ORDER BY updated_at DESC LIMIT 15",
    "task": "SELECT id, title FROM tasks WHERE completed_at IS NULL ORDER BY created_at DESC LIMIT 15",
    "project": "SELECT id, name FROM projects WHERE status != 'archived' ORDER BY updated_at DESC LIMIT 15",
    "goal": "SELECT id, title FROM goals WHERE status != 'completed' ORDER BY created_at DESC LIMIT 15",
    "event": "SELECT id, title FROM events ORDER BY date DESC LIMIT 10",
}


class ItemPicker(FadeDialog):
    """Search and pick one record of the given kinds."""

    def __init__(self, ctx, kinds: list[str], parent: QWidget | None = None, title: str = "Link an item",
                 exclude: set[tuple[str, int]] | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.kinds = kinds
        self.exclude = exclude or set()
        self.choice: SearchHit | None = None
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(480, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(label(title, "section"))
        self.search = SearchField("Search " + ", ".join(KIND_LABELS.get(k, k).lower() + "s" for k in kinds))
        lay.addWidget(self.search)
        self.results = QListWidget()
        self.results.setAccessibleName("Results")
        self.results.itemActivated.connect(self._pick)
        self.results.itemDoubleClicked.connect(self._pick)
        lay.addWidget(self.results, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", "ghost", on_click=self.reject))
        self.ok = button("Link", "primary", on_click=lambda: self._pick(self.results.currentItem()))
        row.addWidget(self.ok)
        lay.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._fill)
        self.search.textChanged.connect(lambda _: self._timer.start())
        self.search.returnPressed.connect(lambda: self._pick(self.results.currentItem()))
        self._fill()
        self.search.setFocus()

    def _hits(self) -> list[SearchHit]:
        text = self.search.text().strip()
        if text:
            return self.ctx.search.search(text, set(self.kinds), limit=40)
        hits = []
        for kind in self.kinds:
            sql = _RECENT_SQL.get(kind)
            if sql:
                hits.extend(SearchHit(kind, int(r[0]), str(r[1] or "Untitled")) for r in self.ctx.db.query(sql))
        return hits

    def _fill(self) -> None:
        self.results.clear()
        for hit in self._hits():
            if (hit.kind, hit.ref_id) in self.exclude:
                continue
            item = QListWidgetItem(icon(KIND_ICONS.get(hit.kind, "info"), "text2", 16),
                                   f"{hit.title}   ·  {hit.label}")
            item.setData(Qt.ItemDataRole.UserRole, hit)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)
        self.ok.setEnabled(self.results.count() > 0)

    def _pick(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        self.choice = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


class LinksPanel(QWidget):
    """Shows what a record is linked to, with add/remove. Works before the record exists:
    pending links are applied by :meth:`apply` once it has been saved."""

    def __init__(self, ctx, kind: str, ref_id: int | None, kinds: list[str], allow_files: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.kind = kind
        self.ref_id = ref_id
        self.kinds = kinds
        self.pending: list[tuple[str, int, str]] = []  # (kind, id, title)
        self.pending_files: list[str] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.items = QVBoxLayout()
        self.items.setSpacing(2)
        lay.addLayout(self.items)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(button("Link item…", "link", "link", self._add))
        if allow_files:
            row.addWidget(button("Reference a file…", "link", "folder", self._add_file))
        row.addStretch(1)
        lay.addLayout(row)
        self._fill()

    def _fill(self) -> None:
        clear_layout(self.items)
        entries: list[tuple[str, str, object]] = []
        if self.ref_id is not None:
            for link in self.ctx.links.links_for(self.kind, self.ref_id):
                entries.append((link.kind, link.title, link))
        for kind, ref, title in self.pending:
            entries.append((kind, title, (kind, ref)))
        for path in self.pending_files:
            entries.append(("file", Path(path).name, path))
        if not entries:
            self.items.addWidget(label("Nothing linked yet.", "caption"))
        for kind, title, token in entries:
            row = QHBoxLayout()
            row.setSpacing(6)
            ic = label("", "caption")
            ic.setPixmap(icon(KIND_ICONS.get(kind, "info"), "text2", 14).pixmap(14, 14))
            row.addWidget(ic)
            text = label(f"{title}  ·  {KIND_LABELS.get(kind, kind)}", "", wrap=True)
            row.addWidget(text, 1)
            if kind == "file" and not isinstance(token, str):
                row.addWidget(tool_button("external", "Open file", lambda t=token: self._open_file(t), 14))
            row.addWidget(tool_button("close", "Remove link", lambda t=token: self._remove(t), 14))
            self.items.addLayout(row)

    def _add(self) -> None:
        exclude = {(self.kind, self.ref_id)} if self.ref_id is not None else set()
        picker = ItemPicker(self.ctx, self.kinds, self, "Link an item", exclude)
        if not picker.exec() or picker.choice is None:
            return
        hit = picker.choice
        if self.ref_id is None:
            self.pending.append((hit.kind, hit.ref_id, hit.title))
        else:
            try:
                self.ctx.links.link(self.kind, self.ref_id, hit.kind, hit.ref_id)
            except Exception as exc:  # validation errors are shown, never crash the dialog
                show_error(self, "Couldn't link", str(exc))
        self._fill()

    def _add_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a file to reference")
        if not path:
            return
        if self.ref_id is None:
            self.pending_files.append(path)
        else:
            self.ctx.links.attach_file(self.kind, self.ref_id, path)
        self._fill()

    def _open_file(self, link) -> None:
        path = self.ctx.links.file_path(link.ref_id)
        if not path or not os.path.exists(path):
            show_error(self, "File not found", "The referenced file was moved or deleted.", path or "")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _remove(self, token) -> None:
        if isinstance(token, str):
            self.pending_files.remove(token)
        elif isinstance(token, tuple):
            self.pending = [p for p in self.pending if (p[0], p[1]) != token]
        else:
            self.ctx.links.unlink(token.link_id)
        self._fill()

    def apply(self, ref_id: int) -> None:
        """Create pending links for a record that has just been saved."""
        for kind, other, _title in self.pending:
            self.ctx.links.link(self.kind, ref_id, kind, other)
        for path in self.pending_files:
            self.ctx.links.attach_file(self.kind, ref_id, path)
        self.pending.clear()
        self.pending_files.clear()
        self.ref_id = ref_id
