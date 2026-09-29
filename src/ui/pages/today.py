from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from src.services.dates import (
    countdown_text,
    format_duration,
    format_long_date,
    format_time,
    greeting,
    now,
    today,
    week_start,
)
from src.services.quickadd import parse_quick_task
from src.ui.bus import bus
from src.ui.dialogs import DailyReviewDialog, ManualStudyDialog, QuickNoteDialog, TaskDialog
from src.ui.pages.base import Page
from src.ui.task_actions import TaskActions
from src.ui.theme import KIND_COLORS
from src.ui.widgets.common import (
    Card,
    EmptyState,
    ResponsiveGrid,
    RoundCheck,
    ThinProgress,
    button,
    chip,
    clear_layout,
    guarded,
    label,
    scroll_wrap,
)
from src.ui.widgets.task_row import TaskRow, connect_row

KIND_TONES = {"event": "blue", "class": "accent", "exam": "terracotta", "deadline": "amber", "task": ""}
KIND_NAMES = {"event": "Event", "class": "Class", "exam": "Exam", "deadline": "Deadline", "task": "Task"}


class TodayPage(Page):
    domains = ("tasks", "habits", "goals", "journal", "schedule", "study", "exams", "settings", "subjects")
    title = "Today"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.actions = TaskActions(ctx, self, lambda t, a, c: self.toast(t, a, c))
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(34, 28, 34, 28)
        outer.setSpacing(18)
        self.root.addWidget(scroll_wrap(content))

        # greeting row
        top = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(2)
        self.greeting = label("", "greeting")
        self.date_label = label("", "subtitle")
        text.addWidget(self.greeting)
        text.addWidget(self.date_label)
        top.addLayout(text, 1)
        self.clock = label("", "clock")
        self.clock.setAccessibleName("Current time")
        top.addWidget(self.clock, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(top)

        # intention
        intent_row = QHBoxLayout()
        intent_row.setSpacing(10)
        intent_row.addWidget(label("Today's intention", "muted"))
        self.intention = QLineEdit()
        self.intention.setProperty("flat", True)
        self.intention.setPlaceholderText("One thing that would make today feel good…")
        self.intention.setAccessibleName("Today's intention")
        self.intention.setMaxLength(300)
        self.intention.editingFinished.connect(self._save_intention)
        intent_row.addWidget(self.intention, 1)
        outer.addLayout(intent_row)

        # quick actions
        qa = QHBoxLayout()
        qa.setSpacing(8)
        qa.addWidget(button("Task", "", "plus", lambda: TaskDialog(ctx, self, default_due=today()).exec(),
                            "Add a task due today (Ctrl+N)"))
        qa.addWidget(button("Quick note", "", "notes", self._quick_note, "Capture a note (Ctrl+Shift+N)"))
        qa.addWidget(button("Start focus", "", "study", self._start_focus, "Open the focus timer"))
        qa.addWidget(button("Log study", "", "clock", lambda: ManualStudyDialog(ctx, self).exec(),
                            "Record a study session you did without the timer"))
        qa.addStretch(1)
        self.review_btn = button("End-of-day review", "ghost", "moon", self._review)
        qa.addWidget(self.review_btn)
        outer.addLayout(qa)

        # cards
        self.grid = ResponsiveGrid((780, 1560))
        self.tasks_card = Card("Today's tasks", "tasks")
        self.schedule_card = Card("Schedule", "calendar")
        self.habits_card = Card("Habits", "habits")
        self.study_card = Card("Study", "study")
        self.goals_card = Card("Goals", "goals")
        self.upcoming_card = Card("Coming up", "flag")
        for card in (self.tasks_card, self.schedule_card, self.habits_card, self.study_card,
                     self.upcoming_card, self.goals_card):
            self.grid.add(card)
        self.tasks_card.add_action(button("All tasks", "link", on_click=lambda: self.main.navigate("tasks")))
        self.schedule_card.add_action(button("Calendar", "link", on_click=lambda: self.main.navigate("calendar")))
        self.habits_card.add_action(button("Manage", "link", on_click=lambda: self.main.navigate("habits")))
        self.study_card.add_action(button("History", "link", on_click=lambda: self.main.navigate("study")))
        self.goals_card.add_action(button("All goals", "link", on_click=lambda: self.main.navigate("goals")))
        self.upcoming_card.add_action(button("Exams", "link", on_click=lambda: self.main.navigate("exams")))
        outer.addWidget(self.grid)
        outer.addStretch(1)

        self._clock_timer = QTimer(self)
        self._clock_timer.setSingleShot(True)
        self._clock_timer.timeout.connect(self._tick_clock)

    # -- clock -------------------------------------------------------------
    def _tick_clock(self) -> None:
        current = now()
        self.clock.setText(format_time(current.time(), self.clock24) if self.ctx.settings.get("show_clock") else "")
        self.greeting.setText(self._greeting_text(current))
        # Wake exactly at the next minute boundary (no per-second polling).
        ms = (60 - current.second) * 1000 - current.microsecond // 1000 + 50
        if self.isVisible():
            self._clock_timer.start(max(1000, ms))

    def _greeting_text(self, current: datetime) -> str:
        name = str(self.ctx.settings.get("user_name") or "").strip()
        return f"{greeting(current)}, {name}" if name else greeting(current)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._tick_clock()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._clock_timer.stop()
        super().hideEvent(event)

    # -- refresh -------------------------------------------------------------
    def refresh(self) -> None:
        day = today()
        self.date_label.setText(format_long_date(day, self.date_style))
        self._tick_clock()
        entry = self.ctx.journal.get(day)
        if not self.intention.hasFocus():
            self.intention.setText(entry.intention)
        self.review_btn.setText("Edit today's review" if (entry.reflection or entry.went_well) else "End-of-day review")
        self._fill_tasks(day)
        self._fill_schedule(day)
        self._fill_habits(day)
        self._fill_study(day)
        self._fill_goals()
        self._fill_upcoming(day)

    def _fill_tasks(self, day) -> None:
        body = self.tasks_card.body
        clear_layout(body)
        overdue, due = self.ctx.tasks.for_day(day)
        done = sum(1 for t in due if t.done)
        if not overdue and not due:
            body.addWidget(EmptyState("tasks", "Nothing due today",
                                      "Add a task for today, or pick one from your list.", compact=True))
        else:
            if due:
                row = QHBoxLayout()
                row.addWidget(label(f"{done} of {len(due)} done", "muted"))
                row.addStretch(1)
                body.addLayout(row)
                bar = ThinProgress(done / len(due))
                body.addWidget(bar)
            if overdue:
                body.addWidget(label(f"Overdue ({len(overdue)})", "danger"))
                for task in overdue[:5]:
                    body.addWidget(self._task_row(task, day))
                if len(overdue) > 5:
                    body.addWidget(button(f"See all {len(overdue)} overdue", "link",
                                          on_click=lambda: self._open_tasks("overdue")))
                if due:
                    body.addWidget(label("Due today", "muted"))
            for task in due[:10]:
                body.addWidget(self._task_row(task, day))
            if len(due) > 10:
                body.addWidget(button(f"See all {len(due)} tasks for today", "link",
                                      on_click=lambda: self._open_tasks("today")))
        quick = QLineEdit()
        quick.setPlaceholderText("Add a task for today…")
        quick.setAccessibleName("Add a task for today")
        quick.returnPressed.connect(lambda: self._quick_task(quick))
        body.addWidget(quick)

    def _task_row(self, task, day) -> TaskRow:
        row = TaskRow(task, day, clock24=self.clock24, date_style=self.date_style, compact=True)
        connect_row(row, self.actions.toggle, self.actions.edit, self.actions.delete)
        return row

    def _open_tasks(self, filter_name: str) -> None:
        page = self.main.page("tasks")
        page.filters.set_current(filter_name)  # type: ignore[attr-defined]
        page.mark_dirty()
        self.main.navigate("tasks")

    def _quick_task(self, edit: QLineEdit) -> None:
        text = edit.text().strip()
        if not text:
            return
        parsed = parse_quick_task(text, today())

        def run() -> None:
            self.ctx.tasks.create(parsed.title, due_date=parsed.due_date or today(), priority=parsed.priority,
                                  category=parsed.category)
            bus.notify("tasks")

        guarded(self, run, "Couldn't add the task")

    def _fill_schedule(self, day) -> None:
        body = self.schedule_card.body
        clear_layout(body)
        items = [i for i in self.ctx.schedule.day_agenda(day) if i.kind != "task"]
        if not items:
            body.addWidget(EmptyState("calendar", "Nothing scheduled",
                                      "Classes, events and exams for today will show here.",
                                      [("Open calendar", lambda: self.main.navigate("calendar"))], compact=True))
            return
        current = now().strftime("%H:%M")
        for item in items[:10]:
            row = QHBoxLayout()
            row.setSpacing(10)
            if item.start_time:
                when = format_time(item.start_time, self.clock24)
                if item.end_time:
                    when += f"–{format_time(item.end_time, self.clock24)}"
            else:
                when = "All day"
            time_lbl = label(when, "muted")
            time_lbl.setMinimumWidth(110 if not self.clock24 else 90)
            row.addWidget(time_lbl)
            title = label(item.title)
            title.setWordWrap(True)
            finished = item.end_time is not None and item.end_time <= current
            if finished:
                title.setProperty("role", "caption")
                title.setToolTip("Finished")
            row.addWidget(title, 1)
            row.addWidget(chip(KIND_NAMES[item.kind], KIND_TONES[item.kind]))
            body.addLayout(row)
        if len(items) > 10:
            body.addWidget(label(f"+{len(items) - 10} more in the calendar", "caption"))

    def _fill_habits(self, day) -> None:
        body = self.habits_card.body
        clear_layout(body)
        habits = self.ctx.habits.scheduled_on(day)
        if not habits:
            has_any = bool(self.ctx.habits.list())
            body.addWidget(EmptyState(
                "habits",
                "No habits for today" if has_any else "No habits yet",
                "None of your habits are scheduled today." if has_any else
                "Small routines you'd like to keep — reading, exercise, water…",
                [] if has_any else [("Create a habit", lambda: self.main.navigate("habits"))], compact=True))
            return
        done_ids = self.ctx.habits.done_on(day)
        done_n = sum(1 for h in habits if h.id in done_ids)
        body.addWidget(label(f"{done_n} of {len(habits)} done today", "muted"))
        for habit in habits:
            row = QHBoxLayout()
            row.setSpacing(10)
            check = RoundCheck(habit.id in done_ids, 18, f"Done today: {habit.name}")
            check.toggled.connect(lambda on, hid=habit.id: self._toggle_habit(hid, on))
            row.addWidget(check)
            row.addWidget(label(habit.name), 1)
            streak = self.ctx.habits.streak_info(habit, day).current
            if streak:
                s = label(f"{streak}-day streak" if habit.weekdays == 127 else f"streak {streak}", "caption")
                s.setToolTip("Consecutive scheduled days completed")
                row.addWidget(s)
            body.addLayout(row)

    def _toggle_habit(self, habit_id: int, done: bool) -> None:
        def run() -> None:
            self.ctx.habits.set_done(habit_id, today(), done)
            bus.notify("habits")

        guarded(self, run, "Couldn't update the habit")

    def _fill_study(self, day) -> None:
        body = self.study_card.body
        clear_layout(body)
        today_secs = self.ctx.study.seconds_on(day)
        week_from = week_start(day, self.week_start)
        week_secs = self.ctx.study.seconds_between(week_from, day)
        row = QHBoxLayout()
        row.setSpacing(28)
        for value, caption in ((today_secs, "today"), (week_secs, "this week")):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(format_duration(value) if value else "0 min", "metric"))
            col.addWidget(label(caption, "metricLabel"))
            row.addLayout(col)
        row.addStretch(1)
        body.addLayout(row)
        study_page = self.main.pages.get("study")
        running = getattr(study_page, "timer_summary", lambda: "")() if study_page else ""
        if running:
            body.addWidget(label(running, "success"))
        elif not today_secs:
            body.addWidget(label("No study recorded today yet. A short focus session is a fine start.", "muted", wrap=True))
        actions = QHBoxLayout()
        actions.addWidget(button("Open timer" if running else "Start focus", "primary", "play", self._start_focus))
        actions.addWidget(button("Log session", "ghost", on_click=lambda: ManualStudyDialog(self.ctx, self).exec()))
        actions.addStretch(1)
        body.addLayout(actions)

    def _fill_goals(self) -> None:
        body = self.goals_card.body
        clear_layout(body)
        goals = self.ctx.goals.list("active")
        if not goals:
            body.addWidget(EmptyState("goals", "No active goals",
                                      "Set a goal you're working towards and track progress over time.",
                                      [("Add a goal", lambda: self._go_new("goals"))], compact=True))
            return
        for goal in goals[:4]:
            row = QHBoxLayout()
            row.addWidget(label(goal.title), 1)
            if goal.fraction is not None:
                row.addWidget(label(f"{goal.current_value:g} / {goal.target_value:g} {goal.unit}".strip(), "caption"))
            elif goal.linked_tasks:
                row.addWidget(label(f"{goal.linked_done}/{goal.linked_tasks} linked tasks", "caption"))
            body.addLayout(row)
            if goal.fraction is not None:
                body.addWidget(ThinProgress(goal.fraction, "blue"))
        if len(goals) > 4:
            body.addWidget(label(f"+{len(goals) - 4} more active goals", "caption"))

    def _fill_upcoming(self, day) -> None:
        body = self.upcoming_card.body
        clear_layout(body)
        horizon = day + timedelta(days=21)
        exams = self.ctx.exams.upcoming(day, horizon)
        deadlines = self.ctx.schedule.upcoming_deadlines(day, horizon)
        revision_due = self.ctx.exams.revision_queue(day)
        entries: list[tuple] = [(e.day, "exam", e.title, e.subject_name or "") for e in exams]
        from datetime import date as _date

        entries += [(_date.fromisoformat(d.date), "deadline", d.title, d.subject_name or d.category) for d in deadlines]
        entries.sort(key=lambda x: x[0])
        if revision_due:
            r = QHBoxLayout()
            r.addWidget(label(f"{len(revision_due)} chapter{'s' if len(revision_due) != 1 else ''} to revise today", "warning"), 1)
            r.addWidget(button("Revise", "link", on_click=lambda: self._open_exams_revision()))
            body.addLayout(r)
        if not entries:
            if not revision_due:
                body.addWidget(EmptyState("flag", "Nothing in the next three weeks",
                                          "Exams and deadlines you add will be counted down here.",
                                          [("Add an exam", lambda: self._go_new("exams"))], compact=True))
            return
        for when, kind, title, detail in entries[:6]:
            row = QHBoxLayout()
            row.setSpacing(10)
            count = label(countdown_text(when, day), "muted")
            count.setMinimumWidth(80)
            row.addWidget(count)
            t = label(title + (f" · {detail}" if detail else ""))
            t.setWordWrap(True)
            row.addWidget(t, 1)
            row.addWidget(chip(KIND_NAMES[kind], KIND_TONES[kind]))
            body.addLayout(row)

    def _open_exams_revision(self) -> None:
        page = self.main.page("exams")
        if hasattr(page, "show_revision"):
            page.show_revision()  # type: ignore[attr-defined]
        self.main.navigate("exams")

    def _go_new(self, key: str) -> None:
        self.main.navigate(key)
        self.main.page(key).new_item()

    # -- actions ------------------------------------------------------------
    def _save_intention(self) -> None:
        text = self.intention.text().strip()
        if text == self.ctx.journal.get(today()).intention:
            return

        def run() -> None:
            self.ctx.journal.save(today(), intention=text)

        if guarded(self, run, "Couldn't save your intention") and text:
            self.toast("Intention saved")

    def _quick_note(self) -> None:
        if QuickNoteDialog(self.ctx, self).exec():
            self.toast("Note saved", "Open notes", lambda: self.main.navigate("notes"))

    def _start_focus(self) -> None:
        self.main.navigate("study")

    def _review(self) -> None:
        self._save_intention()
        if DailyReviewDialog(self.ctx, self).exec():
            self.toast("Review saved. Rest well.")

    def new_item(self) -> None:
        TaskDialog(self.ctx, self, default_due=today()).exec()

    def can_leave(self) -> bool:
        self._save_intention()
        return True
