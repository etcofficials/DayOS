"""The quick picker: search what you copied, press Enter to copy it back.

Shift+Enter also pastes it into the window you were using before the picker
opened (one Ctrl+V, sent only on that explicit request).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from src.modules.clipvault import win32
from src.modules.clipvault.schema import CLIP_KINDS
from src.ui.widgets.common import FadeDialog, button, label

PREVIEW_CHARS = 140


def preview_line(text: str) -> str:
    flat = " ".join(text.split())
    return flat[:PREVIEW_CHARS] + ("…" if len(flat) > PREVIEW_CHARS else "")


class ClipPicker(FadeDialog):
    _instance: "ClipPicker | None" = None

    @classmethod
    def open(cls, window, previous_hwnd: int = 0) -> "ClipPicker":
        if cls._instance is not None and cls._instance.isVisible():
            cls._instance.raise_()
            cls._instance.activateWindow()
            return cls._instance
        dlg = cls(window, previous_hwnd, standalone=not window.isActiveWindow())
        cls._instance = dlg
        dlg.finished.connect(lambda _r: setattr(cls, "_instance", None))
        dlg.show()
        return dlg

    def __init__(self, window, previous_hwnd: int = 0, standalone: bool = False) -> None:
        super().__init__(None if standalone else window)
        self.main = window
        self.ctx = window.ctx
        self.repo = self.ctx.services["clipvault"]
        self.monitor = window.clip_monitor
        self.previous_hwnd = previous_hwnd
        self.setWindowTitle("Clipboard history — DayOS")
        self.setWindowIcon(window.windowIcon())
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(560, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(8)
        lay.addWidget(label("Clipboard history", "section"))
        self.state = label("", "caption", wrap=True)
        lay.addWidget(self.state)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search what you copied, snippets and templates")
        self.search.setAccessibleName("Search clipboard history")
        self.search.textChanged.connect(lambda _t: self.fill())
        self.search.installEventFilter(self)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setAccessibleName("Clipboard entries")
        self.list.itemActivated.connect(lambda _i: self.copy_selected())
        self.list.installEventFilter(self)
        lay.addWidget(self.list, 1)
        hints = "Enter: copy"
        if previous_hwnd:
            hints += " · Shift+Enter: copy and paste into the app you were using"
        hints += " · Ctrl+P: pin · Esc: close"
        lay.addWidget(label(hints, "caption", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Open ClipVault", "link", "clipboard", self._open_page))
        row.addStretch(1)
        row.addWidget(button("Close", "ghost", on_click=self.reject))
        lay.addLayout(row)
        self.fill()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def fill(self) -> None:
        if not self.monitor.enabled:
            self.state.setText("Clipboard history is off — showing your saved snippets and templates.")
        elif self.monitor.paused:
            self.state.setText("Clipboard history is paused. Nothing new is being saved.")
        else:
            self.state.setText("")
        self.state.setVisible(bool(self.state.text()))
        self.list.clear()
        for entry in self.repo.list(self.search.text(), limit=80):
            marks = ("Pinned · " if entry.pinned else "") + ("★ " if entry.favorite else "")
            title = entry.title or preview_line(entry.content)
            item = QListWidgetItem(f"{marks}{title}")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            kind = CLIP_KINDS.get(entry.kind, entry.kind)
            item.setToolTip(f"{kind}" + (f" · from {entry.source_app}" if entry.source_app else ""))
            item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{kind}: {title}")
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.copy_selected(paste=bool(mods & Qt.KeyboardModifier.ShiftModifier))
                return True
            if key == Qt.Key.Key_P and mods & Qt.KeyboardModifier.ControlModifier:
                self._toggle_pin()
                return True
            if obj is self.search and key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown,
                                              Qt.Key.Key_PageUp):
                row = self.list.currentRow()
                step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_PageDown: 8, Qt.Key.Key_PageUp: -8}[key]
                if self.list.count():
                    self.list.setCurrentRow(max(0, min(self.list.count() - 1, row + step)))
                return True
        return super().eventFilter(obj, event)

    def _current_id(self) -> int | None:
        item = self.list.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def copy_selected(self, paste: bool = False) -> None:
        entry_id = self._current_id()
        if entry_id is None:
            return
        if self.monitor.copy_entry(entry_id) is None:
            self.fill()
            return
        hwnd = self.previous_hwnd if paste else 0
        self.accept()
        if hwnd:
            QTimer.singleShot(250, lambda: win32.paste_into(hwnd))
        else:
            self.main.toast.show_message("Copied — paste it anywhere")

    def _toggle_pin(self) -> None:
        entry_id = self._current_id()
        entry = self.repo.get(entry_id) if entry_id else None
        if entry is None:
            return
        self.repo.set_flag(entry.id, "pinned", not entry.pinned)
        self.fill()

    def _open_page(self) -> None:
        self.accept()
        self.main.show_and_raise()
        self.main.navigate("clipvault")
