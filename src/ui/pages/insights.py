from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from src.services import stats
from src.services.dates import format_date, format_duration, today
from src.services.streaks import completion_rate
from src.ui.pages.base import Page
from src.ui.widgets.charts import BarChart, HBarList, LineChart
from src.ui.widgets.common import (
    Card,
    EmptyState,
    PageHeader,
    ResponsiveGrid,
    SegmentBar,
    clear_layout,
    label,
    scroll_wrap,
)

RANGES = [("7", "7 days"), ("30", "30 days"), ("90", "90 days"), ("365", "12 months")]
ACTIVITY_LABELS = {"task": "Task", "study": "Study", "goal": "Goal", "test": "Test", "revision": "Revision", "note": "Note"}


def _minutes_fmt(v: float) -> str:
    return f"{v / 60:.1f}h" if v >= 120 else f"{v:.0f}m"


class InsightsPage(Page):
    domains = ("tasks", "study", "habits", "goals", "exams", "notes", "subjects", "settings")
    title = "Insights"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.root.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(34, 28, 34, 28)
        outer.setSpacing(16)
        self.header = PageHeader("Insights", "")
        self.range = SegmentBar(RANGES, "30")
        self.range.changed.connect(lambda _: self.refresh())
        self.header.add_action(self.range)
        outer.addWidget(self.header)
        outer.addWidget(label(
            "Everything here is counted from what you've recorded — no scores or rankings. "
            "Dates use your computer's local calendar.", "caption", wrap=True))

        self.summary = QHBoxLayout()
        self.summary.setSpacing(12)
        outer.addLayout(self.summary)

        self.grid = ResponsiveGrid((820, 1700))
        self.tasks_card = Card("Tasks completed", "tasks")
        self.study_card = Card("Study time", "study")
        self.subject_card = Card("Study by subject", "subject")
        self.habit_card = Card("Habit completion", "habits")
        self.tests_card = Card("Test scores", "chart")
        self.goals_card = Card("Goal progress", "goals")
        self.activity_card = Card("Recent activity", "clock")
        for card in (self.tasks_card, self.study_card, self.subject_card, self.habit_card, self.tests_card,
                     self.goals_card, self.activity_card):
            self.grid.add(card)
        self.tasks_chart = BarChart("accent", lambda v: f"{v:.0f}", integer=True)
        self.study_chart = BarChart("blue", _minutes_fmt)
        self.tasks_card.body.addWidget(self.tasks_chart)
        self.study_card.body.addWidget(self.study_chart)
        self.tasks_note = label("", "caption", wrap=True)
        self.study_note = label("", "caption", wrap=True)
        self.tasks_card.body.addWidget(self.tasks_note)
        self.study_card.body.addWidget(self.study_note)
        self.dynamic = {c: QVBoxLayout() for c in (self.subject_card, self.habit_card, self.tests_card,
                                                   self.goals_card, self.activity_card)}
        for card, lay in self.dynamic.items():
            card.body.addLayout(lay)
        outer.addWidget(self.grid)
        outer.addStretch(1)
        self.root.addWidget(scroll_wrap(content))

    def _period(self) -> tuple[date, date]:
        end = today()
        days = int(self.range.current())
        return end - timedelta(days=days - 1), end

    def refresh(self) -> None:
        start, end = self._period()
        db = self.ctx.db
        self.header.set_subtitle(f"{format_date(start, self.date_style)} – {format_date(end, self.date_style)}")

        # tasks
        t_daily = stats.tasks_completed_daily(db, start, end)
        t_buckets = stats.aggregate(t_daily, start, end, self.week_start)
        self.tasks_chart.set_data([(b.label, b.value) for b in t_buckets])
        t_sum = stats.tasks_summary(db, start, end)
        per = "day" if stats.bucket_kind(start, end) == "day" else "week"
        self.tasks_note.setText(
            f"{t_sum['completed']} completed and {t_sum['created']} added in this period · bars show tasks per {per}."
            + (f" {t_sum['overdue_now']} open task(s) are overdue right now." if t_sum["overdue_now"] else "")
        )

        # study
        s_daily = stats.study_daily_minutes(db, start, end)
        s_buckets = stats.aggregate(s_daily, start, end, self.week_start)
        self.study_chart.set_data([(b.label, b.value) for b in s_buckets])
        s_sum = stats.study_summary(db, start, end)
        avg = s_sum["seconds"] / s_sum["days"] if s_sum["days"] else 0
        self.study_note.setText(
            f"{format_duration(s_sum['seconds'])} across {s_sum['sessions']} session(s) on {s_sum['days']} day(s)"
            + (f" · about {format_duration(avg)} on days you studied." if s_sum["days"] else ".")
            + f" Bars show time per {per}."
        )

        self._fill_summary(t_sum, s_sum, start, end)
        self._fill_subjects(start, end)
        self._fill_habits(start, end)
        self._fill_tests(start, end)
        self._fill_goals()
        self._fill_activity()

    def _metric(self, value: str, caption: str) -> QWidget:
        from PySide6.QtWidgets import QFrame

        box = QFrame()
        box.setProperty("card", True)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(0)
        lay.addWidget(label(value, "metric"))
        lay.addWidget(label(caption, "metricLabel"))
        return box

    def _fill_summary(self, t_sum: dict, s_sum: dict, start: date, end: date) -> None:
        clear_layout(self.summary)
        done = eligible = 0
        for habit in self.ctx.habits.list():
            d, e = completion_rate(habit.weekdays, habit.start, self.ctx.habits.done_dates(habit.id), start, end, today())
            done += d
            eligible += e
        tests = self.ctx.exams.tests(start, end)
        revisions = self.ctx.exams.revisions_between(start, end)
        items = [
            (str(t_sum["completed"]), "tasks completed"),
            (format_duration(s_sum["seconds"]) if s_sum["seconds"] else "0 min", "studied"),
            (f"{round(100 * done / eligible)}%" if eligible else "–", "habit check-ins"),
            (str(revisions), "chapter revisions"),
            (f"{sum(t.percent for t in tests) / len(tests):.0f}%" if tests else "–", "average test score"),
        ]
        for value, caption in items:
            self.summary.addWidget(self._metric(value, caption), 1)

    def _fill_subjects(self, start: date, end: date) -> None:
        lay = self.dynamic[self.subject_card]
        clear_layout(lay)
        rows = self.ctx.study.by_subject(start, end)
        if not rows:
            lay.addWidget(EmptyState("subject", "No study sessions in this period", "", compact=True))
            return
        top = rows[0][1]
        total = sum(s for _, s in rows)
        bars = HBarList()
        bars.set_rows([(name, secs / top, f"{format_duration(secs)} · {round(100 * secs / total)}%", "blue")
                       for name, secs in rows[:10]])
        lay.addWidget(bars)

    def _fill_habits(self, start: date, end: date) -> None:
        lay = self.dynamic[self.habit_card]
        clear_layout(lay)
        habits = self.ctx.habits.list()
        if not habits:
            lay.addWidget(EmptyState("habits", "No habits to show", "", compact=True))
            return
        rows = []
        for habit in habits:
            d, e = completion_rate(habit.weekdays, habit.start, self.ctx.habits.done_dates(habit.id), start, end, today())
            rows.append((habit.name, d / e if e else 0.0, f"{d}/{e} days" if e else "not scheduled yet", "accent"))
        bars = HBarList()
        bars.set_rows(rows)
        lay.addWidget(bars)
        lay.addWidget(label("Completed scheduled days ÷ scheduled days so far (today counts once it's done).", "caption", wrap=True))

    def _fill_tests(self, start: date, end: date) -> None:
        lay = self.dynamic[self.tests_card]
        clear_layout(lay)
        tests = list(reversed(self.ctx.exams.tests(start, end)))
        if not tests:
            lay.addWidget(EmptyState("chart", "No test results in this period", "", compact=True))
            return
        chart = LineChart("terracotta")
        chart.set_points([(f"{date.fromisoformat(t.date).day}/{date.fromisoformat(t.date).month}", t.percent,
                           f"{t.title}{' · ' + t.subject_name if t.subject_name else ''}: {t.percent:.1f}%")
                          for t in tests[-30:]])
        lay.addWidget(chart)
        best = max(tests, key=lambda t: t.percent)
        lay.addWidget(label(f"{len(tests)} result(s) · highest {best.percent:.0f}% ({best.title})", "caption", wrap=True))

    def _fill_goals(self) -> None:
        lay = self.dynamic[self.goals_card]
        clear_layout(lay)
        goals = [g for g in self.ctx.goals.list("active")]
        measurable = [g for g in goals if g.fraction is not None]
        if not goals:
            lay.addWidget(EmptyState("goals", "No active goals", "", compact=True))
            return
        if measurable:
            bars = HBarList()
            bars.set_rows([(g.title, g.fraction or 0, f"{round((g.fraction or 0) * 100)}%", "blue") for g in measurable[:10]])
            lay.addWidget(bars)
        others = [g for g in goals if g.fraction is None]
        if others:
            lay.addWidget(label(
                f"{len(others)} goal(s) without a numeric target: " + ", ".join(
                    f"{g.title} ({g.linked_done}/{g.linked_tasks} linked tasks)" if g.linked_tasks else g.title
                    for g in others[:5]), "caption", wrap=True))

    def _fill_activity(self) -> None:
        lay = self.dynamic[self.activity_card]
        clear_layout(lay)
        items = stats.recent_activity(self.ctx.db, 12)
        if not items:
            lay.addWidget(EmptyState("clock", "Nothing recorded yet", "Your recent activity will appear here.", compact=True))
            return
        for ts, kind, text in items:
            row = QHBoxLayout()
            when = datetime.fromisoformat(ts)
            row.addWidget(label(f"{format_date(when.date(), self.date_style)}", "caption"))
            row.addWidget(label(text, "", wrap=True), 1)
            lay.addLayout(row)
