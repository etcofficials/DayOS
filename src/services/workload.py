"""Workload check: is today's plan realistic for the time you said you have?

Only real numbers are used: timed calendar items, and estimates you gave to
open tasks due that day. Tasks without an estimate are counted separately and
never guessed. DayOS suggests what could move; it never moves anything itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.models import Task


def _minutes(start: str | None, end: str | None) -> int:
    if not start or not end:
        return 0
    sh, sm = (int(x) for x in start.split(":")[:2])
    eh, em = (int(x) for x in end.split(":")[:2])
    return max(0, (eh * 60 + em) - (sh * 60 + sm))


@dataclass
class Workload:
    day: date
    available_minutes: int | None  # None when the user hasn't said how much time they have
    scheduled_minutes: int
    task_minutes: int
    unestimated_tasks: int
    suggestions: list[Task] = field(default_factory=list)

    @property
    def planned_minutes(self) -> int:
        return self.scheduled_minutes + self.task_minutes

    @property
    def over_by(self) -> int:
        if self.available_minutes is None:
            return 0
        return max(0, self.planned_minutes - self.available_minutes)

    @property
    def fraction(self) -> float | None:
        if not self.available_minutes:
            return None
        return self.planned_minutes / self.available_minutes


def available_minutes(settings, day: date) -> int | None:
    key = "workload.weekend_hours" if day.weekday() >= 5 else "workload.hours"
    hours = settings.get(key)
    if hours is None and day.weekday() >= 5:
        hours = settings.get("workload.hours")
    return None if hours is None else int(round(float(hours) * 60))


def day_workload(ctx, day: date) -> Workload:
    scheduled = sum(_minutes(i.start_time, i.end_time) for i in ctx.schedule.day_agenda(day))
    task_minutes, unestimated = ctx.tasks.open_estimate_minutes(day)
    load = Workload(day, available_minutes(ctx.settings, day), scheduled, task_minutes, unestimated)
    if load.over_by:
        load.suggestions = suggest_moves(ctx.tasks.list("today", ref=day, limit=200), load.over_by)
    return load


def suggest_moves(tasks: list[Task], over_by: int) -> list[Task]:
    """Open, estimated tasks that could move to free ``over_by`` minutes: lowest priority first,
    then the ones without a fixed time, then the largest estimates (so fewer tasks move)."""
    candidates = [t for t in tasks if not t.done and t.estimate_minutes]
    candidates.sort(key=lambda t: (t.priority, t.due_time is not None, -(t.estimate_minutes or 0)))
    picked: list[Task] = []
    freed = 0
    for task in candidates:
        if freed >= over_by:
            break
        picked.append(task)
        freed += task.estimate_minutes or 0
    return picked
