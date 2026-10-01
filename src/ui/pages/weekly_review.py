"""Weekly review: a factual look back at the week (from your records) plus your own notes."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from src.services.dates import format_date, format_duration, today, week_start
from src.services.reviews import week_summary
from src.ui.bus import bus
from src.ui.widgets.common import Card, ThinProgress, button, clear_layout, guarded, label, tool_button

KIND_NAMES = {"study": "Study", "practice": "Practice", "work": "Work", "reading": "Reading", "other": "Other"}


class WeeklyReviewView(QWidget):
    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        self.anchor = today()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(14)
        bar = QHBoxLayout()
        bar.addWidget(tool_button("chev-left", "Previous week", lambda: self._step(-1)))
        bar.addWidget(tool_button("chev-right", "Next week", lambda: self._step(1)))
        self.title = label("", "section")
        bar.addWidget(self.title)
        bar.addWidget(button("This week", "ghost", on_click=self._this_week))
        bar.addStretch(1)
        lay.addLayout(bar)
        lay.addWidget(label("Everything below comes from what you recorded this week. Open items simply carry over; "
                            "nothing here is a score.", "caption", wrap=True))
        self.grid = QGridLayout()
        self.grid.setSpacing(14)
        lay.addLayout(self.grid)
        notes = Card("Your notes on the week", "edit")
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(6)
        self.fields: dict[str, QPlainTextEdit] = {}
        for i, (key, title, hint) in enumerate((
                ("wins", "What went well", "Wins, however small"),
                ("challenges", "What was hard", "What got in the way?"),
                ("priorities", "Priorities for next week", "Two or three things that matter most"),
                ("notes", "Anything else", "Notes for future you"))):
            form.addWidget(label(title, "muted"), (i // 2) * 2, i % 2)
            edit = QPlainTextEdit()
            edit.setPlaceholderText(hint)
            edit.setFixedHeight(76)
            edit.setAccessibleName(title)
            self.fields[key] = edit
            form.addWidget(edit, (i // 2) * 2 + 1, i % 2)
        notes.body.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        self.save_btn = button("Save weekly review", "primary", "check", self.save)
        row.addWidget(self.save_btn)
        notes.body.addLayout(row)
        lay.addWidget(notes)
        lay.addStretch(1)

    def _start(self) -> date:
        return week_start(self.anchor, self.page.week_start)

    def _step(self, direction: int) -> None:
        self.anchor += timedelta(days=7 * direction)
        self.refresh()

    def _this_week(self) -> None:
        self.anchor = today()
        self.refresh()

    def refresh(self) -> None:
        start = self._start()
        style = self.page.date_style
        self.title.setText(f"Week of {format_date(start, style)} – {format_date(start + timedelta(days=6), style)}")
        s = week_summary(self.ctx, start)
        clear_layout(self.grid)

        def card(title: str, icon: str, lines: list[str], empty: str) -> Card:
            c = Card(title, icon, margins=16)
            if lines:
                for line in lines[:8]:
                    c.body.addWidget(label(f"• {line}", "", wrap=True))
                if len(lines) > 8:
                    c.body.addWidget(label(f"…and {len(lines) - 8} more", "caption"))
            else:
                c.body.addWidget(label(empty, "muted", wrap=True))
            return c

        tasks = Card("Tasks", "tasks", margins=16)
        tasks.body.addWidget(label(f"{s.tasks_completed}", "metric"))
        tasks.body.addWidget(label("completed this week", "metricLabel"))
        if s.tasks_carried_over:
            tasks.body.addWidget(label(f"{len(s.tasks_carried_over)} still open from this week (they carry over):",
                                       "caption", wrap=True))
            for t in s.tasks_carried_over[:5]:
                tasks.body.addWidget(label(f"• {t}", "", wrap=True))
        learning = Card("Learning & focus", "study", margins=16)
        learning.body.addWidget(label(format_duration(s.study_minutes * 60) if s.study_minutes else "0 min", "metric"))
        learning.body.addWidget(label("focused time", "metricLabel"))
        if s.study_by_kind:
            for kind, minutes in sorted(s.study_by_kind.items(), key=lambda x: -x[1]):
                learning.body.addWidget(label(f"{KIND_NAMES.get(kind, kind)}: {format_duration(minutes * 60)}", "caption"))
        learning.body.addWidget(label(f"{s.revisions} revision session(s) · {s.tests_taken} test(s)", "caption"))
        habits = Card("Habit consistency", "habits", margins=16)
        if s.habit_rates:
            for name, done, scheduled in s.habit_rates[:6]:
                row = QHBoxLayout()
                row.addWidget(label(name, ""), 1)
                row.addWidget(label(f"{done}/{scheduled}", "caption"))
                habits.body.addLayout(row)
                habits.body.addWidget(ThinProgress(done / scheduled if scheduled else 0, "progress", 5))
        else:
            habits.body.addWidget(label("No habits were scheduled this week.", "muted", wrap=True))
        goals = card("Goal progress", "goals", s.goal_updates, "No goal progress was logged this week.")
        projects = card("Project output", "project", s.project_output, "No project activity recorded this week.")
        upcoming = card("Coming up next week", "calendar", s.next_week, "Nothing scheduled for next week yet.")
        sugg = Card("Suggested priorities", "sparkle", margins=16)
        if s.suggestions:
            sugg.body.addWidget(label("Simple suggestions from your records. Use them or ignore them.", "caption", wrap=True))
            for text, why in s.suggestions:
                sugg.body.addWidget(label(text, "heading", wrap=True))
                sugg.body.addWidget(label(why, "caption", wrap=True))
        else:
            sugg.body.addWidget(label("Nothing stands out. Choose what feels most useful.", "muted", wrap=True))
        cards = [tasks, learning, habits, goals, projects, upcoming, sugg]
        cols = 3 if self.width() > 1100 else 2
        for i, c in enumerate(cards):
            self.grid.addWidget(c, i // cols, i % cols)
        for col in range(3):
            self.grid.setColumnStretch(col, 1 if col < cols else 0)
        review = self.ctx.weekly.get(start)
        for key, edit in self.fields.items():
            edit.setPlainText(getattr(review, key))

    def save(self) -> None:
        start = self._start()
        values = {k: e.toPlainText() for k, e in self.fields.items()}
        if guarded(self, lambda: self.ctx.weekly.save(start, **values), "Couldn't save the weekly review"):
            bus.notify("journal")
            self.page.toast("Weekly review saved")
