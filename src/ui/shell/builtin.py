"""Built-in palette commands and record openers (feature modules register their own)."""

from __future__ import annotations

from src.modules import registry
from src.modules.profiles import get_profile
from src.services.dates import today
from src.ui.bus import bus
from src.ui.shell.commands import Command
from src.ui.themes import THEMES


def register_builtins(w) -> None:
    ctx = w.ctx
    add = w.commands.add
    terms = get_profile(ctx.settings.get("profile")).terms

    for spec in registry.MODULES + [registry.SETTINGS]:
        title = terms.get(spec.key, spec.title)
        add(Command(f"go.{spec.key}", f"Open {title}", spec.description, icon=spec.icon,
                    run=lambda k=spec.key: w.navigate(k), keywords=("go", "open", spec.key), group="Navigate"))

    def page_new(key: str) -> None:
        w.navigate(key)
        w.page(key).new_item()

    def new_event() -> None:
        from src.ui.pages.calendar import EventDialog

        EventDialog(ctx, w, day=today()).exec()

    def new_reminder() -> None:
        from src.ui.shell.reminder_dialog import ReminderDialog

        ReminderDialog(ctx, w).exec()

    def start_focus() -> None:
        study = w.page("study")
        w.navigate("study")
        if not study.timer.is_active:
            study.start_pause()

    def daily_review() -> None:
        from src.ui.dialogs import DailyReviewDialog

        DailyReviewDialog(ctx, w).exec()

    def weekly_review() -> None:
        w.navigate("goals")
        w.page("goals").show_weekly_review()

    def rebuild_search() -> None:
        n = ctx.search.rebuild()
        w.toast.show_message(f"Search index rebuilt ({n} records)")

    def new_project() -> None:
        from src.ui.pages.projects_dialog import ProjectDialog

        ProjectDialog(ctx, w).exec()

    commands = [
        Command("task.new", "New task", "Add a task due today", "Ctrl+Shift+T", "plus", w.quick_task,
                ("add", "todo", "create")),
        Command("note.new", "New note", "Write a note", "Ctrl+Shift+N", "notes", w.quick_note, ("add", "write")),
        Command("capture", "Quick capture", "Capture a task, idea, link or snippet to your Inbox", "Ctrl+Shift+Space",
                "inbox", w.quick_capture, ("idea", "inbox", "jot", "capture idea", "add link", "snippet")),
        Command("event.new", "New event", "Add something to your calendar", "", "calendar", new_event,
                ("appointment", "schedule", "meeting")),
        Command("reminder.new", "New reminder", "Get a nudge at a specific time", "", "bell", new_reminder,
                ("remind", "alarm", "nudge")),
        Command("project.new", "New project", "Start a project with tasks and milestones", "", "project", new_project),
        Command("focus.start", "Start focus session", "Start the focus timer", "Ctrl+Enter on Focus", "study",
                start_focus, ("pomodoro", "timer", "study", "concentrate")),
        Command("review.daily", "Start daily review", "Reflect on today", "", "moon", daily_review,
                ("end of day", "journal", "reflection")),
        Command("review.weekly", "Start weekly review", "Look back at the week and plan the next", "", "goals",
                weekly_review, ("week", "plan", "retrospective")),
        Command("notifications", "Show notifications", "Reminders due now and coming up", "", "bell",
                lambda: w.show_notifications(), ("reminders", "alerts")),
        Command("sidebar.toggle", "Collapse or expand the sidebar", "", "Ctrl+B", "sidebar",
                lambda: w.set_sidebar_collapsed(not w._collapsed)),
        Command("shortcuts", "Keyboard shortcuts", "Every shortcut in one list", "F1", "keyboard", w.show_shortcuts),
        Command("search.rebuild", "Rebuild search index", "Re-index every record (rarely needed)", "", "refresh",
                rebuild_search, ("reindex", "search")),
    ]
    for cmd in commands:
        add(cmd)
    for theme_id, t in THEMES.items():
        add(Command(f"theme.{theme_id}", f"Switch theme: {t.name}", t.description, icon="sparkle",
                    run=lambda tid=theme_id: (ctx.settings.set("theme", tid), bus.notify("settings")),
                    keywords=("theme", "appearance", "dark", "light", "colour", "color"), group="Appearance"))

    # -- openers ---------------------------------------------------------------------------
    def open_task(task_id: int) -> None:
        from src.ui.dialogs import TaskDialog

        task = ctx.tasks.get(task_id)
        if task:
            TaskDialog(ctx, w, task).exec()

    def open_note(note_id: int) -> None:
        w.navigate("notes")
        w.page("notes").open_note(note_id)

    def open_event(event_id: int) -> None:
        from src.ui.pages.calendar import EventDialog

        event = ctx.schedule.get_event(event_id)
        if event:
            EventDialog(ctx, w, event).exec()

    def open_goal(goal_id: int) -> None:
        w.navigate("goals")
        w.page("goals").open_goal(goal_id)

    def open_exam(exam_id: int) -> None:
        w.navigate("exams")
        w.page("exams").open_exam(exam_id)

    def open_chapter(chapter_id: int) -> None:
        chapter = ctx.exams.get_chapter(chapter_id)
        if chapter:
            open_exam(chapter.exam_id)

    def open_mistake(_mistake_id: int) -> None:
        w.navigate("exams")
        w.page("exams").show_mistakes()

    def open_project(project_id: int) -> None:
        if registry.get("projects") is not None:
            w.navigate("projects")
            page = w.page("projects")
            if hasattr(page, "open_project"):
                page.open_project(project_id)
                return
        from src.ui.pages.projects_dialog import ProjectDialog

        project = ctx.projects.get(project_id)
        if project:
            ProjectDialog(ctx, w, project).exec()

    def open_reminder(reminder_id: int) -> None:
        from src.ui.shell.reminder_dialog import ReminderDialog

        reminder = ctx.reminders.get(reminder_id)
        if reminder:
            ReminderDialog(ctx, w, reminder=reminder).exec()

    for kind, fn in (("task", open_task), ("note", open_note), ("event", open_event), ("goal", open_goal),
                     ("exam", open_exam), ("chapter", open_chapter), ("mistake", open_mistake),
                     ("project", open_project), ("reminder", open_reminder),
                     ("inbox", lambda _id: w.navigate("inbox")), ("habit", lambda _id: w.navigate("habits"))):
        w.openers.register(kind, fn)
