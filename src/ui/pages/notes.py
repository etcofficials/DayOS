from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from src.models import Note
from src.services.dates import format_date
from src.ui.bus import bus
from src.ui.pages.base import Page
from src.ui.widgets.common import (
    fit_list_items,
    EmptyState,
    PageHeader,
    SearchField,
    button,
    confirm,
    guarded,
    install_shortcut,
    label,
    tool_button,
)

log = logging.getLogger(__name__)

AUTOSAVE_MS = 900


def _snippet(note: Note) -> str:
    text = " ".join(note.content.split())
    return text[:90] + ("…" if len(text) > 90 else "")


class NoteItem(QWidget):
    def __init__(self, note: Note, date_style: str) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(3)
        top = QHBoxLayout()
        self.title = label(note.title or "Untitled")
        self.title.setStyleSheet("font-weight: 600;")
        top.addWidget(self.title, 1)
        if note.pinned:
            top.addWidget(label("Pinned", "caption"))
        lay.addLayout(top)
        self.snippet = label(_snippet(note) or "No content yet", "muted")
        self.snippet.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.snippet)
        meta = format_date(date.fromisoformat(note.updated_at[:10]), date_style)
        if note.tags:
            meta += " · " + note.tags
        self.meta = label(meta, "caption")
        lay.addWidget(self.meta)


