"""Marking answers.

* Objective questions (MCQ, multiple select, assertion–reason, true/false, fill in
  the blank, numerical, matching) are marked automatically when the answer key is
  known.
* Subjective answers are marked by the user against the marking points (rubric),
  with partial credit. Optional AI feedback is stored separately as an *estimate*
  and can always be overridden.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from src.modules.studyforge.models import OBJECTIVE_TYPES


@dataclass(frozen=True)
class MarkResult:
    marks: float | None  # None = needs manual marking
    correct: int | None  # 1 full, 0 wrong, None partial/unknown
    note: str = ""


def _norm(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").casefold()).strip()
    return text.strip(" .;:,!?")


def _num(text: str) -> float | None:
    cleaned = (text or "").strip().replace(",", "").replace("−", "-")
    match = re.match(r"^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def match_pairs(options: list[str]) -> list[tuple[str, str]]:
    out = []
    for opt in options:
        if "=>" in opt:
            left, right = opt.split("=>", 1)
            out.append((left.strip(), right.strip()))
    return out


def mark(question: dict, response: str, max_marks: float) -> MarkResult:
    """Mark one answer. ``question`` is a test-item snapshot (dict with qtype/options/answer)."""
    qtype = question.get("qtype", "")
    if qtype not in OBJECTIVE_TYPES:
        return MarkResult(None, None, "Needs marking against the marking points.")
    response = (response or "").strip()
    answer = question.get("answer", "")
    if qtype != "match" and not str(answer).strip():
        return MarkResult(None, None, "This question has no answer key; mark it yourself.")
    if not response:
        return MarkResult(0.0, 0, "Not answered.")
    if qtype in ("mcq", "assertion"):
        ok = response == str(answer)
        return MarkResult(max_marks if ok else 0.0, int(ok))
    if qtype == "multi":
        try:
            expected = set(json.loads(answer or "[]"))
            given = set(json.loads(response))
        except (ValueError, TypeError):
            return MarkResult(0.0, 0, "Answer couldn't be read.")
        ok = expected == given
        return MarkResult(max_marks if ok else 0.0, int(ok),
                          "" if ok else "All correct options (and only those) must be selected.")
    if qtype == "tf":
        ok = _norm(response) == str(answer)
        return MarkResult(max_marks if ok else 0.0, int(ok))
    if qtype == "fill":
        accepted = [_norm(a) for a in str(answer).split("|") if a.strip()]
        ok = _norm(response) in accepted
        return MarkResult(max_marks if ok else 0.0, int(ok))
    if qtype == "numerical":
        try:
            key = json.loads(answer)
            value, tol = float(key["value"]), float(key.get("tolerance") or 0)
        except (ValueError, TypeError, KeyError):
            return MarkResult(None, None, "The answer key is incomplete; mark this one yourself.")
        given = _num(response)
        if given is None:
            return MarkResult(0.0, 0, "Not a number.")
        allowed = tol if tol > 0 else max(1e-9, abs(value) * 1e-9)
        ok = abs(given - value) <= allowed
        return MarkResult(max_marks if ok else 0.0, int(ok))
    if qtype == "match":
        pairs = match_pairs(question_options(question))
        if not pairs:
            return MarkResult(None, None, "No matching key; mark this one yourself.")
        try:
            given = json.loads(response)
        except (ValueError, TypeError):
            return MarkResult(0.0, 0, "Answer couldn't be read.")
        right = sum(1 for left, target in pairs if _norm(str(given.get(left, ""))) == _norm(target))
        marks = round(max_marks * right / len(pairs), 2)
        return MarkResult(marks, 1 if right == len(pairs) else (0 if right == 0 else None),
                          f"{right} of {len(pairs)} pairs correct.")
    return MarkResult(None, None)


def question_options(question: dict) -> list[str]:
    raw = question.get("options", "[]")
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except (ValueError, TypeError):
        return []


def rubric_points(question: dict) -> list[dict]:
    raw = question.get("rubric", "[]")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    return [p for p in value or [] if isinstance(p, dict) and p.get("text")]


def rubric_score(points: list[dict], awarded: list[bool], max_marks: float) -> float:
    """Marks from ticked marking points, capped at the question's maximum."""
    total = sum(float(p.get("marks", 1)) for p, ok in zip(points, awarded) if ok)
    return round(min(max_marks, total), 2)


def expected_answer_text(question: dict) -> str:
    """Human-readable correct answer for results and the mistake notebook."""
    qtype = question.get("qtype", "")
    options = question_options(question)
    answer = question.get("answer", "")
    try:
        if qtype in ("mcq", "assertion"):
            i = int(answer)
            return f"{chr(65 + i)}. {options[i]}" if 0 <= i < len(options) else ""
        if qtype == "multi":
            return "; ".join(f"{chr(65 + i)}. {options[i]}" for i in json.loads(answer) if 0 <= i < len(options))
        if qtype == "tf":
            return "True" if answer == "true" else "False"
        if qtype == "fill":
            return " or ".join(a for a in str(answer).split("|") if a)
        if qtype == "numerical":
            key = json.loads(answer)
            tol = f" (± {key['tolerance']:g})" if key.get("tolerance") else ""
            return f"{key['value']:g}{(' ' + key['unit']) if key.get('unit') else ''}{tol}"
        if qtype == "match":
            return "; ".join(f"{a} → {b}" for a, b in match_pairs(options))
    except (ValueError, TypeError, KeyError, IndexError):
        return ""
    return str(answer)


def response_text(question: dict, response: str) -> str:
    qtype = question.get("qtype", "")
    options = question_options(question)
    if not response:
        return "(no answer)"
    try:
        if qtype in ("mcq", "assertion"):
            i = int(response)
            return f"{chr(65 + i)}. {options[i]}"
        if qtype == "multi":
            return "; ".join(f"{chr(65 + i)}. {options[i]}" for i in json.loads(response))
        if qtype == "match":
            return "; ".join(f"{k} → {v}" for k, v in json.loads(response).items())
    except (ValueError, TypeError, IndexError):
        pass
    return response
