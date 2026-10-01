"""Constraint-based test assembly and paper validation.

The assembler only uses questions that are already in the bank (official, your
own, imported or AI-generated ones you kept), so a paper can never contain
invented "official" questions. When the bank can't satisfy a section, it says
exactly what is missing instead of quietly producing a shorter paper.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from src.modules.studyforge.models import OBJECTIVE_TYPES, QTYPES, Question, Section

# Rough minutes per mark used for the duration sanity check of quick (non-blueprint) tests.
MINUTES_PER_MARK = {"mcq": 1.0, "multi": 1.5, "assertion": 1.5, "tf": 0.7, "fill": 1.0, "match": 1.2,
                    "numerical": 2.0, "vsa": 1.5, "sa": 2.0, "la": 2.2, "case": 2.2, "source": 2.2,
                    "competency": 2.0, "application": 2.0, "diagram": 2.2}


@dataclass
class TestConfig:
    sections: list[Section]
    node_ids: set[int]  # scope (already expanded to descendants)
    difficulty: tuple[int, int] = (1, 5)
    target_difficulty: float | None = None
    prefer_nodes: dict[int, float] = field(default_factory=dict)  # weak / due topics -> boost
    coverage: dict[int, float] = field(default_factory=dict)  # node -> share of marks (from blueprint)
    exclude: set[int] = field(default_factory=set)  # recently used questions
    origins: set[str] | None = None  # e.g. {"official", "user"}; None = all
    verified_only: bool = False
    strict_marks: bool = True  # blueprint sections require exact marks per question
    seed: int | None = None


@dataclass
class Picked:
    question: Question
    section: str
    marks: float
    choice_group: int | None = None


@dataclass
class Assembly:
    items: list[Picked]
    problems: list[str]
    coverage: dict[int, float]  # node -> marks

    @property
    def total_marks(self) -> float:
        groups: dict[int, float] = {}
        total = 0.0
        for it in self.items:
            if it.choice_group is None:
                total += it.marks
            else:
                groups[it.choice_group] = max(groups.get(it.choice_group, 0), it.marks)
        return total + sum(groups.values())


def assemble(bank: list[Question], cfg: TestConfig, chapter_of: dict[int, int] | None = None) -> Assembly:
    rnd = random.Random(cfg.seed)
    chapter_of = chapter_of or {}
    pool = [q for q in bank
            if q.node_id in cfg.node_ids
            and cfg.difficulty[0] <= q.difficulty <= cfg.difficulty[1]
            and (cfg.origins is None or q.origin in cfg.origins)
            and (not cfg.verified_only or q.verified)]
    used: set[int] = set()
    marks_by_unit: dict[int, float] = defaultdict(float)
    items: list[Picked] = []
    problems: list[str] = []
    group_id = 0
    total_target = sum(s.total for s in cfg.sections) or 1.0

    def unit(q: Question) -> int:
        return chapter_of.get(q.node_id or 0, q.node_id or 0)

    def score(q: Question) -> float:
        s = rnd.random() * 0.8
        if q.id in cfg.exclude:
            s -= 3
        u = unit(q)
        if cfg.coverage:
            share = cfg.coverage.get(u, cfg.coverage.get(q.node_id or 0, 0))
            want = share * total_target
            s += max(-2.0, min(3.0, (want - marks_by_unit[u]) / max(1.0, want)))
        else:
            s -= marks_by_unit[u] / max(1.0, total_target) * 6  # spread across topics
        s += cfg.prefer_nodes.get(q.node_id or 0, 0) + cfg.prefer_nodes.get(u, 0)
        if cfg.target_difficulty is not None:
            s -= abs(q.difficulty - cfg.target_difficulty) * 0.6
        if q.verified or q.origin == "official":
            s += 0.3
        return s

    for section in cfg.sections:
        allowed = section.allowed_types()
        needed = section.count * (1 + max(0, section.choice))
        candidates = [q for q in pool if q.qtype in allowed and q.id not in used
                      and (not cfg.strict_marks or abs(q.marks - section.marks_each) < 1e-6)]
        if len(candidates) < needed:
            kind = ", ".join(QTYPES[t].lower() for t in sorted(allowed))
            marks = f" worth {section.marks_each:g} mark{'s' if section.marks_each != 1 else ''}" if cfg.strict_marks else ""
            problems.append(
                f"{section.name or 'Section'}: needs {needed} {kind} question{'s' if needed != 1 else ''}{marks} "
                f"in the chosen topics, but the bank has {len(candidates)}. Add questions (or generate practice "
                "questions) for these topics, or change the section.")
        for _ in range(section.count):
            if not candidates:
                break
            candidates.sort(key=score, reverse=True)
            first = candidates.pop(0)
            group = None
            alternatives: list[Question] = []
            if section.choice > 0:
                same = [q for q in candidates if q.qtype == first.qtype and abs(q.marks - first.marks) < 1e-6]
                same.sort(key=score, reverse=True)
                alternatives = same[:section.choice]
                if len(alternatives) < section.choice:
                    problems.append(f"{section.name or 'Section'}: not enough matching questions to offer an internal "
                                    "choice for every question.")
                    alternatives = []
                else:
                    group_id += 1
                    group = group_id
            marks = section.marks_each if cfg.strict_marks else first.marks
            for q in [first, *alternatives]:
                if q in candidates:
                    candidates.remove(q)
                used.add(q.id)
                items.append(Picked(q, section.name, marks, group))
            marks_by_unit[unit(first)] += marks
    return Assembly(items, problems, dict(marks_by_unit))


def quick_sections(qtypes: list[str], count: int) -> list[Section]:
    """Spread a question count across chosen types (for quick tests without a blueprint)."""
    qtypes = [t for t in qtypes if t in QTYPES] or ["mcq"]
    base, extra = divmod(max(1, count), len(qtypes))
    out = []
    for i, t in enumerate(qtypes):
        n = base + (1 if i < extra else 0)
        if n:
            out.append(Section(QTYPES[t], t, n, 1.0))
    return out


def estimated_minutes(items: list[Picked]) -> int:
    seen_groups: set[int] = set()
    total = 0.0
    for it in items:
        if it.choice_group is not None:
            if it.choice_group in seen_groups:
                continue
            seen_groups.add(it.choice_group)
        total += it.marks * MINUTES_PER_MARK.get(it.question.qtype, 2.0)
    return max(1, round(total))


def validate(items: list[Picked], sections: list[Section] | None = None, max_marks: float | None = None,
             duration_min: int | None = None, coverage_nodes: set[int] | None = None,
             chapter_of: dict[int, int] | None = None) -> list[str]:
    """Problems with a paper: totals, counts, choices, duplicates, answer keys, coverage, timing."""
    issues: list[str] = []
    if not items:
        return ["The paper has no questions."]
    ids = [it.question.id for it in items if it.question.id]
    dupes = [qid for qid, n in Counter(ids).items() if n > 1]
    if dupes:
        issues.append(f"{len(dupes)} question(s) appear more than once.")
    groups: dict[int, list[Picked]] = defaultdict(list)
    for it in items:
        if it.choice_group is not None:
            groups[it.choice_group].append(it)
    for g, members in groups.items():
        if len({(m.question.qtype, m.marks) for m in members}) > 1:
            issues.append(f"Internal choice {g}: alternatives must have the same type and marks.")
    total = Assembly(items, [], {}).total_marks
    if max_marks is not None and abs(total - max_marks) > 1e-6:
        issues.append(f"Total is {total:g} marks; the blueprint expects {max_marks:g}.")
    if sections:
        by_section = defaultdict(list)
        for it in items:
            by_section[it.section].append(it)
        for s in sections:
            got = [it for it in by_section.get(s.name, [])]
            chosen = [it for it in got if it.choice_group is None] + \
                     [members[0] for g, members in groups.items() if members[0].section == s.name]
            if len(chosen) != s.count:
                issues.append(f"{s.name or 'Section'}: {len(chosen)} question(s) instead of {s.count}.")
            section_marks = sum(it.marks for it in chosen)
            if abs(section_marks - s.total) > 1e-6:
                issues.append(f"{s.name or 'Section'}: {section_marks:g} marks instead of {s.total:g}.")
            bad = [it for it in got if it.question.qtype not in s.allowed_types()]
            if bad:
                issues.append(f"{s.name or 'Section'}: {len(bad)} question(s) of the wrong type.")
    missing_keys = [it for it in items if it.question.qtype in OBJECTIVE_TYPES and not it.question.answer
                    and it.question.qtype != "match"]
    if missing_keys:
        issues.append(f"{len(missing_keys)} objective question(s) have no answer key.")
    no_model = [it for it in items if it.question.qtype not in OBJECTIVE_TYPES
                and not it.question.answer and not it.question.rubric_points]
    if no_model:
        issues.append(f"{len(no_model)} written question(s) have no model answer or marking points.")
    unverified_ai = [it for it in items if it.question.origin == "ai" and not it.question.verified]
    if unverified_ai:
        issues.append(f"{len(unverified_ai)} AI-generated question(s) haven't been checked by you yet.")
    if coverage_nodes:
        chapter_of = chapter_of or {}
        covered = {chapter_of.get(it.question.node_id or 0, it.question.node_id) for it in items}
        uncovered = [n for n in coverage_nodes if n not in covered]
        if uncovered:
            issues.append(f"{len(uncovered)} required chapter(s)/topic(s) have no question.")
    if duration_min:
        need = estimated_minutes(items)
        if need > duration_min * 1.25:
            issues.append(f"These questions usually need about {need} minutes; the duration is {duration_min}.")
    return issues