class NotesPage(Page):
    domains = ("notes", "settings")
    title = "Notes"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.current: Note | None = None
        self._loading = False
        self._dirty_edit = False
        self._own_notify = False
        self._fresh_empty_ids: set[int] = set()

        header = PageHeader("Notes", "Plain-text notes that save themselves as you type.", eyebrow="Quiet thoughts")
        header.add_action(button("New note", "primary", "plus", self.new_item, "New note (Ctrl+N)"))
        self.root.addWidget(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(14)
        self.root.addWidget(split, 1)

        # -- list pane
        left = QFrame()
        left.setProperty("panel", True)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)
        self.search = SearchField("Search notes")
        self.search.textChanged.connect(lambda _: self._reload_list())
        ll.addWidget(self.search)
        self.tag_filter = QComboBox()
        self.tag_filter.setAccessibleName("Filter by tag")
        self.tag_filter.currentIndexChanged.connect(lambda _: self._reload_list())
        ll.addWidget(self.tag_filter)
        self.list = QListWidget()
        self.list.setAccessibleName("Notes")
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list, 1)
        self.count_label = label("", "caption")
        ll.addWidget(self.count_label)
        left.setMinimumWidth(240)
        split.addWidget(left)

        # -- editor pane
        right = QFrame()
        right.setProperty("panel", True)
        self.right_stack = QStackedLayout(right)
        editor = QWidget()
        el = QVBoxLayout(editor)
        el.setContentsMargins(22, 16, 22, 14)
        el.setSpacing(6)
        tools = QHBoxLayout()
        self.status = label("", "caption")
        self.status.setAccessibleName("Save status")
        tools.addWidget(self.status, 1)
        self.pin_btn = tool_button("pin", "Pin note", self._toggle_pin)
        self.pin_btn.setCheckable(True)
        tools.addWidget(self.pin_btn)
        tools.addWidget(tool_button("trash", "Delete note", self._delete))
        el.addLayout(tools)
        self.title_edit = QLineEdit()
        self.title_edit.setProperty("flat", True)
        self.title_edit.setProperty("titleEdit", True)
        self.title_edit.setPlaceholderText("Title")
        self.title_edit.setAccessibleName("Note title")
        self.title_edit.setMaxLength(200)
        el.addWidget(self.title_edit)
        self.tags_edit = QLineEdit()
        self.tags_edit.setProperty("flat", True)
        self.tags_edit.setPlaceholderText("Add tags, separated by commas")
        self.tags_edit.setAccessibleName("Note tags")
        el.addWidget(self.tags_edit)
        self.editor = QPlainTextEdit()
        self.editor.setProperty("editor", True)
        self.editor.setPlaceholderText("Start writing…")
        self.editor.setAccessibleName("Note content")
        self.editor.setTabChangesFocus(False)
        el.addWidget(self.editor, 1)
        self.meta = label("", "caption")
        el.addWidget(self.meta)
        self.right_stack.addWidget(editor)
        self.placeholder = QWidget()
        pl = QVBoxLayout(self.placeholder)
        pl.addWidget(EmptyState("notes", "No note selected", "Choose a note on the left or start a new one.",
                                [("New note", self.new_item)]))
        self.right_stack.addWidget(self.placeholder)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 700])

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTOSAVE_MS)
        self._timer.timeout.connect(self.save_now)
        for w in (self.title_edit, self.tags_edit):
            w.textEdited.connect(self._changed)
        self.editor.textChanged.connect(self._changed)
        install_shortcut(self, "Ctrl+S", self._manual_save)
        self._show_editor(False)

    # -- list -----------------------------------------------------------------
    def _on_data_changed(self, domain: str) -> None:
        if self._own_notify:
            return
        super()._on_data_changed(domain)

    def refresh(self) -> None:
        tags = self.ctx.notes.all_tags()
        current_tag = self.tag_filter.currentData()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem("All tags", "")
        for tag in tags:
            self.tag_filter.addItem(f"#{tag}", tag)
        index = self.tag_filter.findData(current_tag)
        self.tag_filter.setCurrentIndex(max(0, index))
        self.tag_filter.blockSignals(False)
        self.tag_filter.setVisible(bool(tags))
        self._reload_list()

    def _reload_list(self) -> None:
        self.save_now()
        notes = self.ctx.notes.list(self.search.text(), self.tag_filter.currentData() or "")
        keep = self.current.id if self.current else None
        self.list.blockSignals(True)
        self.list.clear()
        selected_item = None
        for note in notes:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            widget = NoteItem(note, self.date_style)
            item.setSizeHint(QSize(100, widget.sizeHint().height()))
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)
            if note.id == keep:
                selected_item = item
        if selected_item:
            self.list.setCurrentItem(selected_item)
        self.list.blockSignals(False)
        fit_list_items(self.list)
        if self.current is None and self.list.count() and not self.search.text().strip():
            self.list.setCurrentRow(0)
        total = self.ctx.notes.count()
        filtered = self.search.text().strip() or self.tag_filter.currentData()
        self.count_label.setText(
            f"{len(notes)} of {total} notes" if filtered else f"{total} note{'s' if total != 1 else ''}"
        )
        if self.current and not any(n.id == self.current.id for n in notes):
            # Current note filtered out (or deleted elsewhere): keep editing only if it still exists.
            still = self.ctx.notes.get(self.current.id)
            if still is None:
                self._open(None)

    def _on_select(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        note_id = int(current.data(Qt.ItemDataRole.UserRole))
        if self.current and note_id == self.current.id:
            return
        self._open(self.ctx.notes.get(note_id))

    # -- editor -----------------------------------------------------------------
    def _show_editor(self, on: bool) -> None:
        self.right_stack.setCurrentIndex(0 if on else 1)

    def _open(self, note: Note | None) -> None:
        self.save_now()
        self._discard_if_empty()
        self.current = note
        self._loading = True
        if note is None:
            self._show_editor(False)
        else:
            self.title_edit.setText(note.title)
            self.tags_edit.setText(note.tags)
            self.editor.setPlainText(note.content)
            self.pin_btn.setChecked(bool(note.pinned))
            self.pin_btn.setToolTip("Unpin note" if note.pinned else "Pin note")
            self._set_status("Saved")
            self._update_meta()
            self._show_editor(True)
        self._loading = False
        self._dirty_edit = False

    def _update_meta(self) -> None:
        if not self.current:
            return
        words = len(self.editor.toPlainText().split())
        self.meta.setText(
            f"Created {self.current.created_at[:16]} · Updated {self.current.updated_at[:16]} · {words} words"
        )

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _changed(self, *_args) -> None:
        if self._loading or self.current is None:
            return
        self._dirty_edit = True
        self._set_status("Unsaved changes…")
        self._timer.start()

    def save_now(self) -> bool:
        """Write pending edits. Returns False if saving failed."""
        self._timer.stop()
        if not self._dirty_edit or self.current is None:
            return True
        self._set_status("Saving…")
        note_id = self.current.id
        try:
            stamp = self.ctx.notes.save(note_id, self.title_edit.text(), self.editor.toPlainText(), self.tags_edit.text())
        except Exception as exc:
            log.exception("Autosave failed")
            self._set_status(f"Not saved — {exc}")
            return False
        self._dirty_edit = False
        if self.title_edit.text().strip() or self.editor.toPlainText().strip():
            self._fresh_empty_ids.discard(note_id)
        self.current.title = self.title_edit.text().strip()
        self.current.content = self.editor.toPlainText()
        self.current.updated_at = stamp
        self._set_status("Saved")
        self._update_meta()
        self._update_current_item()
        self._own_notify = True
        try:
            bus.notify("notes")
        finally:
            self._own_notify = False
        return True

    def _update_current_item(self) -> None:
        if not self.current:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if int(item.data(Qt.ItemDataRole.UserRole)) == self.current.id:
                widget = self.list.itemWidget(item)
                if isinstance(widget, NoteItem):
                    widget.title.setText(self.current.title or "Untitled")
                    widget.snippet.setText(_snippet(self.current) or "No content yet")
                return

    def _manual_save(self) -> None:
        if self.current is not None:
            self._dirty_edit = True
            if self.save_now():
                self.toast("Note saved")

    def _discard_if_empty(self) -> None:
        """Remove a brand-new note that was left completely empty."""
        if self.current and self.current.id in self._fresh_empty_ids:
            note = self.ctx.notes.get(self.current.id)
            if note and not note.title.strip() and not note.content.strip() and not note.tags.strip():
                self.ctx.notes.delete(note.id)
            self._fresh_empty_ids.discard(self.current.id)

    # -- actions ----------------------------------------------------------------
    def new_item(self) -> None:
        self.save_now()
        self._discard_if_empty()
        self.search.clear()
        self.tag_filter.setCurrentIndex(0)
        note_id = self.ctx.notes.create()
        self._fresh_empty_ids.add(note_id)
        self.current = None
        self._open(self.ctx.notes.get(note_id))
        self._reload_list()
        self.title_edit.setFocus()

    def _toggle_pin(self) -> None:
        if not self.current:
            return
        pinned = self.pin_btn.isChecked()
        if guarded(self, lambda: self.ctx.notes.set_pinned(self.current.id, pinned)):
            self.current.pinned = int(pinned)
            self.pin_btn.setToolTip("Unpin note" if pinned else "Pin note")
            self._reload_list()

    def _delete(self) -> None:
        if not self.current:
            return
        name = self.title_edit.text().strip() or "Untitled note"
        if not confirm(self, "Delete note?", f"“{name}” will be permanently deleted."):
            return
        note_id = self.current.id
        self._dirty_edit = False
        self._fresh_empty_ids.discard(note_id)
        if guarded(self, lambda: self.ctx.notes.delete(note_id)):
            self.current = None
            self._open(None)
            self.refresh()
            self.toast("Note deleted")

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def can_leave(self) -> bool:
        ok = self.save_now()
        if ok:
            self._discard_if_empty()
        return ok or confirm(self, "Note not saved",
                             "Your latest changes couldn't be saved. Leave anyway and lose them?",
                             "Leave without saving")

    def hideEvent(self, event) -> None:  # noqa: N802
        self.save_now()
        super().hideEvent(event)
