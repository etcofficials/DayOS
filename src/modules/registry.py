"""The DayOS module registry.

Every page in the sidebar is described by a :class:`ModuleSpec`. The main window
builds its grouped navigation from this list and imports a page's code only the
first time it is opened (``factory`` is a ``"module.path:ClassName"`` string),
so expensive modules cost nothing until used.

Profiles (see :mod:`src.modules.profiles`) decide which modules are visible;
``core`` modules can't be hidden.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

GROUPS: list[tuple[str, str]] = [
    ("home", "Your day"),
    ("learn", "Learning"),
    ("knowledge", "Knowledge"),
    ("create", "Make & grow"),
    ("life", "Life"),
    ("tools", "Desktop tools"),
]


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    title: str
    icon: str
    group: str
    factory: str
    description: str
    core: bool = False  # always visible
    eager: bool = False  # created at startup (pages other code depends on)


MODULES: list[ModuleSpec] = [
    ModuleSpec("today", "Today", "today", "home", "src.ui.pages.today:TodayPage",
               "Your daily dashboard: plan, schedule, focus and rituals.", core=True, eager=True),
    ModuleSpec("tasks", "Tasks", "tasks", "home", "src.ui.pages.tasks:TasksPage",
               "Tasks with due dates, priorities, tags, projects and checklists.", core=True),
    ModuleSpec("calendar", "Calendar", "calendar", "home", "src.ui.pages.calendar:CalendarPage",
               "Day, week and month views, timetable and recurring events."),
    ModuleSpec("habits", "Habits", "habits", "home", "src.ui.pages.habits:HabitsPage",
               "Gentle habit tracking with flexible schedules."),
    ModuleSpec("goals", "Goals & reviews", "goals", "home", "src.ui.pages.goals:GoalsPage",
               "Goals, milestones, journal, daily and weekly reviews."),
    ModuleSpec("study", "Focus", "study", "learn", "src.ui.pages.study:StudyPage",
               "Focus timer, pomodoro presets and session history.", eager=True),
    ModuleSpec("exams", "Exams", "exams", "learn", "src.ui.pages.exams:ExamsPage",
               "Exam dates, chapter checklists, mistakes and mock-test scores."),
    ModuleSpec("inbox", "Inbox", "inbox", "knowledge", "src.ui.pages.inbox:InboxPage",
               "Everything you captured quickly, ready to sort into tasks, notes or projects."),
    ModuleSpec("notes", "SecondBrain", "brain", "knowledge", "src.modules.brain.ui.page:BrainPage",
               "Notes, bookmarks, code snippets, commands, ideas and troubleshooting notes, all searchable."),
    ModuleSpec("insights", "Insights", "insights", "home", "src.ui.pages.insights:InsightsPage",
               "Charts built only from your own records."),
]

SETTINGS = ModuleSpec("settings", "Settings", "settings", "", "src.ui.pages.settings:SettingsPage",
                      "Themes, profile, privacy, data and backups.", core=True)

_BY_KEY = {m.key: m for m in MODULES}
_BY_KEY[SETTINGS.key] = SETTINGS


def register(spec: ModuleSpec, after: str | None = None) -> None:
    """Add a module (used by feature packages); keeps registry order stable."""
    if spec.key in _BY_KEY:
        return
    index = len(MODULES)
    if after is not None:
        for i, m in enumerate(MODULES):
            if m.key == after:
                index = i + 1
    MODULES.insert(index, spec)
    _BY_KEY[spec.key] = spec


def get(key: str) -> ModuleSpec | None:
    return _BY_KEY.get(key)


def all_keys() -> list[str]:
    return [m.key for m in MODULES] + [SETTINGS.key]


def load_class(spec: ModuleSpec):
    module_name, _, class_name = spec.factory.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)
