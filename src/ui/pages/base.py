from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.context import AppContext
from src.ui.bus import bus

if TYPE_CHECKING:
    from src.ui.main_window import MainWindow


PAGE_MARGIN = 34
PAGE_MARGIN_NARROW = 20
NARROW_PAGE_WIDTH = 960


class Page(QWidget):
    """Base for sidebar pages.

    Pages refresh when data in one of their ``domains`` changes: right away if
    visible, otherwise the next time they are shown (no background polling).
    """

    domains: tuple[str, ...] = ()
    title = ""

    def __init__(self, ctx: AppContext, window: "MainWindow") -> None:
        super().__init__()
        self.ctx = ctx
        self.main = window
        self.setObjectName("Page")
        self._dirty = True
        self._pending = QTimer(self)
        self._pending.setSingleShot(True)
        self._pending.setInterval(0)
        self._pending.timeout.connect(self._run_refresh)
        bus.changed.connect(self._on_data_changed)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(PAGE_MARGIN, 28, PAGE_MARGIN, 24)
        self.root.setSpacing(18)

    # -- refresh plumbing -------------------------------------------------
    def _on_data_changed(self, domain: str) -> None:
        if domain == "all" or domain in self.domains:
            if self.isVisible():
                self._pending.start()
            else:
                self._dirty = True

    def _run_refresh(self) -> None:
        self._dirty = False
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            self._run_refresh()

    def mark_dirty(self) -> None:
        self._dirty = True

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Narrow windows get slimmer side margins, leaving more room for the content itself.
        # Pages that set their own margins (0, edge to edge) keep them.
        m = self.root.contentsMargins()
        side = PAGE_MARGIN_NARROW if self.width() < NARROW_PAGE_WIDTH else PAGE_MARGIN
        if m.left() in (PAGE_MARGIN, PAGE_MARGIN_NARROW) and m.left() != side:
            self.root.setContentsMargins(side, m.top(), side, m.bottom())

    # -- hooks ------------------------------------------------------------
    def refresh(self) -> None:
        """Reload visible data from the database."""

    def new_item(self) -> None:
        """Ctrl+N on this page."""

    def focus_search(self) -> None:
        """Ctrl+F on this page."""

    def can_leave(self) -> bool:
        """Called before navigating away or closing; flush unsaved work here."""
        return True

    # -- conveniences -----------------------------------------------------
    def toast(self, text: str, action: str | None = None, callback=None) -> None:
        self.main.toast.show_message(text, action, callback)

    @property
    def clock24(self) -> bool:
        return bool(self.ctx.settings.get("clock_24h"))

    @property
    def date_style(self) -> str:
        return str(self.ctx.settings.get("date_format"))

    @property
    def week_start(self) -> int:
        return int(self.ctx.settings.get("week_start"))
