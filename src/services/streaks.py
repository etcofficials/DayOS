"""Habit streak rules (pure functions, no database access).

Definitions used throughout DayOS:

* Only **scheduled days** count. A habit scheduled Mon/Wed/Fri is not broken by
  Tuesday; a completion logged on an unscheduled day is kept in history but
  neither extends nor breaks a streak.
* **Current streak**: consecutive completed scheduled days, counting back from
  today. If today is scheduled but not yet completed, today is treated as
  still in progress and the streak continues from the previous scheduled day.
* **Longest streak**: longest run of consecutive completed scheduled days.
* Tracking begins on the earlier of the habit's start date and its first log.
  Future dates are never counted.
* **Completion rate** for a period: completed scheduled days ÷ scheduled days
  that have finished. Today is included only once it is completed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


@dataclass(frozen=True)
class StreakInfo:
    current: int
    longest: int


def _scheduled(weekdays: int, d: date) -> bool:
    return bool(weekdays & (1 << d.weekday()))


def tracking_start(start: date, done: Iterable[date]) -> date:
    earliest = min(done, default=start)
    return min(start, earliest)


def current_streak(weekdays: int, start: date, done: set[date], today: date) -> int:
    first = tracking_start(start, done)
    d = today
    if _scheduled(weekdays, d) and d not in done:
        d -= timedelta(days=1)
    streak = 0
    while d >= first:
        if _scheduled(weekdays, d):
            if d in done:
                streak += 1
            else:
                break
        d -= timedelta(days=1)
    return streak


def longest_streak(weekdays: int, start: date, done: set[date], today: date) -> int:
    first = tracking_start(start, done)
    best = run = 0
    d = first
    while d <= today:
        if _scheduled(weekdays, d):
            if d in done:
                run += 1
                best = max(best, run)
            elif d != today:
                run = 0
        d += timedelta(days=1)
    return best


def streaks(weekdays: int, start: date, done: set[date], today: date) -> StreakInfo:
    return StreakInfo(
        current=current_streak(weekdays, start, done, today),
        longest=longest_streak(weekdays, start, done, today),
    )


def completion_rate(
    weekdays: int, start: date, done: set[date], period_start: date, period_end: date, today: date
) -> tuple[int, int]:
    """Return (completed, eligible) scheduled days within the period."""
    first = max(period_start, tracking_start(start, done))
    last = min(period_end, today)
    completed = eligible = 0
    d = first
    while d <= last:
        if _scheduled(weekdays, d):
            if d in done:
                completed += 1
                eligible += 1
            elif d != today:
                eligible += 1
        d += timedelta(days=1)
    return completed, eligible
