"""StudyForge data classes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

NODE_KINDS = ["subject", "unit", "chapter", "topic", "objective"]
NODE_LABELS = {"subject": "Subject", "unit": "Unit", "chapter": "Chapter", "topic": "Topic", "objective": "Learning objective"}

QTYPES: dict[str, str] = {
    "mcq": "Multiple choice (one answer)",
    "multi": "Multiple select",
    "assertion": "Assertion–reason",
    "tf": "True / false",
    "fill": "Fill in the blank",
    "match": "Matching",
    "numerical": "Numerical",
    "vsa": "Very short answer",
    "sa": "Short answer",
    "la": "Long answer",
    "case": "Case-based",
    "source": "Source-based",
    "competency": "Competency-based",
    "application": "Application",
    "diagram": "Diagram-based",
}
OBJECTIVE_TYPES = {"mcq", "multi", "assertion", "tf", "fill", "match", "numerical"}
SHORT_TYPES = {"mcq": "MCQ", "multi": "Multi", "assertion": "A–R", "tf": "T/F", "fill": "Fill", "match": "Match",
               "numerical": "Num", "vsa": "VSA", "sa": "SA", "la": "LA", "case": "Case", "source": "Source",
               "competency": "Comp", "application": "App", "diagram": "Diagram"}

ORIGINS = {
    "official": "Official (from a source document)",
    "imported": "Imported, not verified",
    "user": "Written by you",
    "ai": "AI-generated practice",
}
ASSERTION_OPTIONS = [
    "Both A and R are true, and R is the correct explanation of A.",
    "Both A and R are true, but R is not the correct explanation of A.",
    "A is true, but R is false.",
    "A is false, but R is true.",
]
BLUEPRINT_STATUS = {"verified": "Verified against an official source", "provisional": "Provisional — please verify",
                    "user": "User-defined"}
DOC_KINDS = {"syllabus": "Syllabus / curriculum", "textbook": "Textbook", "sample_paper": "Sample / past paper",
             "marking_scheme": "Marking scheme", "notes": "Notes", "revision_sheet": "Revision sheet",
             "chapter_list": "Chapter list", "other": "Other"}


def _json(value: str, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


@dataclass
class Course:
    id: int
    name: str
    kind: str = "custom"
    session: str = ""
    authority: str = ""
    level: str = ""
    description: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Node:
    id: int
    course_id: int
    parent_id: int | None
    kind: str
    title: str
    position: int = 0
    subject_id: int | None = None
    exam_date: str | None = None
    weight: float | None = None
    source_doc_id: int | None = None
    source_ref: str = ""
    confidence: float | None = None
    notes: str = ""
    created_at: str = ""
    children: list["Node"] = field(default_factory=list)

    @property
    def exam_day(self) -> date | None:
        return date.fromisoformat(self.exam_date) if self.exam_date else None


@dataclass
class Document:
    id: int
    course_id: int | None
    title: str
    filename: str = ""
    path: str = ""
    kind: str = "other"
    official: int = 0
    sha256: str = ""
    pages: int = 0
    text_chars: int = 0
    session: str = ""
    authority: str = ""
    syllabus_version: str = ""
    status: str = "parsed"
    problems: str = "[]"
    imported_at: str = ""

    @property
    def problem_list(self) -> list[str]:
        return _json(self.problems, [])


@dataclass
class Question:
    id: int
    course_id: int | None
    node_id: int | None
    qtype: str
    text: str
    difficulty: int = 2
    marks: float = 1.0
    options: str = "[]"
    answer: str = ""
    explanation: str = ""
    rubric: str = "[]"
    origin: str = "user"
    verified: int = 0
    source_doc_id: int | None = None
    source_ref: str = ""
    tags: str = ""
    media_path: str = ""
    content_hash: str = ""
    created_at: str = ""
    updated_at: str = ""
    node_title: str | None = None
    times_used: int = 0
    times_correct: float = 0.0

    @property
    def option_list(self) -> list[str]:
        return _json(self.options, [])

    @property
    def rubric_points(self) -> list[dict]:
        """Marking points: [{"text": "...", "marks": 1.0}, …]."""
        points = _json(self.rubric, [])
        return [p for p in points if isinstance(p, dict) and p.get("text")]

    @property
    def objective(self) -> bool:
        return self.qtype in OBJECTIVE_TYPES

    @property
    def provenance(self) -> str:
        if self.origin == "ai":
            return "AI-generated practice question" + (" (checked by you)" if self.verified else " — not verified")
        if self.origin == "official":
            return "Official question" + (f" · {self.source_ref}" if self.source_ref else "")
        if self.origin == "imported":
            return "Imported" + (" and verified" if self.verified else " — not verified")
        return "Your question" + (" (verified)" if self.verified else "")

    def snapshot(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "qtype", "text", "difficulty", "marks", "options", "answer",
                                               "explanation", "rubric", "origin", "verified", "source_ref", "node_id",
                                               "node_title", "media_path")}


@dataclass
class Section:
    name: str
    qtype: str
    count: int
    marks_each: float
    choice: int = 0  # extra alternative questions offered (internal choice): 0 = none
    instructions: str = ""
    types: list[str] = field(default_factory=list)  # optional extra allowed types

    @property
    def total(self) -> float:
        return self.count * self.marks_each

    def allowed_types(self) -> set[str]:
        return {self.qtype, *self.types}

    def to_dict(self) -> dict:
        return {"name": self.name, "qtype": self.qtype, "count": self.count, "marks_each": self.marks_each,
                "choice": self.choice, "instructions": self.instructions, "types": self.types}

    @classmethod
    def from_dict(cls, d: dict) -> "Section":
        return cls(str(d.get("name", "")), str(d.get("qtype", "mcq")), int(d.get("count", 0)),
                   float(d.get("marks_each", 1)), int(d.get("choice", 0)), str(d.get("instructions", "")),
                   [str(t) for t in d.get("types", []) if t in QTYPES])


@dataclass
class Blueprint:
    id: int
    course_id: int | None
    name: str
    max_marks: float
    duration_min: int
    subject_node_id: int | None = None
    session: str = ""
    instructions: str = ""
    status: str = "user"
    source_doc_id: int | None = None
    source_note: str = ""
    version: str = ""
    sections: str = "[]"
    coverage: str = "{}"
    created_at: str = ""
    updated_at: str = ""

    @property
    def section_list(self) -> list[Section]:
        return [Section.from_dict(d) for d in _json(self.sections, []) if isinstance(d, dict)]

    @property
    def coverage_map(self) -> dict[int, float]:
        raw = _json(self.coverage, {})
        out = {}
        for k, v in raw.items():
            try:
                out[int(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out


@dataclass
class Test:
    id: int
    course_id: int | None
    title: str
    blueprint_id: int | None = None
    mode: str = "practice"
    duration_min: int | None = None
    total_marks: float = 0
    config: str = "{}"
    instructions: str = ""
    created_at: str = ""
    attempts: int = 0
    best: float | None = None

    @property
    def config_dict(self) -> dict:
        return _json(self.config, {})


@dataclass
class TestItem:
    id: int
    test_id: int
    position: int
    snapshot: str
    marks: float
    section: str = ""
    question_id: int | None = None
    choice_group: int | None = None

    @property
    def question(self) -> dict:
        return _json(self.snapshot, {})


@dataclass
class Attempt:
    id: int
    test_id: int
    started_at: str
    submitted_at: str | None = None
    elapsed_s: int = 0
    status: str = "in_progress"
    score: float | None = None
    max_score: float | None = None
    has_estimates: int = 0
    test_title: str | None = None


@dataclass
class Answer:
    attempt_id: int
    item_id: int
    response: str = ""
    flagged: int = 0
    marks: float | None = None
    marker: str = "none"
    correct: int | None = None
    feedback: str = ""
    time_s: int = 0
    updated_at: str = ""


@dataclass
class TopicState:
    node_id: int
    ease: float = 2.5
    interval_days: int = 0
    due_date: str | None = None
    last_practiced: str | None = None
    reps: int = 0
    lapses: int = 0
    attempts: int = 0
    correct: float = 0.0
    confidence: int | None = None
    manual_due: int = 0
    updated_at: str = ""

    @property
    def accuracy(self) -> float | None:
        return self.correct / self.attempts if self.attempts else None


@dataclass
class Flashcard:
    id: int
    course_id: int | None
    front: str
    back: str = ""
    node_id: int | None = None
    kind: str = "card"
    source_ref: str = ""
    ai_generated: int = 0
    reviewed: int = 1
    ease: float = 2.5
    interval_days: int = 0
    due_date: str | None = None
    reps: int = 0
    lapses: int = 0
    created_at: str = ""
    updated_at: str = ""
    node_title: str | None = None


@dataclass
class Material:
    id: int
    course_id: int | None
    title: str
    kind: str = "notes"
    body: str = ""
    node_id: int | None = None
    source_doc_id: int | None = None
    source_ref: str = ""
    ai_generated: int = 0
    reviewed: int = 1
    created_at: str = ""
    updated_at: str = ""
    node_title: str | None = None
