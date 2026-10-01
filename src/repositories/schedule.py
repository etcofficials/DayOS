"""Calendar events, recurring timetable and the combined agenda.

Constraints (explained in the UI): an event starts and ends on the same day —
events crossing midnight should be split into two entries. Timetable entries
repeat weekly on one weekday, optionally limited to a date window, and single
occurrences can be skipped without touching the rest of the series.

Events can repeat too (daily, weekdays, weekly, monthly, yearly; see
:mod:`src.services.recurrence`). Reading a date range expands a repeating event
into one :class:`Event` per occurrence (same id, ``date`` set to the occurrence);
single occurrences can be skipped via ``event_skips``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
from typing import Any

from src.models import AgendaItem, Event, TimetableEntry, from_row
from src.repositories.base import Repository, clean_text, optional_id
from src.services import recurrence
from src.services.dates import ValidationError, date_range, iso, now_stamp, parse_date, parse_time, time_str

_EVENT_SELECT = "SELECT e.*, s.name AS subject_name FROM events e LEFT JOIN subjects s ON s.id = e.subject_id"
_TT_SELECT = "SELECT t.*, s.name AS subject_name FROM timetable t LEFT JOIN subjects s ON s.id = t.subject_id"


def _overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return a_start < b_end and b_start < a_end


class ScheduleRepository(Repository):
    # -- events -------------------------------------------------------------
    def _clean_event(self, data: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "title": clean_text(data.get("title"), field="Title", required=True, max_len=150),
            "kind": data.get("kind", "event"),
            "description": clean_text(data.get("description", ""), field="Description", max_len=3000),
            "category": clean_text(data.get("category", ""), field="Category", max_len=60),
            "subject_id": optional_id(data.get("subject_id")),
        }
        if out["kind"] not in ("event", "deadline"):
            raise ValidationError("Unknown event type.")
        d = parse_date(data.get("date"), field="Date", required=True)
        out["date"] = iso(d)  # type: ignore[arg-type]
        start = parse_time(data.get("start_time"), field="Start time")
        end = parse_time(data.get("end_time"), field="End time")
        if end is not None and start is None:
            raise ValidationError("Set a start time before setting an end time.")
        if start is not None and end is not None and end <= start:
            raise ValidationError(
                "The end time must be after the start time. Events can't cross midnight — "
                "split late-night events into two entries."
            )
        out["start_time"] = time_str(start)
        out["end_time"] = time_str(end)
        rule = data.get("recurrence", "") or ""
        if rule not in recurrence.RULES:
            raise ValidationError("Unknown repeat rule.")
        out["recurrence"] = rule
        until = parse_date(data.get("recur_until"), field="Repeat until") if rule else None
        if until is not None and until < d:  # type: ignore[operator]
            raise ValidationError("The repeat end date must be on or after the first date.")
        out["recur_until"] = iso(until) if until else None
        remind = data.get("remind_minutes")
        if remind in ("", None):
            out["remind_minutes"] = None
        else:
            remind = int(remind)
            if not 0 <= remind <= 10080:
                raise ValidationError("Reminders can be set up to a week before an event.")
            if start is None:
                raise ValidationError("Set a start time to get a reminder before the event.")
            out["remind_minutes"] = remind
        out["location"] = clean_text(data.get("location", ""), field="Location", max_len=150)
        out["task_id"] = optional_id(data.get("task_id"))
        return out

    def create_event(self, **data: Any) -> int:
        clean = self._clean_event(data)
        clean["created_at"] = now_stamp()
        cols = ", ".join(clean)
        marks = ", ".join("?" for _ in clean)
        with self.db.transaction():
            return self.db.insert(f"INSERT INTO events ({cols}) VALUES ({marks})", list(clean.values()))

    def update_event(self, event_id: int, **data: Any) -> None:
        clean = self._clean_event(data)
        assignments = ", ".join(f"{k} = ?" for k in clean)
        with self.db.transaction():
            self.db.execute(f"UPDATE events SET {assignments} WHERE id = ?", [*clean.values(), event_id])

    def delete_event(self, event_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def get_event(self, event_id: int) -> Event | None:
        row = self.db.query_one(_EVENT_SELECT + " WHERE e.id = ?", (event_id,))
        return from_row(Event, row) if row else None

    def events_between(self, start: date, end: date, kind: str | None = None) -> list[Event]:
        """Events in [start, end] with repeating events expanded to one entry per occurrence."""
        kind_sql = " AND e.kind = ?" if kind else ""
        params: list[Any] = [iso(start), iso(end)]
        rows = self.db.query(
            _EVENT_SELECT + " WHERE e.recurrence = '' AND e.date BETWEEN ? AND ?" + kind_sql,
            params + ([kind] if kind else []),
        )
        events = [from_row(Event, r) for r in rows]
        repeating = self.db.query(
            _EVENT_SELECT + " WHERE e.recurrence != '' AND e.date <= ? AND (e.recur_until IS NULL OR e.recur_until >= ?)"
            + kind_sql, [iso(end), iso(start)] + ([kind] if kind else []))
        if repeating:
            skips = {(int(r[0]), r[1]) for r in self.db.query(
                "SELECT event_id, date FROM event_skips WHERE date BETWEEN ? AND ?", (iso(start), iso(end)))}
            for row in repeating:
                series = from_row(Event, row)
                until = date.fromisoformat(series.recur_until) if series.recur_until else None
                for day in recurrence.occurrences(series.day, series.recurrence, 1, start, end, until, limit=400):
                    if (series.id, iso(day)) not in skips:
                        events.append(replace(series, date=iso(day)))
        events.sort(key=lambda e: (e.date, e.start_time is not None, e.start_time or "", e.title.lower()))
        return events

    def upcoming_deadlines(self, start: date, end: date) -> list[Event]:
        return self.events_between(start, end, kind="deadline")

    def skip_event_occurrence(self, event_id: int, day: date) -> None:
        with self.db.transaction():
            self.db.execute("INSERT OR IGNORE INTO event_skips (event_id, date) VALUES (?, ?)", (event_id, iso(day)))

    def end_event_series(self, event_id: int, last_day: date) -> None:
        """Stop a repeating event after ``last_day`` (earlier occurrences stay)."""
        event = self.get_event(event_id)
        if event is None:
            return
        if last_day < event.day:
            self.delete_event(event_id)
            return
        with self.db.transaction():
            self.db.execute("UPDATE events SET recur_until = ? WHERE id = ?", (iso(last_day), event_id))

    # -- timetable ----------------------------------------------------------
    def _clean_entry(self, data: dict[str, Any]) -> dict[str, Any]:
        weekday = int(data.get("weekday", -1))
        if not 0 <= weekday <= 6:
            raise ValidationError("Choose a weekday.")
        start = parse_time(data.get("start_time"), field="Start time", required=True)
        end = parse_time(data.get("end_time"), field="End time", required=True)
        assert start is not None and end is not None
        if end <= start:
            raise ValidationError("The end time must be after the start time.")
        valid_from = parse_date(data.get("valid_from"), field="Start date")
        valid_until = parse_date(data.get("valid_until"), field="End date")
        if valid_from and valid_until and valid_until < valid_from:
            raise ValidationError("The repeat end date must be on or after its start date.")
        return {
            "title": clean_text(data.get("title"), field="Title", required=True, max_len=150),
            "subject_id": optional_id(data.get("subject_id")),
            "weekday": weekday,
            "start_time": time_str(start),
            "end_time": time_str(end),
            "location": clean_text(data.get("location", ""), field="Location", max_len=100),
            "valid_from": iso(valid_from) if valid_from else None,
            "valid_until": iso(valid_until) if valid_until else None,
        }

    def create_entry(self, **data: Any) -> int:
        clean = self._clean_entry(data)
        clean["created_at"] = now_stamp()
        cols = ", ".join(clean)
        marks = ", ".join("?" for _ in clean)
        with self.db.transaction():
            return self.db.insert(f"INSERT INTO timetable ({cols}) VALUES ({marks})", list(clean.values()))

    def update_entry(self, entry_id: int, **data: Any) -> None:
        """Edit the whole weekly series (every occurrence changes)."""
        clean = self._clean_entry(data)
        assignments = ", ".join(f"{k} = ?" for k in clean)
        with self.db.transaction():
            self.db.execute(f"UPDATE timetable SET {assignments} WHERE id = ?", [*clean.values(), entry_id])

    def delete_entry(self, entry_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM timetable WHERE id = ?", (entry_id,))

    def end_series(self, entry_id: int, last_day: date) -> None:
        """Stop a repeating entry after ``last_day``, keeping past occurrences."""
        entry = self.get_entry(entry_id)
        if entry is None:
            return
        if entry.valid_from and iso(last_day) < entry.valid_from:
            self.delete_entry(entry_id)
            return
        with self.db.transaction():
            self.db.execute("UPDATE timetable SET valid_until = ? WHERE id = ?", (iso(last_day), entry_id))

    def get_entry(self, entry_id: int) -> TimetableEntry | None:
        row = self.db.query_one(_TT_SELECT + " WHERE t.id = ?", (entry_id,))
        return from_row(TimetableEntry, row) if row else None

    def entries(self) -> list[TimetableEntry]:
        rows = self.db.query(_TT_SELECT + " ORDER BY t.weekday, t.start_time")
        return [from_row(TimetableEntry, r) for r in rows]

    def skip_occurrence(self, entry_id: int, day: date) -> None:
        with self.db.transaction():
            self.db.execute("INSERT OR IGNORE INTO timetable_skips (entry_id, date) VALUES (?, ?)", (entry_id, iso(day)))

    def unskip_occurrence(self, entry_id: int, day: date) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM timetable_skips WHERE entry_id = ? AND date = ?", (entry_id, iso(day)))

    def _skips(self, start: date, end: date) -> set[tuple[int, str]]:
        rows = self.db.query("SELECT entry_id, date FROM timetable_skips WHERE date BETWEEN ? AND ?", (iso(start), iso(end)))
        return {(int(r[0]), r[1]) for r in rows}

    # -- agenda ---------------------------------------------------------------
    def agenda(self, start: date, end: date, include_tasks: bool = True) -> dict[date, list[AgendaItem]]:
        """All scheduled items per day in [start, end] (bounded by the caller)."""
        items: dict[date, list[AgendaItem]] = defaultdict(list)
        for e in self.events_between(start, end):
            detail = " · ".join(x for x in (e.subject_name or e.category or "", e.location) if x)
            items[date.fromisoformat(e.date)].append(
                AgendaItem(e.kind, e.title, date.fromisoformat(e.date), e.start_time, e.end_time, detail, e.id,
                           bool(e.recurrence))
            )
        skips = self._skips(start, end)
        entries = self.entries()
        if entries:
            for day in date_range(start, end):
                for entry in entries:
                    if entry.active_on(day) and (entry.id, iso(day)) not in skips:
                        detail = " · ".join(x for x in (entry.subject_name or "", entry.location) if x)
                        items[day].append(
                            AgendaItem("class", entry.title, day, entry.start_time, entry.end_time, detail, entry.id)
                        )
        for row in self.db.query(
            "SELECT x.id, x.title, x.exam_date, x.exam_time, s.name AS subject FROM exams x "
            "LEFT JOIN subjects s ON s.id = x.subject_id WHERE x.exam_date BETWEEN ? AND ?",
            (iso(start), iso(end)),
        ):
            day = date.fromisoformat(row["exam_date"])
            items[day].append(AgendaItem("exam", row["title"], day, row["exam_time"], None, row["subject"] or "", row["id"]))
        if include_tasks:
            for row in self.db.query(
                "SELECT id, title, due_date, due_time, completed_at FROM tasks "
                "WHERE due_date BETWEEN ? AND ? ORDER BY due_time",
                (iso(start), iso(end)),
            ):
                day = date.fromisoformat(row["due_date"])
                detail = "Completed" if row["completed_at"] else "Task due"
                items[day].append(AgendaItem("task", row["title"], day, row["due_time"], None, detail, row["id"]))
        for day_items in items.values():
            day_items.sort(key=lambda i: i.sort_key)
        return dict(items)

    def day_agenda(self, day: date, include_tasks: bool = False) -> list[AgendaItem]:
        return self.agenda(day, day, include_tasks).get(day, [])

    # -- overlap warnings -------------------------------------------------
    def event_conflicts(self, day: date, start: str | None, end: str | None, exclude_id: int | None = None) -> list[str]:
        if not start or not end:
            return []
        titles: list[str] = []
        for item in self.day_agenda(day):
            if item.kind == "event" and item.ref_id == exclude_id:
                continue
            if item.start_time and item.end_time and _overlaps(start, end, item.start_time, item.end_time):
                titles.append(f"{item.title} ({item.start_time}–{item.end_time})")
        return titles

    def conflicts_between(self, start: date, end: date) -> list[tuple[date, "AgendaItem", "AgendaItem"]]:
        """Every pair of overlapping timed items (events, classes, exams) per day in [start, end]."""
        found = []
        for day, items in self.agenda(start, end, include_tasks=False).items():
            timed = [i for i in items if i.start_time and i.end_time]
            for i, a in enumerate(timed):
                for b in timed[i + 1:]:
                    if _overlaps(a.start_time, a.end_time, b.start_time, b.end_time):  # type: ignore[arg-type]
                        found.append((day, a, b))
        return sorted(found, key=lambda x: (x[0], x[1].start_time or ""))

    def entry_conflicts(self, weekday: int, start: str, end: str, exclude_id: int | None = None) -> list[str]:
        titles = []
        for entry in self.entries():
            if entry.id == exclude_id or entry.weekday != weekday:
                continue
            if _overlaps(start, end, entry.start_time, entry.end_time):
                titles.append(f"{entry.title} ({entry.start_time}–{entry.end_time})")
        return titles
