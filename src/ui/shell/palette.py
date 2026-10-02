"""The command palette (Ctrl+K): run any command or jump to anything you've recorded."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.services.search import KIND_ICONS, SearchHit
from src.ui import anim
from src.ui.icons import pixmap
from src.ui.shell.commands import Command
from src.ui.theme import theme
from src.ui.widgets.common import FadeDialog, fit_list_items, label, paint_card


class _Row(QWidget):
    def __init__(self, icon_name: str, title: str, detail: str, right: str) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 1, 12, 1)  # the list item's own padding adds the rest
        lay.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(pixmap(icon_name, theme.tokens["text2"], 18))
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(title)
        t.setProperty("role", "heading")
        col.addWidget(t)
        if detail:
            d = label(detail, "caption")
            col.addWidget(d)
        lay.addLayout(col, 1)
        if right:
            lay.addWidget(label(right, "caption"))


class CommandPalette(FadeDialog):
    """Frameless, keyboard-first launcher. Up/Down to move, Enter to run, Esc to close."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window_ = window
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setAccessibleName("Command palette")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 18)
        self.frame = QFrame()
        self.frame.setObjectName("PaletteFrame")
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(14, 10, 14, 12)
        fl.setSpacing(6)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(pixmap("search", theme.tokens["text3"], 20))
        top.addWidget(icon)
        self.edit = QLineEdit()
        self.edit.setProperty("palette", True)
        self.edit.setPlaceholderText("Type a command or search tasks, notes, projects, courses…")
        self.edit.setAccessibleName("Search or run a command")
        top.addWidget(self.edit, 1)
        top.addWidget(label("Esc to close", "caption"))
        fl.addLayout(top)
        self.list = QListWidget()
        self.list.setAccessibleName("Results")
        self.list.setMinimumHeight(360)
        self.list.itemActivated.connect(self._run_item)
        self.list.itemClicked.connect(self._run_item)
        fl.addWidget(self.list, 1)
        self.hint = label("Enter to run · ↑↓ to move · Searching never leaves this computer.", "caption")
        fl.addWidget(self.hint)
        outer.addWidget(self.frame)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._fill)
        self.edit.textChanged.connect(lambda _: self._timer.start())
        self.edit.installEventFilter(self)
        self.resize(640, 500)
        self._fill()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.frame.geometry()
        from PySide6.QtCore import QRectF

        paint_card(p, QRectF(r), 1.0, theme.shape.card_radius)
        p.end()

    def showEvent(self, event) -> None:  # noqa: N802
        parent = self.window_
        geo = parent.geometry()
        self.move(geo.x() + (geo.width() - self.width()) // 2, geo.y() + max(40, geo.height() // 7))
        super().showEvent(event)
        self.edit.setFocus()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.edit and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                step = 1 if key == Qt.Key.Key_Down else -1
                row = self.list.currentRow()
                for _ in range(self.list.count()):
                    row = (row + step) % max(1, self.list.count())
                    item = self.list.item(row)
                    if item is not None and item.flags() & Qt.ItemFlag.ItemIsSelectable:
                        self.list.setCurrentRow(row)
                        break
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run_item(self.list.currentItem())
                return True
        return super().eventFilter(obj, event)

    def _header(self, text: str) -> None:
        item = QListWidgetItem(text.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setSizeHint(QSize(10, 26))
        self.list.addItem(item)

    def _add(self, payload, icon_name: str, title: str, detail: str, right: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, payload)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{title}. {detail}")
        row = _Row(icon_name, title, detail, right)
        item.setSizeHint(QSize(10, max(44, row.sizeHint().height())))
        self.list.addItem(item)
        self.list.setItemWidget(item, row)

    def _fill(self) -> None:
        text = self.edit.text()
        self.list.clear()
        commands = self.window_.commands.match(text, limit=8 if text.strip() else 14)
        hits: list[SearchHit] = []
        if len(text.strip()) >= 2:
            hits = self.window_.ctx.search.search(text, limit=12)
            hits = [h for h in hits if self.window_.openers.can_open(h.kind)]
        if hits:
            self._header("Your records")
            for hit in hits:
                snippet = hit.snippet if hit.snippet and hit.snippet.lower() != hit.title.lower() else ""
                self._add(hit, KIND_ICONS.get(hit.kind, "info"), hit.title, snippet[:90], hit.label)
        if commands:
            self._header("Commands")
            for cmd in commands:
                self._add(cmd, cmd.icon, cmd.title, cmd.description, cmd.shortcut)
        if not commands and not hits:
            self._header("No results" if text.strip() else "")
        fit_list_items(self.list)  # rows measured once styled, plus the item padding
        for i in range(self.list.count()):
            if self.list.item(i).flags() & Qt.ItemFlag.ItemIsSelectable:
                self.list.setCurrentRow(i)
                break

    def _run_item(self, item: QListWidgetItem | None) -> None:
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsSelectable:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

        def go() -> None:
            if isinstance(payload, Command):
                payload.run()
            elif isinstance(payload, SearchHit):
                self.window_.openers.open(payload.kind, payload.ref_id)

        QTimer.singleShot(0 if not anim.motion_enabled() else 130, go)
