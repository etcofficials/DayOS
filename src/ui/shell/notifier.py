"""Delivers reminders: a badge in the sidebar, a notification centre, and optional Windows pop-ups.

One single-shot timer sleeps until the next reminder is due (re-checked at most
every 30 minutes, and whenever relevant data changes); nothing polls in a tight
loop. Quiet hours suppress pop-ups and in-app toasts only, never the centre.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QSystemTrayIcon, QVBoxLayout, QWidget

from src.services.dates import format_time, now
from src.services.notifications import CATEGORIES, Notice
from src.ui.bus import bus
from src.ui.widgets.common import button, clear_layout, label, paint_card, scroll_wrap, separator

log = logging.getLogger(__name__)
MAX_SLEEP_MS = 30 * 60 * 1000


class Notifier(QObject):
    changed = Signal(int)  # number of due notices

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.ctx = window.ctx
        self._tray: QSystemTrayIcon | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.check)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self.check)
        bus.changed.connect(self._on_data)
        self.due: list[Notice] = []
        try:
            self.ctx.reminders.prune_state(now() - timedelta(days=30))
        except Exception:
            log.warning("Could not prune notification state", exc_info=True)

    def start(self) -> None:
        self._stopped = False
        self._timer.start(1500)

    def stop(self) -> None:
        """Called when the window closes: no more checks against the database."""
        self._stopped = True
        self._timer.stop()
        self._debounce.stop()
        try:
            bus.changed.disconnect(self._on_data)
        except (RuntimeError, TypeError):
            pass

    def _on_data(self, domain: str) -> None:
        if domain in ("reminders", "schedule", "habits", "settings", "tasks", "money", "all"):
            self._debounce.start()

    def check(self) -> None:
        if getattr(self, "_stopped", False):
            return
        at = now()
        try:
            self.due = self.ctx.notifications.due(at)
            fresh = [n for n in self.due if not self.ctx.notifications.was_notified(n)]
        except Exception:
            log.exception("Checking reminders failed")
            self.due, fresh = [], []
        if fresh:
            quiet = self.ctx.notifications.quiet_now(at)
            if not quiet:
                self._announce(fresh)
            for notice in fresh:
                self.ctx.notifications.mark_notified(notice)
        self.changed.emit(len(self.due))
        self._schedule(at)

    def _schedule(self, at: datetime) -> None:
        try:
            nxt = self.ctx.notifications.next_wakeup(at)
        except Exception:
            nxt = None
        delay = MAX_SLEEP_MS if nxt is None else int((nxt - at).total_seconds() * 1000) + 500
        self._timer.start(max(2000, min(MAX_SLEEP_MS, delay)))

    def _announce(self, notices: list[Notice]) -> None:
        if len(notices) == 1:
            title, body = notices[0].title, notices[0].body
        else:
            title = f"{len(notices)} reminders"
            body = "; ".join(n.title for n in notices[:4])
        if self.window.isActiveWindow():
            n = notices[0]
            self.window.toast.show_message(f"⏰ {title}", "View", self.window.show_notifications, ms=8000)
        self.desktop(title, body, force=False)
        log.info("Delivered %d reminder(s)", len(notices))

    def desktop(self, title: str, message: str, force: bool = False) -> bool:
        """Show a Windows notification if the user allowed them. Returns True if shown."""
        if not (force or self.ctx.settings.get("notify_desktop")) or not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        if self._tray is None:
            self._tray = QSystemTrayIcon(self.window.windowIcon(), self)
            self._tray.setToolTip("DayOS")
            self._tray.messageClicked.connect(self.window.show_and_raise)
        self._tray.show()
        self._tray.showMessage(title, message, self.window.windowIcon(), 8000)
        QTimer.singleShot(12000, lambda: self._tray.hide() if self._tray else None)
        return True


class NotificationCenter(QFrame):
    """Popup listing what's due now and later today, with snooze / dismiss / open."""

    def __init__(self, window) -> None:
        super().__init__(window, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.window = window
        self.ctx = window.ctx
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName("Notifications")
        self.setFixedWidth(420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(label("Notifications", "section"), 1)
        head.addWidget(button("Settings", "link", "settings", self._settings))
        outer.addLayout(head)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(6)
        area = scroll_wrap(self.content)
        area.setMinimumHeight(140)
        area.setMaximumHeight(460)
        outer.addWidget(area)
        self.fill()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_card(p, QRectF(self.rect()).adjusted(4, 3, -4, -6), 1.0)
        p.end()

    def popup(self, anchor: QWidget) -> None:
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(anchor.width() + 6, anchor.height() - self.sizeHint().height()))
        screen = anchor.screen().availableGeometry()
        pos.setY(max(screen.top() + 8, min(pos.y(), screen.bottom() - self.sizeHint().height() - 8)))
        pos.setX(min(pos.x(), screen.right() - self.width() - 8))
        self.move(pos)
        self.show()

    def fill(self) -> None:
        clear_layout(self.body)
        at = now()
        clock24 = bool(self.ctx.settings.get("clock_24h"))
        due = self.ctx.notifications.due(at)
        upcoming = self.ctx.notifications.upcoming(at, 18)
        overdue = self.ctx.notifications.overdue_tasks()
        if self.ctx.notifications.quiet_now(at):
            self.body.addWidget(label("Quiet hours are on: pop-ups are paused, but everything is listed here.",
                                      "caption", wrap=True))
        if due:
            self.body.addWidget(label("DUE NOW", "eyebrow"))
            for n in due:
                self.body.addWidget(self._row(n, at, clock24, actionable=True))
        if overdue:
            row = QHBoxLayout()
            row.addWidget(label(f"{overdue} open task{'s are' if overdue != 1 else ' is'} past the due date.",
                                "muted", wrap=True), 1)
            row.addWidget(button("Review", "link", on_click=self._overdue))
            self.body.addLayout(row)
        if upcoming:
            if due or overdue:
                self.body.addWidget(separator())
            self.body.addWidget(label("COMING UP", "eyebrow"))
            for n in upcoming[:10]:
                self.body.addWidget(self._row(n, at, clock24, actionable=False))
        if not (due or upcoming or overdue):
            self.body.addWidget(label("All quiet. Reminders you set on tasks, events and habits appear here.",
                                      "muted", wrap=True))
        self.body.addStretch(1)

    def _row(self, n: Notice, at: datetime, clock24: bool, actionable: bool) -> QWidget:
        w = QFrame()
        w.setProperty("inset", True)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 8, 10, 8)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.addWidget(label(n.title, "heading", wrap=True), 1)
        when = format_time(n.due.strftime("%H:%M"), clock24)
        if n.due.date() != at.date():
            when = n.due.strftime("%a ") + when
        top.addWidget(label(("Overdue · " if n.is_overdue(at) else "") + when, "caption"))
        lay.addLayout(top)
        lay.addWidget(label(f"{n.body} · {CATEGORIES.get(n.category, n.category)}", "caption", wrap=True))
        if actionable:
            row = QHBoxLayout()
            row.setSpacing(4)
            snooze = button("Snooze", "ghost", "clock")
            menu = QMenu(snooze)
            for text, minutes in (("10 minutes", 10), ("1 hour", 60), ("3 hours", 180)):
                menu.addAction(text, lambda m=minutes, nn=n: self._snooze(nn, m))
            menu.addAction("Tomorrow morning", lambda nn=n: self._snooze(nn, self._until_tomorrow()))
            snooze.setMenu(menu)
            row.addWidget(snooze)
            row.addWidget(button("Dismiss", "ghost", "check", lambda nn=n: self._dismiss(nn)))
            row.addStretch(1)
            if n.ref_kind and self.window.openers.can_open(n.ref_kind):
                row.addWidget(button("Open", "link", "chev-right", lambda nn=n: self._open(nn)))
            lay.addLayout(row)
        return w

    @staticmethod
    def _until_tomorrow() -> int:
        current = now()
        target = datetime.combine(current.date() + timedelta(days=1), time(8, 0))
        return max(1, int((target - current).total_seconds() // 60))

    def _snooze(self, n: Notice, minutes: int) -> None:
        self.ctx.notifications.snooze(n, minutes)
        bus.notify("reminders")
        self.fill()

    def _dismiss(self, n: Notice) -> None:
        self.ctx.notifications.dismiss(n)
        bus.notify("reminders")
        self.fill()

    def _open(self, n: Notice) -> None:
        self.hide()
        self.window.openers.open(n.ref_kind, n.ref_id)

    def _overdue(self) -> None:
        self.hide()
        page = self.window.page("tasks")
        page.filters.set_current("overdue")  # type: ignore[attr-defined]
        page.mark_dirty()
        self.window.navigate("tasks")

    def _settings(self) -> None:
        self.hide()
        self.window.navigate("settings")
        self.window.page("settings").show_section("focus")  # type: ignore[attr-defined]
