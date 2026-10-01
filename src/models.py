"""Plain data classes returned by repositories."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, fields
from datetime import date
from typing import Any, TypeVar

T = TypeVar("T")

PRIORITY_LABELS = {0: "Low", 1: "Normal", 2: "High"}

CHAPTER_STATUSES = ["not_started", "learning", "needs_revision", "revised", "mastered"]
CHAPTER_STATUS_LABELS = {
    "not_started": "Not started",
    "learning": "Learning",
    "needs_revision": "Needs revision",
    "revised": "Revised",
    "mastered": "Mastered",
}
GOAL_STATUSES = ["active", "paused", "completed"]


def from_row(cls: type[T], row: sqlite3.Row | dict[str, Any]) -> T:
    keys = row.keys()
    names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    return cls(**{k: row[k] for k in keys if k in names})  # type: ignore[call-arg]


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@dataclass
class Subject:
    id: int
    name: str
    color: str = ""
    archived: int = 0
    created_at: str = ""


@dataclass
class Subtask:
    id: int
    task_id: int
    title: str
    done: int = 0
    position: int = 0


@dataclass
class Task:
    id: int
    title: str
    description: str = ""
    due_date: str | None = None
    due_time: str | None = None
    priority: int = 1
    category: str = ""
    subject_id: int | None = None
    goal_id: int | None = None
    estimate_minutes: int | None = None
    created_at: str = ""
    completed_at: str | None = None
    tags: str = ""
    project_id: int | None = None
    actual_minutes: int | None = None
    recurrence: str = ""
    recur_interval: int = 1
    next_task_id: int | None = None
    subject_name: str | None = None
    goal_title: str | None = None
    project_name: str | None = None
    subtask_total: int = 0
    subtask_done: int = 0
    blocked_by: int = 0

    @property
    def done(self) -> bool:
        return self.completed_at is not None

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def due(self) -> date | None:
        return _d(self.due_date)

    def is_overdue(self, today: date) -> bool:
        return not self.done and self.due is not None and self.due < today


@dataclass
class Note:
    id: int
    title: str
    content: str = ""
    tags: str = ""
    pinned: int = 0
    created_at: str = ""
    updated_at: str = ""

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


@dataclass
class Habit:
    id: int
    name: str
    description: str = ""
    weekdays: int = 127
    start_date: str = ""
    archived: int = 0
    position: int = 0
    created_at: str = ""
    remind_time: str | None = None
    weekly_target: int | None = None

    def is_scheduled(self, d: date) -> bool:
        return bool(self.weekdays & (1 << d.weekday()))

    @property
    def start(self) -> date:
        return date.fromisoformat(self.start_date)


@dataclass
class Goal:
    id: int
    title: str
    description: str = ""
    category: str = ""
    target_date: str | None = None
    target_value: float | None = None
    current_value: float = 0.0
    unit: str = ""
    status: str = "active"
    created_at: str = ""
    completed_at: str | None = None
    linked_tasks: int = 0
    linked_done: int = 0

    @property
    def fraction(self) -> float | None:
        if not self.target_value:
            return None
        return max(0.0, min(1.0, self.current_value / self.target_value))


@dataclass
class GoalProgress:
    id: int
    goal_id: int
    date: str
    value: float
    note: str = ""
    created_at: str = ""


@dataclass
class JournalEntry:
    date: str
    intention: str = ""
    reflection: str = ""
    went_well: str = ""
    updated_at: str = ""
    improve: str = ""


@dataclass
class Event:
    id: int
    title: str
    kind: str = "event"
    date: str = ""
    start_time: str | None = None
    end_time: str | None = None
    description: str = ""
    category: str = ""
    subject_id: int | None = None
    created_at: str = ""
    recurrence: str = ""
    recur_until: str | None = None
    remind_minutes: int | None = None
    location: str = ""
    task_id: int | None = None
    subject_name: str | None = None

    @property
    def day(self) -> date:
        return date.fromisoformat(self.date)


@dataclass
class TimetableEntry:
    id: int
    title: str
    subject_id: int | None = None
    weekday: int = 0
    start_time: str = ""
    end_time: str = ""
    location: str = ""
    valid_from: str | None = None
    valid_until: str | None = None
    created_at: str = ""
    subject_name: str | None = None

    def active_on(self, d: date) -> bool:
        if d.weekday() != self.weekday:
            return False
        if self.valid_from and d.isoformat() < self.valid_from:
            return False
        if self.valid_until and d.isoformat() > self.valid_until:
            return False
        return True


@dataclass
class AgendaItem:
    """A unified item for a day's schedule (events, classes, exams, deadlines)."""

    kind: str  # 'event' | 'deadline' | 'class' | 'exam'
    title: str
    date: date
    start_time: str | None = None
    end_time: str | None = None
    detail: str = ""
    ref_id: int = 0
    recurring: bool = False

    @property
    def sort_key(self) -> tuple:
        return (self.date, self.start_time is not None, self.start_time or "", self.title.lower())


