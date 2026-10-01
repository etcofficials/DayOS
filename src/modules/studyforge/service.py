"""StudyForge workflows built on the repositories (still Qt-free, so everything is testable)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.modules.studyforge import marking, srs
from src.modules.studyforge.assembler import Assembly, Picked, TestConfig, assemble, estimated_minutes, validate
from src.modules.studyforge.models import Attempt, Blueprint, Flashcard, Node, Question, Section, TopicState
from src.modules.studyforge.repository import StudyForge
from src.services.dates import ValidationError, iso, now, today


@dataclass
class GenerateRequest:
    course_id: int
    title: str
    node_ids: list[int]  # chosen scope (chapters/topics/whole subjects)
    sections: list[Section] = field(default_factory=list)
    blueprint_id: int | None = None
    mode: str = "practice"
    duration_min: int | None = None
    difficulty: tuple[int, int] = (1, 5)
    focus: str = "balanced"  # balanced | weak | due
    origins: set[str] | None = None
    verified_only: bool = False
    seed: int | None = None


@dataclass
class GenerateResult:
    test_id: int | None
    assembly: Assembly
    issues: list[str]


@dataclass
class QueueItem:
    node: Node
    state: TopicState
    reasons: list[str]
    urgency: float
    exam: date | None
    mastery: str
    course_name: str = ""


@dataclass
class SubmitSummary:
    score: float
    max_score: float
    auto_marked: int
    needs_marking: int
    mistakes_added: int


class StudyForgeService:
    def __init__(self, sf: StudyForge) -> None:
        self.sf = sf
        self.db = sf.db

    # -- test generation ---------------------------------------------------------------
    def chapter_map(self, course_id: int) -> dict[int, int]:
        """node id -> its chapter id (or itself), used for coverage."""
        out: dict[int, int] = {}
        nodes = {n.id: n for n in self.sf.courses.nodes(course_id)}
        for nid, n in nodes.items():
            cur, guard = n, 0
            while cur is not None and cur.kind not in ("chapter", "unit", "subject") and guard < 20:
                cur = nodes.get(cur.parent_id) if cur.parent_id else None
                guard += 1
            out[nid] = cur.id if cur is not None else nid
        return out

    def weak_nodes(self, course_id: int, node_ids: set[int]) -> dict[int, float]:
        boosts: dict[int, float] = {}
        day = today()
        for nid, st in self.sf.revision.states(node_ids).items():
            if st.attempts and st.correct / st.attempts < 0.6:
                boosts[nid] = 2.0
            if st.due_date and date.fromisoformat(st.due_date) <= day:
                boosts[nid] = boosts.get(nid, 0) + 1.5
        for row in self.db.query("SELECT node_id, COUNT(*) FROM mistakes WHERE resolved = 0 AND node_id IS NOT NULL "
                                 "GROUP BY node_id"):
            if int(row[0]) in node_ids:
                boosts[int(row[0])] = boosts.get(int(row[0]), 0) + min(2.0, 0.5 * int(row[1]))
        return boosts

    def generate(self, req: GenerateRequest, save: bool = True) -> GenerateResult:
        if not req.node_ids:
            raise ValidationError("Choose at least one chapter or topic.")
        scope = self.sf.courses.descendants(req.node_ids)
        blueprint: Blueprint | None = self.sf.tests.blueprint(req.blueprint_id) if req.blueprint_id else None
        sections = blueprint.section_list if blueprint else req.sections
        if not sections:
            raise ValidationError("Choose question types and how many questions you want.")
        strict = blueprint is not None
        chapter_of = self.chapter_map(req.course_id)
        prefer = self.weak_nodes(req.course_id, scope) if req.focus in ("weak", "due") else {}
        if req.focus == "due":
            prefer = {k: v * 1.5 for k, v in prefer.items()}
        cfg = TestConfig(sections, scope, req.difficulty, None, prefer,
                         blueprint.coverage_map if blueprint else {}, self.sf.bank.recently_used(req.course_id),
                         req.origins, req.verified_only, strict, req.seed)
        bank = self.sf.bank.list(req.course_id, scope)
        for q in bank:
            q.node_title = q.node_title or ""
        result = assemble(bank, cfg, chapter_of)
        duration = (blueprint.duration_min if blueprint else req.duration_min) or estimated_minutes(result.items)
        issues = list(result.problems)
        issues += [i for i in validate(result.items, sections if strict else None,
                                       blueprint.max_marks if blueprint else None,
                                       duration if req.mode == "timed" else None,
                                       set(blueprint.coverage_map) if blueprint else None, chapter_of)
                   if i not in issues]
        test_id = None
        if save and result.items:
            config = {"node_ids": sorted(req.node_ids), "focus": req.focus, "difficulty": list(req.difficulty),
                      "sections": [s.to_dict() for s in sections], "signature": self._signature(req, sections)}
            instructions = blueprint.instructions if blueprint else ""
            test_id = self.sf.tests.create_test(
                req.course_id, req.title,
                [{"question": it.question, "section": it.section, "marks": it.marks, "choice_group": it.choice_group}
                 for it in result.items],
                blueprint_id=blueprint.id if blueprint else None, mode=req.mode,
                duration_min=duration if req.mode == "timed" else (req.duration_min or None), config=config,
                instructions=instructions)
        return GenerateResult(test_id, result, issues)

    @staticmethod
    def _signature(req: GenerateRequest, sections: list[Section]) -> str:
        """Tests with the same signature are comparable (same scope, structure and difficulty)."""
        parts = [str(req.blueprint_id or ""), ",".join(map(str, sorted(req.node_ids))),
                 "/".join(f"{s.qtype}:{s.count}x{s.marks_each:g}" for s in sections), f"{req.difficulty}"]
        return "|".join(parts)

    # -- taking & marking ------------------------------------------------------------------
    def submit(self, attempt_id: int, elapsed_s: int | None = None) -> SubmitSummary:
        attempt = self.sf.tests.attempt(attempt_id)
        if attempt is None:
            raise ValidationError("This attempt no longer exists.")
        if elapsed_s is not None:
            self.sf.tests.set_elapsed(attempt_id, elapsed_s)
        items = self.sf.tests.items(attempt.test_id)
        answers = self.sf.tests.answers(attempt_id)
        auto = pending = mistakes = 0
        chosen = self._chosen_items(items, answers)
        with self.db.transaction():
            for item in items:
                if item.id not in chosen:
                    continue
                ans = answers.get(item.id)
                response = ans.response if ans else ""
                if ans is not None and ans.marker in ("self", "ai"):
                    continue
                result = marking.mark(item.question, response, item.marks)
                if result.marks is None:
                    pending += 1
                    self.sf.tests.set_mark(attempt_id, item.id, None, "none", None, result.note)
                    continue
                auto += 1
                self.sf.tests.set_mark(attempt_id, item.id, result.marks, "auto", result.correct, result.note)
                if result.marks < item.marks and response.strip():
                    if self._add_mistake(attempt_id, item, response):
                        mistakes += 1
            summary = self._finalise(attempt_id)
        self._update_topics(attempt_id, only_items=None)
        return SubmitSummary(summary[0], summary[1], auto, pending, mistakes)

    @staticmethod
    def _chosen_items(items, answers) -> set[int]:
        """For internal choices, only the alternative the student answered counts (the first if none)."""
        chosen: set[int] = set()
        groups: dict[int, list] = defaultdict(list)
        for item in items:
            if item.choice_group is None:
                chosen.add(item.id)
            else:
                groups[item.choice_group].append(item)
        for members in groups.values():
            answered = [m for m in members if answers.get(m.id) and answers[m.id].response.strip()]
            chosen.add((answered[0] if answered else members[0]).id)
        return chosen

    def _finalise(self, attempt_id: int) -> tuple[float, float]:
        attempt = self.sf.tests.attempt(attempt_id)
        items = self.sf.tests.items(attempt.test_id)
        answers = self.sf.tests.answers(attempt_id)
        chosen = self._chosen_items(items, answers)
        score = max_score = 0.0
        unmarked = estimates = False
        for item in items:
            if item.id not in chosen:
                continue
            max_score += item.marks
            ans = answers.get(item.id)
            if ans is None or ans.marks is None:
                unmarked = True
                continue
            score += ans.marks
            estimates = estimates or ans.marker == "ai"
        self.sf.tests.finish_attempt(attempt_id, round(score, 2), max_score, not unmarked, estimates)
        return round(score, 2), max_score

    def mark_written(self, attempt_id: int, item_id: int, marks: float, feedback: str = "", marker: str = "self",
                     add_mistake: bool | None = None) -> None:
        """Record marks for a written answer (by the user, or an AI estimate the user can override)."""
        items = {i.id: i for i in self.sf.tests.items(self.sf.tests.attempt(attempt_id).test_id)}
        item = items.get(item_id)
        if item is None:
            raise ValidationError("Unknown question in this test.")
        if not 0 <= marks <= item.marks:
            raise ValidationError(f"Marks must be between 0 and {item.marks:g}.")
        existing = self.sf.tests.answers(attempt_id).get(item_id)
        if marker == "ai" and existing is not None and existing.marker == "self":
            raise ValidationError("You've already marked this answer yourself; an AI estimate won't replace your mark.")
        correct = 1 if marks >= item.marks else (0 if marks == 0 else None)
        self.sf.tests.set_mark(attempt_id, item_id, round(marks, 2), marker, correct, feedback)
        response = self.sf.tests.answers(attempt_id).get(item_id)
        wants_mistake = add_mistake if add_mistake is not None else (marks < item.marks * 0.5)
        if wants_mistake and response and response.response.strip():
            self._add_mistake(attempt_id, item, response.response)
        self._finalise(attempt_id)
        if marker == "self":
            self._update_topics(attempt_id, only_items={item_id})

    def _add_mistake(self, attempt_id: int, item, response: str) -> bool:
        q = item.question
        if self.sf.mistakes.exists_for(attempt_id, item.question_id):
            return False
        self.sf.mistakes.add(
            q.get("text", "")[:20000], node_id=q.get("node_id"), question_id=item.question_id,
            user_answer=marking.response_text(q, response), expected_answer=marking.expected_answer_text(q),
            explanation=q.get("explanation", ""), attempt_id=attempt_id)
        return True

    def _update_topics(self, attempt_id: int, only_items: set[int] | None) -> None:
        """Feed marked answers into the spaced-revision schedule (one result per topic per attempt)."""
        attempt = self.sf.tests.attempt(attempt_id)
        items = {i.id: i for i in self.sf.tests.items(attempt.test_id)}
        answers = self.sf.tests.answers(attempt_id)
        per_node: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for item_id, ans in answers.items():
            if only_items is not None and item_id not in only_items:
                continue
            if ans.marks is None or ans.marker == "ai":
                continue  # AI estimates never drive the schedule on their own
            item = items.get(item_id)
            node_id = item.question.get("node_id") if item else None
            if not node_id or self.sf.courses.node(int(node_id)) is None:
                continue
            per_node[int(node_id)][0] += ans.marks
            per_node[int(node_id)][1] += item.marks
        day = today()
        for node_id, (got, total) in per_node.items():
            if total <= 0:
                continue
            score = got / total
            self.record_practice(node_id, score, "test", f"{attempt.test_title or 'Test'}: {got:g}/{total:g}", day)

    def record_practice(self, node_id: int, score: float, source: str, detail: str = "", day: date | None = None) -> TopicState:
        day = day or today()
        st = self.sf.revision.state(node_id)
        new = srs.update_topic(st, score, day, self.sf.courses.exam_date_for(node_id))
        self.sf.revision.save_state(new)
        self.sf.revision.log(node_id, source, score, detail, day)
        return new

    def reschedule(self, node_id: int, day: date) -> None:
        st = self.sf.revision.state(node_id)
        st.due_date = iso(day)
        st.manual_due = 1
        self.sf.revision.save_state(st)

    def set_confidence(self, node_id: int, confidence: int | None) -> None:
        st = self.sf.revision.state(node_id)
        st.confidence = confidence
        self.sf.revision.save_state(st)

    # -- revision queue -----------------------------------------------------------------------
    def queue(self, course_id: int | None = None, day: date | None = None, limit: int = 60) -> list[QueueItem]:
        day = day or today()
        courses = [self.sf.courses.get(course_id)] if course_id else self.sf.courses.list()
        out: list[QueueItem] = []
        open_mistakes = {int(r[0]): int(r[1]) for r in self.db.query(
            "SELECT node_id, COUNT(*) FROM mistakes WHERE resolved = 0 AND node_id IS NOT NULL GROUP BY node_id")}
        for course in courses:
            if course is None:
                continue
            topics = self.sf.courses.topic_nodes(course.id)
            states = self.sf.revision.states(n.id for n in topics)
            for node in topics:
                st = states[node.id]
                exam = self.sf.courses.exam_date_for(node.id)
                mistakes = open_mistakes.get(node.id, 0)
                due = srs.is_due(st, day, exam) or st.manual_due or (mistakes and st.attempts > 0)
                if not due:
                    continue
                history = self.sf.revision.history(node.id, 10)
                last = history[0][2] if history else None
                practice_days = [h[0] for h in history]
                out.append(QueueItem(node, st, srs.reasons(st, day, exam, mistakes, last),
                                     srs.urgency(st, day, exam, mistakes), exam, srs.mastery(st, practice_days),
                                     course.name))
        out.sort(key=lambda q: -q.urgency)
        return out[:limit]

    def topic_overview(self, course_id: int) -> dict[int, dict]:
        """Per node: questions, attempts, accuracy, mastery estimate, next review."""
        counts = self.sf.bank.counts_by_node(course_id)
        nodes = self.sf.courses.nodes(course_id)
        states = self.sf.revision.states(n.id for n in nodes)
        out = {}
        for n in nodes:
            st = states[n.id]
            days = [h[0] for h in self.sf.revision.history(n.id, 10)] if st.attempts else []
            out[n.id] = {"questions": counts.get(n.id, 0), "attempts": st.attempts,
                         "accuracy": st.accuracy, "mastery": srs.mastery(st, days), "due": st.due_date}
        return out

    # -- flashcards ---------------------------------------------------------------------------
    def grade_card(self, card: Flashcard, grade: str) -> Flashcard:
        updated = srs.grade_card(card, grade, today())
        self.sf.revision.save_card_schedule(updated)
        if card.node_id:
            self.sf.revision.log(card.node_id, "flashcard", srs.CARD_GRADES[grade] / 5,
                                 f"Card: {card.front[:60]}")
        return updated

    # -- analytics ------------------------------------------------------------------------------
    def analytics(self, course_id: int | None = None) -> dict:
        attempts = [a for a in self.sf.tests.attempts(course_id) if a.max_score]
        history = [{"id": a.id, "title": a.test_title, "date": (a.submitted_at or a.started_at)[:10],
                    "percent": round(100 * (a.score or 0) / a.max_score, 1), "status": a.status,
                    "estimates": bool(a.has_estimates), "minutes": round(a.elapsed_s / 60)} for a in attempts]
        params: list = []
        course_filter = ""
        if course_id is not None:
            course_filter = " AND t.course_id = ?"
            params.append(course_id)
        rows = self.db.query(
            "SELECT i.snapshot, i.marks AS max_marks, a.marks, a.marker FROM sf_answers a "
            "JOIN sf_test_items i ON i.id = a.item_id JOIN sf_tests t ON t.id = i.test_id "
            "JOIN sf_attempts at ON at.id = a.attempt_id WHERE a.marks IS NOT NULL AND at.status != 'in_progress'"
            + course_filter, params)
        by_type: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        by_topic: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        estimated = 0
        for r in rows:
            q = json.loads(r["snapshot"])
            if r["marker"] == "ai":
                estimated += 1
                continue  # estimates are shown separately, never mixed into accuracy
            by_type[q.get("qtype", "?")][0] += r["marks"]
            by_type[q.get("qtype", "?")][1] += r["max_marks"]
            topic = q.get("node_title") or "Unassigned"
            by_topic[topic][0] += r["marks"]
            by_topic[topic][1] += r["max_marks"]
        comparable: dict[str, list[dict]] = defaultdict(list)
        for a in attempts:
            test = self.sf.tests.test(a.test_id)
            sig = (test.config_dict.get("signature") if test else None) or f"test:{a.test_id}"
            comparable[sig].append({"date": (a.submitted_at or "")[:10], "percent": round(100 * (a.score or 0) / a.max_score, 1),
                                    "title": a.test_title})
        series = {k: sorted(v, key=lambda x: x["date"]) for k, v in comparable.items() if len(v) >= 2}
        return {
            "history": history,
            "by_type": {k: round(100 * v[0] / v[1], 1) for k, v in by_type.items() if v[1]},
            "by_topic": sorted(((k, round(100 * v[0] / v[1], 1), v[1]) for k, v in by_topic.items() if v[1]),
                               key=lambda x: x[1]),
            "comparable": series,
            "estimated_answers": estimated,
            "mistakes": self.sf.mistakes.category_counts(
                {n.id for n in self.sf.courses.nodes(course_id)} if course_id else None),
            "revisions_done": int(self.db.scalar("SELECT COUNT(*) FROM sf_review_log WHERE date >= ?",
                                                 (iso(today() - timedelta(days=30)),), 0)),
        }

    def unfinished(self) -> list[Attempt]:
        return self.sf.tests.unfinished_attempts()

    def elapsed_since_start(self, attempt: Attempt) -> int:
        from datetime import datetime

        return int((now() - datetime.fromisoformat(attempt.started_at)).total_seconds())
