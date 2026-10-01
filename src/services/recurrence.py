"""Repeat rules shared by tasks and calendar events.

Rules: ``""`` (no repeat), ``daily``, ``weekdays`` (Monday–Friday), ``weekly``,
``monthly`` and ``yearly``, each with an interval ("every 2 weeks").

Month-end dates are handled the way people expect: a series that starts on the
31st falls on the last day of shorter months, and 29 February falls on
28 February in non-leap years. The series' anchor (its first date) is kept, so a
month-end series returns to the 31st whenever the month has one.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

RULES: dict[str, str] = {
    "": "Doesn't repeat",
    "daily": "Every day",
    "weekdays": "Every weekday (Mon–Fri)",
    "weekly": "Every week",
    "monthly": "Every month",
    "yearly": "Every year",
}

_UNITS = {"daily": ("day", "days"), "weekly": ("week", "weeks"), "monthly": ("month", "months"),
          "yearly": ("year", "years")}


def describe(rule: str, interval: int = 1) -> str:
    if not rule:
        return RULES[""]
    if rule == "weekdays":
        return RULES["weekdays"]
    one, many = _UNITS[rule]
    return f"Every {one}" if interval <= 1 else f"Every {interval} {many}"


def _clamped(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def nth_month(anchor: date, months: int) -> date:
    total = anchor.month - 1 + months
    return _clamped(anchor.year + total // 12, total % 12 + 1, anchor.day)


def next_date(anchor: date, rule: str, interval: int = 1, after: date | None = None) -> date | None:
    """The first occurrence strictly after ``after`` (default: ``anchor``) in the series anchored at ``anchor``."""
    if not rule:
        return None
    interval = max(1, int(interval))
    after = after or anchor
    if rule == "daily":
        steps = (after - anchor).days // interval + 1
        return anchor + timedelta(days=steps * interval)
    if rule == "weekdays":
        d = after + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d
    if rule == "weekly":
        steps = (after - anchor).days // (7 * interval) + 1
        return anchor + timedelta(days=steps * 7 * interval)
    if rule == "monthly":
        k = max(0, _months_between(anchor, after) // interval)
        while True:
            candidate = nth_month(anchor, k * interval)
            if candidate > after:
                return candidate
            k += 1
    if rule == "yearly":
        k = max(0, (after.year - anchor.year) // interval)
        while True:
            candidate = nth_month(anchor, 12 * k * interval)
            if candidate > after:
                return candidate
            k += 1
    raise ValueError(f"Unknown repeat rule {rule!r}")


def occurs_on(anchor: date, rule: str, interval: int, day: date, until: date | None = None) -> bool:
    if day < anchor or (until is not None and day > until):
        return False
    if day == anchor:
        return True
    if not rule:
        return False
    interval = max(1, int(interval))
    if rule == "daily":
        return (day - anchor).days % interval == 0
    if rule == "weekdays":
        return day.weekday() < 5
    if rule == "weekly":
        return (day - anchor).days % (7 * interval) == 0
    if rule == "monthly":
        months = _months_between(anchor, day)
        return months % interval == 0 and nth_month(anchor, months) == day
    if rule == "yearly":
        months = _months_between(anchor, day)
        return months % (12 * interval) == 0 and nth_month(anchor, months) == day
    return False


def occurrences(anchor: date, rule: str, interval: int, start: date, end: date,
                until: date | None = None, limit: int = 1000) -> list[date]:
    """All occurrences in [start, end] (inclusive), bounded by ``limit``."""
    if end < start:
        return []
    out: list[date] = []
    if not rule:
        return [anchor] if start <= anchor <= end and (until is None or anchor <= until) else []
    d: date | None = anchor
    if anchor < start:
        d = next_date(anchor, rule, interval, start - timedelta(days=1))
    while d is not None and d <= end and len(out) < limit:
        if until is not None and d > until:
            break
        if d >= start:
            out.append(d)
        d = next_date(anchor, rule, interval, d)
    return out
