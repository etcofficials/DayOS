"""Local-date helpers. All DayOS dates are the user's local calendar dates."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Callable

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Injectable "now" so tests can pin the clock.
_now_provider: Callable[[], datetime] = datetime.now


def set_now_provider(provider: Callable[[], datetime] | None) -> None:
    global _now_provider
    _now_provider = provider or datetime.now


def now() -> datetime:
    return _now_provider()


def today() -> date:
    return now().date()


def now_stamp() -> str:
    """Local timestamp in DayOS storage format."""
    return now().replace(microsecond=0).isoformat(sep=" ")


def stamp(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat(sep=" ")


def iso(d: date) -> str:
    return d.isoformat()


class ValidationError(ValueError):
    """Raised for invalid user input; the message is shown to the user."""


def parse_date(value: str | date | None, *, field: str = "Date", required: bool = False) -> date | None:
    if isinstance(value, date):
        return value
    if value is None or str(value).strip() == "":
        if required:
            raise ValidationError(f"{field} is required.")
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError(f"{field} must be a valid date (YYYY-MM-DD).") from None


def parse_time(value: str | time | None, *, field: str = "Time", required: bool = False) -> time | None:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if value is None or str(value).strip() == "":
        if required:
            raise ValidationError(f"{field} is required.")
        return None
    text = str(value).strip()
    try:
        hours, minutes = text.split(":")[:2]
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        raise ValidationError(f"{field} must be a valid time (HH:MM).") from None


def time_str(t: time | None) -> str | None:
    return None if t is None else f"{t.hour:02d}:{t.minute:02d}"


def date_range(start: date, end: date) -> list[date]:
    """Inclusive list of dates from start to end."""
    if end < start:
        return []
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def week_start(d: date, first_weekday: int = 0) -> date:
    """Start of the week containing ``d``. ``first_weekday``: 0=Monday … 6=Sunday."""
    offset = (d.weekday() - first_weekday) % 7
    return d - timedelta(days=offset)


def month_grid_start(year: int, month: int, first_weekday: int = 0) -> date:
    return week_start(date(year, month, 1), first_weekday)


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    nxt = date(year + (month // 12), month % 12 + 1, 1)
    return (nxt - timedelta(days=1)).day


# -- display ---------------------------------------------------------------

DATE_FORMATS = {
    "dmy": "27 Sep 2026",
    "mdy": "Sep 27, 2026",
    "iso": "2026-09-27",
}


def format_date(d: date | None, style: str = "dmy", *, with_weekday: bool = False) -> str:
    if d is None:
        return ""
    mon = MONTH_NAMES[d.month - 1][:3]
    if style == "mdy":
        text = f"{mon} {d.day}, {d.year}"
    elif style == "iso":
        text = d.isoformat()
    else:
        text = f"{d.day} {mon} {d.year}"
    if with_weekday:
        text = f"{WEEKDAY_SHORT[d.weekday()]}, {text}"
    return text


def format_long_date(d: date, style: str = "dmy") -> str:
    month = MONTH_NAMES[d.month - 1]
    weekday = WEEKDAY_NAMES[d.weekday()]
    if style == "mdy":
        return f"{weekday}, {month} {d.day}, {d.year}"
    if style == "iso":
        return f"{weekday}, {d.isoformat()}"
    return f"{weekday}, {d.day} {month} {d.year}"


def format_time(t: time | str | None, clock24: bool = True) -> str:
    if t is None or t == "":
        return ""
    if isinstance(t, str):
        t = parse_time(t)
        assert t is not None
    if clock24:
        return f"{t.hour:02d}:{t.minute:02d}"
    hour = t.hour % 12 or 12
    suffix = "AM" if t.hour < 12 else "PM"
    return f"{hour}:{t.minute:02d} {suffix}"


def relative_day(d: date, ref: date | None = None) -> str:
    ref = ref or today()
    delta = (d - ref).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    if 1 < delta < 7:
        return WEEKDAY_NAMES[d.weekday()]
    if delta > 0:
        return f"In {delta} days"
    return f"{-delta} days ago"


def countdown_text(d: date, ref: date | None = None) -> str:
    ref = ref or today()
    delta = (d - ref).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta < 0:
        return f"{-delta} day{'s' if delta != -1 else ''} ago"
    weeks, days = divmod(delta, 7)
    if delta >= 14:
        return f"{delta} days (~{weeks} weeks)"
    return f"{delta} days"


def format_duration(seconds: int | float) -> str:
    """Friendly duration, e.g. '1 h 25 min' or '12 min'."""
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    return f"{hours} h {mins} min" if mins else f"{hours} h"


def greeting(dt: datetime | None = None) -> str:
    hour = (dt or now()).hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    if 17 <= hour < 22:
        return "Good evening"
    return "Hello, night owl"
