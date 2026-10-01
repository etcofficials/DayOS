"""Synthetic demo records for screenshots and manual layout review (development tool only).

Never used by the application itself, never run against a real data folder, and
never bundled into the executable. Every record is obviously fictional.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


def fill(ctx) -> None:
    if ctx.tasks.db.scalar("SELECT COUNT(*) FROM tasks", default=0):
        return  # already filled
    today = date.today()
    maths = ctx.subjects.get_or_create("Mathematics")
    science = ctx.subjects.get_or_create("Science")
    english = ctx.subjects.get_or_create("English")
    ctx.tasks.create("Finish quadratic equations worksheet", due_date=today, priority=2, subject_id=maths,
                     estimate_minutes=40)
    ctx.tasks.create("Read chapter 4: Carbon compounds", due_date=today, subject_id=science, estimate_minutes=30)
    ctx.tasks.create("Draft the book review introduction", due_date=today, subject_id=english, due_time="17:30")
    done = ctx.tasks.create("Pack lab notebook", due_date=today)
    ctx.tasks.set_completed(done, True)
    ctx.tasks.create("Email club secretary about Friday", due_date=today + timedelta(days=1))
    ctx.tasks.create("Revise trigonometry identities", due_date=today - timedelta(days=1), subject_id=maths)
    for wd, (title, start, end, subj) in enumerate([
        ("Mathematics", "09:00", "09:45", maths), ("Science", "10:00", "10:45", science),
        ("English", "11:15", "12:00", english), ("Mathematics", "09:00", "09:45", maths),
        ("Science", "12:30", "13:15", science),
    ]):
        ctx.schedule.create_entry(title=title, subject_id=subj, weekday=wd, start_time=start, end_time=end,
                                  location="Room 12")
    ctx.schedule.create_event(title="Library study group", date=today, start_time="16:00", end_time="17:00")
    ctx.schedule.create_event(title="Science project due", kind="deadline", date=today + timedelta(days=5))
    exam = ctx.exams.create_exam(title="Mathematics mid-term", subject_id=maths, exam_date=today + timedelta(days=12))
    ctx.exams.add_chapters(exam, ["Real numbers", "Polynomials", "Quadratic equations", "Trigonometry"])
    ctx.exams.create_exam(title="Science unit test", subject_id=science, exam_date=today + timedelta(days=19))
    for name in ("Read 20 minutes", "Evening walk", "Plan tomorrow"):
        hid = ctx.habits.create(name, start=today - timedelta(days=20))
        for back in range(1, 15):
            if back % 3:
                ctx.habits.set_done(hid, today - timedelta(days=back), True)
    goal = ctx.goals.create("Score 85% in mathematics", target_value=85, unit="%", category="School",
                            target_date=today + timedelta(days=60))
    ctx.goals.log_progress(goal, 72, "Last test")
    ctx.notes.create("Trig identities", "sin²θ + cos²θ = 1\n1 + tan²θ = sec²θ", "maths, formulas", pinned=True)
    ctx.notes.create("Book review ideas", "Theme of belonging; compare the two narrators.", "english")
    from src.repositories.study import new_session_uid

    for back in range(1, 8):
        ctx.study.record(session_uid=new_session_uid(), subject_id=[maths, science, english][back % 3],
                         started_at=datetime.combine(today - timedelta(days=back), datetime.min.time()).replace(hour=18),
                         actual_seconds=1500 + 300 * (back % 4), planned_minutes=25)
    ctx.journal.save(today, intention="Steady progress on maths, then an early night.")
