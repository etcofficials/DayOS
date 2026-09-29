"""Deterministic, rule-based revision scheduling.

This is a simple expanding-interval rule, not an optimized or AI-driven
algorithm. After you revise a chapter you rate how it went:

* **Hard**  → review again tomorrow (interval resets to 1 day); status becomes
  "Needs revision".
* **Okay**  → interval doubles (minimum 2 days, maximum 30); status "Revised".
* **Easy**  → interval triples (minimum 4 days, maximum 60); status "Revised",
  or "Mastered" once the interval reaches 21 days.

The next review date is never scheduled after the exam date when the exam is
still ahead (it is pulled back to the day before the exam) so every chapter
gets a final look.

The queue lists chapters whose next review date is today or earlier, plus
chapters of upcoming exams that are "Learning" or "Needs revision" and have no
review scheduled. It is ordered by: overdue first, then nearest exam, then
status (needs revision → learning → revised).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

OUTCOMES = ("hard", "okay", "easy")
OUTCOME_LABELS = {"hard": "Hard", "okay": "Okay", "easy": "Easy"}


@dataclass(frozen=True)
class ReviewResult:
    interval_days: int
    next_review: date
    status: str


def schedule_next(outcome: str, previous_interval: int, reviewed_on: date, exam_date: date | None = None) -> ReviewResult:
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown outcome: {outcome}")
    previous_interval = max(0, int(previous_interval))
    if outcome == "hard":
        interval, status = 1, "needs_revision"
    elif outcome == "okay":
        interval, status = min(30, max(2, previous_interval * 2)), "revised"
    else:
        interval = min(60, max(4, previous_interval * 3))
        status = "mastered" if interval >= 21 else "revised"
    next_review = reviewed_on + timedelta(days=interval)
    if exam_date is not None and reviewed_on < exam_date - timedelta(days=1) and next_review >= exam_date:
        next_review = exam_date - timedelta(days=1)
    return ReviewResult(interval, next_review, status)


STATUS_PRIORITY = {"needs_revision": 0, "learning": 1, "not_started": 2, "revised": 3, "mastered": 4}


def queue_sort_key(next_review: date | None, exam_date: date | None, status: str, today: date) -> tuple:
    overdue_days = (today - next_review).days if next_review and next_review <= today else -1
    exam_distance = (exam_date - today).days if exam_date and exam_date >= today else 10_000
    return (-overdue_days, exam_distance, STATUS_PRIORITY.get(status, 9))
