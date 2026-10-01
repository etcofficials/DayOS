"""User preferences stored in the ``settings`` table as JSON values.

Unknown or invalid stored values fall back to defaults (and are logged) so a
damaged setting can never stop DayOS from starting. Keys beginning with
``state.`` hold app state (e.g. an in-progress study timer) rather than
preferences; "Reset settings" leaves them alone and never touches user data.
"""

from __future__ import annotations

import copy
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


def _str_max(n: int) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, str) and len(v) <= n


def _str_list(max_items: int = 100, max_len: int = 200) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, list) and len(v) <= max_items and all(
        isinstance(x, str) and len(x) <= max_len for x in v)


def _opt_str_list(max_items: int = 100) -> Callable[[Any], bool]:
    inner = _str_list(max_items, 60)
    return lambda v: v is None or inner(v)


def _str_dict(max_items: int = 50) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, dict) and len(v) <= max_items and all(
        isinstance(k, str) and isinstance(x, str) and len(k) <= 40 and len(x) <= 40 for k, x in v.items())


def _number_range(lo: float, hi: float) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def _hhmm(v: Any) -> bool:
    if not isinstance(v, str) or len(v) != 5 or v[2] != ":":
        return False
    try:
        return 0 <= int(v[:2]) <= 23 and 0 <= int(v[3:]) <= 59
    except ValueError:
        return False


THEME_CHOICES = ("system", "paper", "midnight", "zen", "aurora", "espresso", "light", "dark")
FONT_SCALES = (0.9, 1.0, 1.1, 1.25)
PROFILE_CHOICES = ("general", "school", "college", "learner", "developer", "professional", "creator")

PREFERENCES: dict[str, tuple[Any, Callable[[Any], bool]]] = {
    "theme": ("paper", _choice(*THEME_CHOICES)),
    "theme.accents": ({}, _str_dict()),
    "font_scale": (1.0, lambda v: v in FONT_SCALES and not isinstance(v, bool)),
    "profile": ("general", _choice(*PROFILE_CHOICES)),
    "nav.modules": (None, _opt_str_list()),
    "dashboard.widgets": (None, _opt_str_list()),
    "onboarded": (False, _bool),
    "notify.reminder": (True, _bool),
    "notify.event": (True, _bool),
    "notify.habit": (False, _bool),
    "notify.bedtime": (False, _bool),
    "notify.bill": (True, _bool),
    "bedtime.time": ("22:30", _hhmm),
    "quiet.enabled": (False, _bool),
    "quiet.start": ("22:00", _hhmm),
    "quiet.end": ("07:00", _hhmm),
    "workload.hours": (None, lambda v: v is None or _number_range(0.5, 18)(v)),
    "workload.weekend_hours": (None, lambda v: v is None or _number_range(0.5, 18)(v)),
    "focus.break_reminder": (0, _int_range(0, 240)),
    "focus.cycles": (4, _int_range(2, 8)),
    "capture.hotkey": ("Ctrl+Alt+N", _str_max(40)),
    "capture.global": (True, _bool),
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
                value = default
            return copy.deepcopy(value) if isinstance(value, (dict, list)) else value
        value = self._values.get(key)
        return copy.deepcopy(value) if isinstance(value, (dict, list)) else value

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
