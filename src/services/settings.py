"""User preferences stored in the ``settings`` table as JSON values.

Unknown or invalid stored values fall back to defaults (and are logged) so a
damaged setting can never stop DayOS from starting. Keys beginning with
``state.`` hold app state (e.g. an in-progress study timer) rather than
preferences; "Reset settings" leaves them alone and never touches user data.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from src.database import Database

log = logging.getLogger(__name__)


def _choice(*options: Any) -> Callable[[Any], bool]:
    return lambda v: v in options


def _bool(v: Any) -> bool:
    return isinstance(v, bool)


def _int_range(lo: int, hi: int) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _short_str(v: Any) -> bool:
    return isinstance(v, str) and len(v) <= 40


PREFERENCES: dict[str, tuple[Any, Callable[[Any], bool]]] = {
    "theme": ("light", _choice("system", "light", "dark")),
    "week_start": (0, _int_range(0, 6)),
    "clock_24h": (True, _bool),
    "date_format": ("dmy", _choice("dmy", "mdy", "iso")),
    "show_clock": (True, _bool),
    "user_name": ("", _short_str),
    "reduce_motion": (False, _bool),
    "sidebar_collapsed": (False, _bool),
    "notify_desktop": (False, _bool),
    "launch_at_login": (False, _bool),
    "study.focus_minutes": (25, _int_range(1, 240)),
    "study.short_break": (5, _int_range(1, 60)),
    "study.long_break": (15, _int_range(1, 120)),
    "calendar.show_tasks": (True, _bool),
}


class Settings:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._values: dict[str, Any] = {}
        self._listeners: list[Callable[[str, Any], None]] = []
        self.reload()

    def reload(self) -> None:
        self._values.clear()
        for row in self.db.query("SELECT key, value FROM settings"):
            try:
                self._values[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                log.warning("Ignoring unreadable setting %r", row["key"])

    def get(self, key: str) -> Any:
        if key in PREFERENCES:
            default, valid = PREFERENCES[key]
            value = self._values.get(key, default)
            if not valid(value):
                log.warning("Invalid value for setting %r; using default", key)
                return default
            return value
        return self._values.get(key)

    def set(self, key: str, value: Any) -> None:
        if key in PREFERENCES:
            _, valid = PREFERENCES[key]
            if not valid(value):
                raise ValueError(f"Invalid value for setting {key!r}: {value!r}")
        elif not key.startswith("state."):
            raise KeyError(f"Unknown setting {key!r}")
        with self.db.transaction():
            if value is None:
                self.db.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                self.db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value)),
                )
        if value is None:
            self._values.pop(key, None)
        else:
            self._values[key] = value
        for listener in list(self._listeners):
            listener(key, self.get(key))

    def reset_preferences(self) -> None:
        """Restore every preference to its default. User data and app state are untouched."""
        keys = list(PREFERENCES)
        with self.db.transaction():
            self.db.executemany("DELETE FROM settings WHERE key = ?", [(k,) for k in keys])
        for key in keys:
            self._values.pop(key, None)
        for listener in list(self._listeners):
            for key in keys:
                listener(key, self.get(key))

    def subscribe(self, listener: Callable[[str, Any], None]) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[str, Any], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)
