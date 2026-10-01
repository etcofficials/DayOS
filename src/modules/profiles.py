"""User profiles: presets that tailor navigation, the Today dashboard and quick actions.

A profile is only a starting point. It never creates a separate database or
copies data; it decides what is *shown*. Users can change profile at any time
and adjust individual modules and dashboard widgets afterwards (stored in the
``nav.modules`` and ``dashboard.widgets`` settings).

DayOS never infers a profile. New users get "General" until they choose one.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    description: str
    modules: tuple[str, ...]
    widgets: tuple[str, ...]
    quick_actions: tuple[str, ...]
    terms: dict[str, str] = field(default_factory=dict)  # module key -> nav title override


# Dashboard widgets the Today page knows how to show (order = default order).
WIDGETS: dict[str, str] = {
    "plan": "Today's plan (tasks)",
    "day": "Your day (schedule)",
    "focus": "Focus nook (timer)",
    "rituals": "Habits",
    "coming": "Coming up (exams, deadlines, goals)",
    "revision": "Revision due",
    "workload": "Workload check",
    "projects": "Active projects",
    "inbox": "Capture inbox",
    "weather": "Weather",
    "news": "News briefing",
    "money": "Bills & budget",
    "review": "End-of-day review",
}

ALL_ACTIONS = ("task", "note", "capture", "event", "focus", "test", "review", "project", "expense")

PROFILES: dict[str, Profile] = {p.id: p for p in (
    Profile("general", "General productivity",
            "Tasks, schedule, habits, goals and notes, with the other modules a click away in Settings.",
            ("today", "tasks", "calendar", "habits", "goals", "insights", "study", "inbox", "notes", "projects"),
            ("plan", "day", "focus", "rituals", "coming", "workload", "inbox", "review"),
            ("task", "note", "capture", "event", "focus")),
    Profile("school", "School student",
            "Timetable, homework, exams and revision, StudyForge practice tests and a study timer.",
            ("today", "tasks", "calendar", "habits", "goals", "insights", "study", "studyforge", "exams",
             "inbox", "notes"),
            ("plan", "day", "focus", "revision", "coming", "rituals", "workload", "review"),
            ("task", "focus", "test", "note", "capture"),
            {"study": "Study", "calendar": "Timetable"}),
    Profile("college", "College student",
            "Courses, assignments and exams, plus projects, notes and a simple budget.",
            ("today", "tasks", "calendar", "habits", "goals", "insights", "study", "studyforge", "exams",
             "inbox", "notes", "projects", "money"),
            ("plan", "day", "focus", "revision", "coming", "projects", "money", "review"),
            ("task", "focus", "test", "note", "expense"),
            {"study": "Study"}),
    Profile("learner", "Self-learner",
            "Skill roadmaps, courses and practice, notes and focused sessions.",
            ("today", "tasks", "calendar", "habits", "goals", "insights", "study", "studyforge", "skills",
             "inbox", "notes", "projects"),
            ("plan", "focus", "revision", "rituals", "projects", "coming", "review"),
            ("task", "focus", "test", "note", "capture")),
    Profile("developer", "Developer",
            "Projects, a technical knowledge vault, clipboard snippets, skills and file tools.",
            ("today", "tasks", "calendar", "habits", "goals", "insights", "study", "inbox", "notes", "clipvault",
             "projects", "skills", "filepilot"),
            ("plan", "day", "focus", "projects", "inbox", "news", "workload", "review"),
            ("task", "capture", "note", "project", "focus"),
            {"study": "Focus"}),
    Profile("professional", "Working professional",
            "Schedule, tasks, projects, notes and personal finances.",
            ("today", "tasks", "calendar", "habits", "goals", "insights", "study", "inbox", "notes", "projects",
             "money", "clipvault"),
            ("plan", "day", "coming", "projects", "workload", "weather", "money", "review"),
            ("task", "event", "note", "capture", "expense"),
            {"calendar": "Schedule"}),
    Profile("creator", "Freelancer / creator",
            "Projects and deadlines, audio setup, file clean-up, clipboard and income tracking.",
            ("today", "tasks", "calendar", "habits", "goals", "insights", "study", "inbox", "notes", "projects",
             "audiodock", "filepilot", "clipvault", "money"),
            ("plan", "day", "projects", "coming", "money", "workload", "review"),
            ("task", "project", "capture", "expense", "note")),
)}

DEFAULT_PROFILE = "general"


def get_profile(profile_id: str | None) -> Profile:
    return PROFILES.get(profile_id or "", PROFILES[DEFAULT_PROFILE])
