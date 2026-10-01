"""Daily and weekly review summaries, built only from stored records.

Language is deliberately neutral: unfinished work is "still open" or "carried
over", never a failure. Suggested priorities are simple, explained rules over
your own data (overdue high-priority tasks, the nearest exam, goals with a
target date and no progress recently), and are labelled as suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from src.services.dates import iso, today


@dataclass
class DaySummary:
    day: date
    completed: list[str]
    still_open: list[str]
    overdue: int
    study_minutes: int
    study_sessions: int
    habits_done: int
    habits_scheduled: int
    events: list[str]


def day_summary(ctx, day: date) -> DaySummary:
    overdue, due = ctx.tasks.for_day(day)
    completed_rows = ctx.db.query(
        "SELECT title FROM tasks WHERE substr(completed_at, 1, 10) = ? ORDER BY completed_at", (iso(day),))
    sessions = ctx.db.query_one("SELECT COUNT(*), COALESCE(SUM(actual_seconds), 0) FROM study_sessions WHERE date = ?",
                                (iso(day),))
    habits = ctx.habits.scheduled_on(day)
    done_habits = ctx.habits.done_on(day)
    events = [f"{i.start_time + ' ' if i.start_time else ''}{i.title}" for i in ctx.schedule.day_agenda(day)]
    return DaySummary(
        day=day,
        completed=[r[0] for r in completed_rows],
        still_open=[t.title for t in due if not t.done],
        overdue=len(overdue),
        study_minutes=int(sessions[1]) // 60,
        study_sessions=int(sessions[0]),
        habits_done=sum(1 for h in habits if h.id in done_habits),
        habits_scheduled=len(habits),
        events=events,
    )


@dataclass
class WeekSummary:
    start: date
    end: date
    tasks_completed: int
    tasks_carried_over: list[str]
    study_minutes: int
    study_by_kind: dict[str, int]
    revisions: int
    tests_taken: int
    goal_updates: list[str]
    project_output: list[str]
    habit_rates: list[tuple[str, int, int]]  # name, done, scheduled
    next_week: list[str]
    suggestions: list[tuple[str, str]] = field(default_factory=list)  # (suggestion, why)


def week_summary(ctx, start: date) -> WeekSummary:
    end = start + timedelta(days=6)
    s, e = iso(start), iso(end)
    q = ctx.db.query
    completed = int(ctx.db.scalar(
        "SELECT COUNT(*) FROM tasks WHERE substr(completed_at, 1, 10) BETWEEN ? AND ?", (s, e), 0))
    carried = [r[0] for r in q(
        "SELECT title FROM tasks WHERE completed_at IS NULL AND due_date BETWEEN ? AND ? ORDER BY due_date", (s, e))]
    by_kind = {r[0]: int(r[1]) // 60 for r in q(
        "SELECT kind, SUM(actual_seconds) FROM study_sessions WHERE date BETWEEN ? AND ? GROUP BY kind", (s, e))}
    revisions = int(ctx.db.scalar("SELECT COUNT(*) FROM revision_logs WHERE date BETWEEN ? AND ?", (s, e), 0))
    tests = int(ctx.db.scalar("SELECT COUNT(*) FROM mock_tests WHERE date BETWEEN ? AND ?", (s, e), 0))
    if ctx.db.scalar("SELECT 1 FROM sqlite_master WHERE name = 'sf_attempts'"):
        tests += int(ctx.db.scalar("SELECT COUNT(*) FROM sf_attempts WHERE status != 'in_progress' AND "
                                   "substr(submitted_at, 1, 10) BETWEEN ? AND ?", (s, e), 0))
    goal_updates = [f"{r[0]}: {r[1]:g}" + (f" — {r[2]}" if r[2] else "") for r in q(
        "SELECT g.title, p.value, p.note FROM goal_progress p JOIN goals g ON g.id = p.goal_id "
        "WHERE p.date BETWEEN ? AND ? ORDER BY p.date", (s, e))]
    project_output = [f"{r[0]}: {r[1]}" for r in q(
        "SELECT p.name, CASE l.kind WHEN 'release' THEN 'released ' || l.version WHEN 'time' THEN l.minutes || ' min' "
        "ELSE substr(l.text, 1, 80) END FROM project_logs l JOIN projects p ON p.id = l.project_id "
        "WHERE l.date BETWEEN ? AND ? ORDER BY l.date", (s, e))]
    project_output += [f"{r[0]}: completed “{r[1]}”" for r in q(
        "SELECT p.name, t.title FROM tasks t JOIN projects p ON p.id = t.project_id "
        "WHERE substr(t.completed_at, 1, 10) BETWEEN ? AND ?", (s, e))]
    habit_rates = []
    for habit in ctx.habits.list():
        done, scheduled = ctx.habits.rate(habit, start, end, min(end, today()))
        if scheduled:
            habit_rates.append((habit.name, done, scheduled))
    nxt_start, nxt_end = end + timedelta(days=1), end + timedelta(days=7)
    agenda = ctx.schedule.agenda(nxt_start, nxt_end, include_tasks=False)
    next_week = [f"{d:%a %d %b}: {i.title}" for d in sorted(agenda) for i in agenda[d]
                 if i.kind in ("exam", "deadline", "event")][:12]
    summary = WeekSummary(start, end, completed, carried, sum(by_kind.values()), by_kind, revisions, tests,
                          goal_updates, project_output, habit_rates, next_week)
    summary.suggestions = suggest_priorities(ctx, end)
    return summary


def suggest_priorities(ctx, ref: date) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for t in ctx.tasks.list("overdue", ref=ref + timedelta(days=1), sort="priority", limit=3):
        if t.priority == 2:
            out.append((f"Finish or reschedule “{t.title}”", "High priority and past its due date."))
    for exam in ctx.exams.upcoming(ref, ref + timedelta(days=21))[:2]:
        if exam.chapter_total and exam.chapter_ready < exam.chapter_total:
            out.append((f"Revise for {exam.title}",
                        f"{exam.chapter_total - exam.chapter_ready} of {exam.chapter_total} chapters not revised yet; "
                        f"exam on {exam.day:%d %b}."))
    cutoff = iso(ref - timedelta(days=14))
    for row in ctx.db.query(
            "SELECT g.title FROM goals g WHERE g.status = 'active' AND g.target_date IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM goal_progress p WHERE p.goal_id = g.id AND p.date >= ?) ORDER BY g.target_date LIMIT 2",
            (cutoff,)):
        out.append((f"Take one step towards “{row[0]}”", "No progress recorded in the last two weeks."))
    return out[:6]