@dataclass
class StudySession:
    id: int
    session_uid: str
    subject_id: int | None
    date: str
    started_at: str
    ended_at: str
    planned_minutes: int | None
    actual_seconds: int
    completed: int = 1
    source: str = "timer"
    note: str = ""
    subject_name: str | None = None
    task_id: int | None = None
    project_id: int | None = None
    kind: str = "study"
    task_title: str | None = None
    project_name: str | None = None


@dataclass
class Exam:
    id: int
    title: str
    exam_date: str
    subject_id: int | None = None
    exam_time: str | None = None
    syllabus: str = ""
    notes: str = ""
    created_at: str = ""
    subject_name: str | None = None
    chapter_total: int = 0
    chapter_ready: int = 0

    @property
    def day(self) -> date:
        return date.fromisoformat(self.exam_date)


@dataclass
class Chapter:
    id: int
    exam_id: int
    name: str
    status: str = "not_started"
    last_reviewed: str | None = None
    next_review: str | None = None
    interval_days: int = 0
    review_count: int = 0
    position: int = 0
    created_at: str = ""
    exam_title: str | None = None
    exam_date: str | None = None
    subject_name: str | None = None


@dataclass
class RevisionLog:
    id: int
    chapter_id: int
    date: str
    outcome: str
    note: str = ""
    created_at: str = ""


@dataclass
class Mistake:
    id: int
    question: str
    subject_id: int | None = None
    chapter_id: int | None = None
    correction: str = ""
    resolved: int = 0
    created_at: str = ""
    subject_name: str | None = None
    chapter_name: str | None = None


@dataclass
class MockTest:
    id: int
    title: str
    date: str
    marks: float
    max_marks: float
    subject_id: int | None = None
    exam_id: int | None = None
    notes: str = ""
    created_at: str = ""
    subject_name: str | None = None

    @property
    def percent(self) -> float:
        return 100.0 * self.marks / self.max_marks if self.max_marks else 0.0


@dataclass
class TaskSnapshot:
    """Everything needed to undo a task deletion."""

    task: dict[str, Any]
    subtasks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Project:
    id: int
    name: str
    description: str = ""
    status: str = "active"
    goal_id: int | None = None
    repo_url: str = ""
    color: str = ""
    start_date: str | None = None
    target_date: str | None = None
    created_at: str = ""
    updated_at: str = ""
    goal_title: str | None = None
    open_tasks: int = 0
    done_tasks: int = 0
    minutes: int = 0


@dataclass
class Milestone:
    id: int
    title: str
    target_date: str | None = None
    done_at: str | None = None
    position: int = 0
    created_at: str = ""
    goal_id: int | None = None
    project_id: int | None = None
    due_date: str | None = None

    @property
    def done(self) -> bool:
        return self.done_at is not None

    @property
    def when(self) -> date | None:
        value = self.target_date or self.due_date
        return date.fromisoformat(value) if value else None


@dataclass
class ProjectLog:
    id: int
    project_id: int
    kind: str = "note"
    date: str = ""
    minutes: int | None = None
    version: str = ""
    text: str = ""
    created_at: str = ""


@dataclass
class InboxItem:
    id: int
    kind: str
    text: str
    url: str = ""
    created_at: str = ""
    processed_at: str | None = None
    result_kind: str | None = None
    result_id: int | None = None


@dataclass
class Reminder:
    id: int
    title: str
    due_at: str
    kind: str = "custom"
    ref_id: int | None = None
    note: str = ""
    snoozed_until: str | None = None
    dismissed_at: str | None = None
    notified_at: str | None = None
    created_at: str = ""


@dataclass
class WeeklyReview:
    week_start: str
    wins: str = ""
    challenges: str = ""
    priorities: str = ""
    notes: str = ""
    updated_at: str = ""


@dataclass
class RoutineItem:
    id: int
    routine: str
    title: str
    position: int = 0
    archived: int = 0
    created_at: str = ""
