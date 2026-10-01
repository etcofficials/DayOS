"""Reminders and notifications, computed from your records (no background polling).

Sources (each can be switched off in Settings → Focus & notifications):

* ``reminder``: reminders you set (standalone or on a task);
* ``event``: calendar events with "remind me N minutes before";
* ``habit``: habits with a reminder time, only while not yet done today;
* ``bedtime``: an optional gentle bedtime nudge;
* extra providers registered by modules (e.g. subscription renewals).

Quiet hours never hide anything from the notification centre; they only stop
desktop pop-ups. The UI asks :meth:`NotificationService.next_wakeup` when to
check again and sets a single timer, so nothing runs while nothing is due.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable

from src.services.dates import iso, now, stamp

CATEGORIES = {
    "reminder": "Your reminders",
    "event": "Event reminders",
    "habit": "Habit reminders",
    "bedtime": "Bedtime reminder",
    "bill": "Bills & subscriptions",
}


@dataclass(frozen=True)
class Notice:
    key: str
    category: str
    title: str
    body: str
    due: datetime
    ref_kind: str = ""
    ref_id: int = 0

    def is_overdue(self, at: datetime) -> bool:
        """More than an hour late (as opposed to just due)."""
        return at - self.due > timedelta(hours=1)


Provider = Callable[[datetime, datetime], list[Notice]]


def _hhmm(value: str | None) -> time | None:
    if not value:
        return None
    try:
        h, m = (int(x) for x in value.split(":")[:2])
        return time(h, m)
    except (ValueError, TypeError):
        return None


def in_quiet_hours(at: datetime, start: str, end: str) -> bool:
    a, b = _hhmm(start), _hhmm(end)
    if a is None or b is None or a == b:
        return False
    t = at.time()
    return a <= t < b if a < b else (t >= a or t < b)


class NotificationService:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self._providers: dict[str, Provider] = {}

    def add_provider(self, name: str, provider: Provider) -> None:
        self._providers[name] = provider

    # -- preferences ----------------------------------------------------------------
    def enabled(self, category: str) -> bool:
        key = f"notify.{category}"
        try:
            return bool(self.ctx.settings.get(key))
        except KeyError:
            return True

    def quiet_now(self, at: datetime | None = None) -> bool:
        s = self.ctx.settings
        return bool(s.get("quiet.enabled")) and in_quiet_hours(at or now(), s.get("quiet.start"), s.get("quiet.end"))

    # -- collection ----------------------------------------------------------------------
    def _collect(self, start: datetime, end: datetime) -> list[Notice]:
        """All candidate notices due in [start, end], before snooze/dismiss filtering."""
        out: list[Notice] = []
        if self.enabled("reminder"):
            for r in self.ctx.reminders.pending(end):
                due = datetime.fromisoformat(r.snoozed_until or r.due_at)
                body = r.note or ("Task reminder" if r.kind == "task" else "Reminder")
                out.append(Notice(f"reminder:{r.id}", "reminder", r.title, body, due,
                                  "task" if r.kind == "task" else "reminder", r.ref_id or r.id))
        if self.enabled("event"):
            for e in self.ctx.schedule.events_between(start.date() - timedelta(days=1), end.date() + timedelta(days=7)):
                if e.remind_minutes is None or not e.start_time:
                    continue
                starts = datetime.combine(e.day, _hhmm(e.start_time) or time())
                due = starts - timedelta(minutes=e.remind_minutes)
                if start - timedelta(days=1) <= due <= end:
                    when = "now" if e.remind_minutes == 0 else f"in {e.remind_minutes} min" \
                        if e.remind_minutes < 120 else f"at {e.start_time}"
                    out.append(Notice(f"event:{e.id}:{e.date}", "event", e.title,
                                      f"Starts {when}" + (f" · {e.location}" if e.location else ""), due, "event", e.id))
        if self.enabled("habit"):
            for day in {start.date(), end.date()}:
                done = self.ctx.habits.done_on(day)
                for h in self.ctx.habits.scheduled_on(day):
                    t = _hhmm(h.remind_time)
                    if t is None or h.id in done:
                        continue
                    due = datetime.combine(day, t)
                    if due <= end:
                        out.append(Notice(f"habit:{h.id}:{iso(day)}", "habit", h.name,
                                          "A gentle nudge for today's habit", due, "habit", h.id))
        if self.enabled("bedtime"):
            t = _hhmm(self.ctx.settings.get("bedtime.time"))
            if t is not None:
                for day in {start.date(), end.date()}:
                    due = datetime.combine(day, t)
                    if due <= end:
                        out.append(Notice(f"bedtime:{iso(day)}", "bedtime", "Time to wind down",
                                          "Your bedtime is coming up. Tomorrow's plan can wait.", due))
        for name, provider in list(self._providers.items()):
            category = name.split(":")[0]
            if not self.enabled(category):
                continue
            try:
                out.extend(provider(start, end))
            except Exception:  # an optional module must never break notifications
                import logging

                logging.getLogger(__name__).warning("Notification provider %s failed", name, exc_info=True)
        return out

    def _visible(self, notice: Notice, at: datetime) -> bool:
        if notice.key.startswith("reminder:"):
            return True  # reminders carry their own snooze/dismiss state
        st = self.ctx.reminders.state(notice.key)
        if st["dismissed_at"]:
            return False
        if st["snoozed_until"] and datetime.fromisoformat(st["snoozed_until"]) > at:
            return False
        return True

    def due(self, at: datetime | None = None) -> list[Notice]:
        """Notices due now (not dismissed or snoozed), oldest first."""
        at = at or now()
        horizon_start = at - timedelta(days=2)
        notices = [n for n in self._collect(horizon_start, at) if n.due <= at and self._visible(n, at)]
        return sorted(notices, key=lambda n: n.due)

    def upcoming(self, at: datetime | None = None, hours: int = 24) -> list[Notice]:
        at = at or now()
        notices = [n for n in self._collect(at, at + timedelta(hours=hours)) if n.due > at and self._visible(n, at)]
        return sorted(notices, key=lambda n: n.due)

    def next_wakeup(self, at: datetime | None = None) -> datetime | None:
        """When something next becomes due (within a day), so the UI can sleep until then."""
        at = at or now()
        upcoming = self.upcoming(at, 24)
        times = [n.due for n in upcoming]
        snoozes = self.ctx.db.query(
            "SELECT snoozed_until FROM notification_state WHERE snoozed_until > ?", (stamp(at),))
        times.extend(datetime.fromisoformat(r[0]) for r in snoozes)
        return min(times) if times else None

    # -- actions ------------------------------------------------------------------------------
    def snooze(self, notice: Notice, minutes: int) -> None:
        until = now() + timedelta(minutes=minutes)
        if notice.key.startswith("reminder:"):
            self.ctx.reminders.snooze(int(notice.key.split(":")[1]), until)
        else:
            self.ctx.reminders.set_state(notice.key, snoozed_until=stamp(until))

    def dismiss(self, notice: Notice) -> None:
        if notice.key.startswith("reminder:"):
            self.ctx.reminders.dismiss(int(notice.key.split(":")[1]))
        else:
            self.ctx.reminders.set_state(notice.key, dismissed_at=stamp(now()))

    def mark_notified(self, notice: Notice) -> None:
        if notice.key.startswith("reminder:"):
            self.ctx.reminders.mark_notified(int(notice.key.split(":")[1]))
        else:
            self.ctx.reminders.set_state(notice.key, notified_at=stamp(now()))

    def was_notified(self, notice: Notice) -> bool:
        if notice.key.startswith("reminder:"):
            r = self.ctx.reminders.get(int(notice.key.split(":")[1]))
            return bool(r and r.notified_at and (not r.snoozed_until or r.notified_at >= r.snoozed_until))
        return bool(self.ctx.reminders.state(notice.key)["notified_at"])

    def overdue_tasks(self, day: date | None = None) -> int:
        return int(self.ctx.tasks.counts(day).get("overdue", 0))
