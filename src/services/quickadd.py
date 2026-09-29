"""Tiny, predictable parser for quick-add task text.

Recognised tokens (anywhere in the text, case-insensitive):

* ``today``, ``tomorrow``, ``tmr`` or a weekday name (``mon``/``monday`` …) → due date
  (a weekday means its next occurrence; today's weekday means one week ahead)
* ``!high`` / ``!h`` / ``!!``, ``!low`` / ``!l`` → priority
* ``#word`` → category

Everything else becomes the title.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

_WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}


@dataclass
class QuickTask:
    title: str
    due_date: date | None = None
    priority: int = 1
    category: str = ""


def parse_quick_task(text: str, ref: date) -> QuickTask:
    words = text.split()
    title_words: list[str] = []
    result = QuickTask(title="")
    for word in words:
        low = word.lower().rstrip(",.")
        if low in ("today", "tod"):
            result.due_date = ref
        elif low in ("tomorrow", "tmr", "tmrw"):
            result.due_date = ref + timedelta(days=1)
        elif low in _WEEKDAYS and len(words) > 1:
            delta = (_WEEKDAYS[low] - ref.weekday()) % 7 or 7
            result.due_date = ref + timedelta(days=delta)
        elif low in ("!high", "!h", "!!"):
            result.priority = 2
        elif low in ("!low", "!l"):
            result.priority = 0
        elif low.startswith("#") and len(low) > 1:
            result.category = word[1:].rstrip(",.")
        else:
            title_words.append(word)
    result.title = " ".join(title_words).strip()
    if not result.title:
        result.title = text.strip()
        result.due_date, result.priority, result.category = None, 1, ""
    return result
