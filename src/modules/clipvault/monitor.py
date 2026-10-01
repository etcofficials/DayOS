"""Watches the clipboard while ClipVault is turned on and not paused.

The monitor listens to Qt's ``dataChanged`` signal only (no keyboard hooks).
While capture is off or paused it is disconnected entirely, so the clipboard
is not even read. Skipped copies are reported by reason only; clipboard text
is never logged.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from src.ui.bus import bus

from . import win32
from .privacy import PRIVATE_FORMATS, decide
from .repository import ClipRepository, content_hash, expand_template

log = logging.getLogger(__name__)

RETENTION_INTERVAL_MS = 30 * 60 * 1000
WATCHED = {"clip.enabled", "clip.paused", "clip.retention_days", "clip.max_items"}

Probe = Callable[[], tuple[set, str, bool]]  # (private formats present, owner exe, owner is DayOS)


def default_probe() -> tuple[set, str, bool]:
    if QGuiApplication.platformName() != "windows":
        return set(), "", False
    formats = win32.private_formats(PRIVATE_FORMATS)
    app, own = win32.owner_app()
    if not app:
        # Many apps copy without an owner window; the app in front is almost always the one copying.
        app, own = win32.foreground_app()
    return formats, app, own


class ClipMonitor(QObject):
    captured = Signal(int)
    skipped = Signal(str)
    state_changed = Signal()

    def __init__(self, ctx, repo: ClipRepository, probe: Probe | None = None) -> None:
        super().__init__()
        self.ctx = ctx
        self.repo = repo
        self.probe = probe or default_probe
        self.last_skip = ""
        self._ignore: str | None = None
        self._connected = False
        self._timer = QTimer(self)
        self._timer.setInterval(RETENTION_INTERVAL_MS)
        self._timer.timeout.connect(self.apply_retention)
        ctx.settings.subscribe(self._on_setting)
        self.sync()

    # -- state ----------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.ctx.settings.get("clip.enabled"))

    @property
    def paused(self) -> bool:
        return bool(self.ctx.settings.get("clip.paused"))

    @property
    def active(self) -> bool:
        return self.enabled and not self.paused

    def set_paused(self, paused: bool) -> None:
        self.ctx.settings.set("clip.paused", bool(paused))

    def _on_setting(self, key: str, _value) -> None:
        if key in WATCHED:
            self.sync()

    def sync(self) -> None:
        clipboard = QGuiApplication.clipboard()
        want = self.active and clipboard is not None
        if want and not self._connected:
            clipboard.dataChanged.connect(self._on_changed)
            self._connected = True
        elif not want and self._connected:
            try:
                clipboard.dataChanged.disconnect(self._on_changed)
            except (RuntimeError, TypeError):
                pass
            self._connected = False
        if self.enabled:
            self.apply_retention()
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.state_changed.emit()

    def stop(self) -> None:
        self._timer.stop()
        if self._connected:
            try:
                QGuiApplication.clipboard().dataChanged.disconnect(self._on_changed)
            except (RuntimeError, TypeError):
                pass
            self._connected = False
        self.ctx.settings.unsubscribe(self._on_setting)

    def apply_retention(self) -> int:
        try:
            removed = self.repo.enforce_retention(int(self.ctx.settings.get("clip.retention_days")),
                                                  int(self.ctx.settings.get("clip.max_items")))
        except Exception:
            log.warning("ClipVault retention clean-up failed", exc_info=True)
            return 0
        if removed:
            log.info("ClipVault retention removed %d old entr%s", removed, "y" if removed == 1 else "ies")
            bus.notify("clips")
        return removed

    # -- capture ----------------------------------------------------------------------
    def _on_changed(self) -> None:
        if not self.active:
            return
        try:
            self._capture()
        except Exception:
            log.warning("ClipVault could not store a clipboard change", exc_info=False)

    def _capture(self) -> None:
        settings = self.ctx.settings
        formats, app, own = self.probe()
        mime = QGuiApplication.clipboard().mimeData()
        if mime is None or not mime.hasText():
            return
        text = mime.text()
        if self._ignore is not None and content_hash(text) == self._ignore:
            self._ignore = None  # DayOS's own copy from the vault: already counted as a use
            return
        decision = decide(text, app, formats, self.repo.active_rules(),
                          max_chars=int(settings.get("clip.max_chars")),
                          skip_sensitive=bool(settings.get("clip.skip_sensitive")),
                          skip_private_apps=bool(settings.get("clip.skip_private_apps")))
        if not decision.keep:
            if decision.reason != "empty":
                self.last_skip = decision.reason
                log.info("Clipboard change not stored: %s", decision.reason)
                self.skipped.emit(decision.reason)
            return
        entry_id, created = self.repo.record(text, "DayOS" if own else app)
        if created:
            self.repo.enforce_retention(0, int(settings.get("clip.max_items")))
        bus.notify("clips")
        self.captured.emit(entry_id)

    # -- copying back -------------------------------------------------------------------
    def copy_entry(self, entry_id: int) -> str | None:
        """Put an entry on the clipboard (templates are filled in first). Returns the text."""
        entry = self.repo.get(entry_id)
        if entry is None:
            return None
        clipboard = QGuiApplication.clipboard()
        text = entry.content
        if entry.kind == "template":
            text = expand_template(text, clipboard=clipboard.text() if "{clipboard}" in text else "")
        self._ignore = content_hash(text) if self._connected else None
        clipboard.setText(text)
        self.repo.mark_used(entry_id)
        bus.notify("clips")
        return text
