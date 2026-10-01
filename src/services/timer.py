"""Focus/break timer engine independent of Qt.

Elapsed time is always computed from a monotonic clock
(``accumulated + (now - running_since)``), never by counting ticks, so the
display stays correct if the window is minimized or the UI thread is busy.

On Windows the monotonic clock keeps counting while the computer sleeps, so
the UI pauses the timer at the last tick when it notices a long gap between
ticks (see :data:`SLEEP_GAP_SECONDS`) instead of counting sleep as study time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from src.services.dates import now

FOCUS, SHORT_BREAK, LONG_BREAK = "focus", "short_break", "long_break"
MODES = (FOCUS, SHORT_BREAK, LONG_BREAK)
SLEEP_GAP_SECONDS = 60.0


@dataclass
class FocusTimer:
    clock: Callable[[], float] = time.monotonic
    mode: str = FOCUS
    duration_s: int = 25 * 60
    accumulated: float = 0.0
    running_since: float | None = None
    started_wall: datetime | None = None
    session_uid: str | None = None
    subject_id: int | None = None
    finished: bool = False
    active: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    # -- state --------------------------------------------------------------
    @property
    def state(self) -> str:
        if self.finished:
            return "finished"
        if self.running_since is not None:
            return "running"
        if self.active:
            return "paused"
        return "idle"

    @property
    def is_active(self) -> bool:
        """True while a session is running or paused (i.e. there is time to save)."""
        return self.state in ("running", "paused")

    def elapsed(self) -> float:
        running = self.clock() - self.running_since if self.running_since is not None else 0.0
        return min(float(self.duration_s), self.accumulated + running)

    def remaining(self) -> float:
        return max(0.0, self.duration_s - self.elapsed())

    def check_finished(self) -> bool:
        """Mark the timer finished if its time is up. Returns True on the transition."""
        if not self.finished and self.running_since is not None and self.remaining() <= 0:
            self.accumulated = float(self.duration_s)
            self.running_since = None
            self.finished = True
            self.active = False
            return True
        return False

    # -- controls -------------------------------------------------------------
    def start(self, duration_s: int, mode: str = FOCUS, session_uid: str | None = None, subject_id: int | None = None) -> None:
        if mode not in MODES:
            raise ValueError(mode)
        if duration_s <= 0:
            raise ValueError("duration must be positive")
        self.mode = mode
        self.duration_s = int(duration_s)
        self.accumulated = 0.0
        self.finished = False
        self.session_uid = session_uid
        self.subject_id = subject_id
        self.started_wall = now()
        self.active = True
        self.running_since = self.clock()

    def pause(self) -> None:
        if self.running_since is not None:
            self.accumulated = self.elapsed()
            self.running_since = None

    def pause_at(self, moment: float) -> None:
        """Pause as if at an earlier clock reading (used after system sleep)."""
        if self.running_since is not None:
            gained = max(0.0, moment - self.running_since)
            self.accumulated = min(float(self.duration_s), self.accumulated + gained)
            self.running_since = None

    def resume(self) -> None:
        if self.running_since is None and not self.finished and self.accumulated < self.duration_s:
            self.running_since = self.clock()

    def reset(self) -> None:
        self.accumulated = 0.0
        self.running_since = None
        self.finished = False
        self.active = False
        self.session_uid = None
        self.started_wall = None

    # -- persistence ----------------------------------------------------------
    def checkpoint(self) -> dict[str, Any] | None:
        """Serializable snapshot for crash recovery (only for focus sessions)."""
        if self.mode != FOCUS or not self.is_active or not self.session_uid:
            return None
        return {
            "session_uid": self.session_uid,
            "subject_id": self.subject_id,
            "duration_s": self.duration_s,
            "elapsed_s": round(self.elapsed(), 1),
            "started_wall": self.started_wall.replace(microsecond=0).isoformat() if self.started_wall else None,
            "saved_at": now().replace(microsecond=0).isoformat(),
            "extra": dict(self.extra),
        }
