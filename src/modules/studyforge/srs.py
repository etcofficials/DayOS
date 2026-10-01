"""Spaced revision for topics and flashcards (an SM-2 style schedule, explained to the user).

Topic schedule
--------------
Every practice result is a score between 0 and 1 (fraction of marks on that
topic, a recall rating, or a flashcard grade).

* score ≥ 0.6 counts as a successful retrieval: the interval grows
  (1 day → 3 days → previous × ease), and ease rises a little for easy recalls;
* score < 0.6 is a lapse: the topic comes back tomorrow and ease drops;
* when an exam date is known, intervals are capped at half the days left, so
  topics keep coming back before the exam.

Mastery is a cautious *estimate*, never claimed after one correct answer:
"strong" needs at least three successful retrievals, overall accuracy ≥ 80 %
and practice spread over at least a week.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from src.modules.studyforge.models import Flashcard, TopicState
from src.services.dates import iso

PASS = 0.6
MIN_EASE = 1.3
MAX_INTERVAL = 180

MASTERY_LABELS = {
    "new": "Not practised yet",
    "learning": "Learning",
    "developing": "Developing",
    "strong": "Strong (estimate)",
}


def update_topic(state: TopicState, score: float, day: date, exam: date | None = None) -> TopicState:
    score = max(0.0, min(1.0, float(score)))
    st = replace(state)
    quality = round(score * 5)
    st.attempts += 1
    st.correct += score
    st.last_practiced = iso(day)
    if score >= PASS:
        st.reps += 1
        if st.reps == 1:
            interval = 1
        elif st.reps == 2:
            interval = 3
        else:
            interval = max(st.interval_days + 1, round(st.interval_days * st.ease))
        st.ease = max(MIN_EASE, st.ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    else:
        st.lapses += 1
        st.reps = 0
        interval = 1
        st.ease = max(MIN_EASE, st.ease - 0.2)
    interval = min(MAX_INTERVAL, interval)
    if exam is not None and exam > day:
        interval = min(interval, max(1, (exam - day).days // 2))
    st.interval_days = interval
    st.due_date = iso(day + timedelta(days=interval))
    st.manual_due = 0
    return st


def mastery(state: TopicState, practice_days: list[str] | None = None) -> str:
    if state.attempts == 0:
        return "new"
    accuracy = state.correct / state.attempts
    spread = 0
    if practice_days:
        days = sorted(date.fromisoformat(d) for d in practice_days)
        spread = (days[-1] - days[0]).days if len(days) > 1 else 0
    if state.reps >= 3 and accuracy >= 0.8 and spread >= 7:
        return "strong"
    if accuracy >= 0.6 and state.reps >= 1:
        return "developing"
    return "learning"


def is_due(state: TopicState, day: date, exam: date | None = None) -> bool:
    if state.due_date and date.fromisoformat(state.due_date) <= day:
        return True
    if state.attempts == 0 and exam is not None and 0 <= (exam - day).days <= 21:
        return True
    return False


def reasons(state: TopicState, day: date, exam: date | None, recent_mistakes: int = 0,
            last_score: float | None = None) -> list[str]:
    """Plain-language reasons a topic is in the revision queue."""
    out: list[str] = []
    if state.manual_due:
        out.append("You scheduled it for today")
    if last_score is not None and last_score < PASS:
        out.append(f"Last practice scored {round(last_score * 100)}%")
    if recent_mistakes:
        out.append(f"{recent_mistakes} open mistake{'s' if recent_mistakes != 1 else ''} in your notebook")
    if state.attempts == 0:
        out.append("Not practised yet")
    elif state.last_practiced:
        gap = (day - date.fromisoformat(state.last_practiced)).days
        if gap >= 14:
            out.append(f"Not practised for {gap} days")
        elif state.due_date and date.fromisoformat(state.due_date) <= day:
            out.append(f"Spaced review due (every {state.interval_days} day{'s' if state.interval_days != 1 else ''})")
    if exam is not None and exam >= day:
        days = (exam - day).days
        out.append("Exam today" if days == 0 else f"Exam in {days} day{'s' if days != 1 else ''}")
    return out


def urgency(state: TopicState, day: date, exam: date | None, recent_mistakes: int = 0) -> float:
    """Higher = more urgent. Used only for ordering the queue."""
    score = 0.0
    if state.due_date:
        overdue = (day - date.fromisoformat(state.due_date)).days
        score += max(0, overdue) * 1.5
    if state.attempts == 0:
        score += 4
    else:
        score += (1 - state.correct / state.attempts) * 10
    score += recent_mistakes * 2
    if exam is not None and exam >= day:
        score += max(0, 30 - (exam - day).days) * 0.6
    if state.manual_due:
        score += 8
    return score


# -- flashcards ------------------------------------------------------------------------
CARD_GRADES = {"again": 0, "hard": 3, "good": 4, "easy": 5}


def grade_card(card: Flashcard, grade: str, day: date) -> Flashcard:
    q = CARD_GRADES[grade]
    c = replace(card)
    if q < 3:
        c.lapses += 1
        c.reps = 0
        c.interval_days = 0  # see it again in this session / today
        c.ease = max(MIN_EASE, c.ease - 0.2)
        c.due_date = iso(day)
        return c
    c.reps += 1
    if c.reps == 1:
        c.interval_days = 1 if q < 5 else 3
    elif c.reps == 2:
        c.interval_days = 3 if q < 5 else 6
    else:
        factor = c.ease * (1.3 if q == 5 else 0.85 if q == 3 else 1.0)
        c.interval_days = min(MAX_INTERVAL, max(c.interval_days + 1, round(c.interval_days * factor)))
    c.ease = max(MIN_EASE, c.ease + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    c.due_date = iso(day + timedelta(days=c.interval_days))
    return c
