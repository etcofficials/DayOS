"""Read questions, a blueprint and an answer key out of a sample / past paper (best effort).

Everything returned is a proposal for the user to review. Questions from a paper
are only labelled "official" when the user has confirmed the document is an
official paper from the named authority; otherwise they are "imported". A
blueprint read from a paper is always "provisional" until the user verifies it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.modules.studyforge.models import Section

RE_QSTART = re.compile(r"^\s*(?:Q(?:uestion)?\s*\.?\s*)?(\d{1,2})\s*[.)]\s+(.+)$", re.I)
RE_OPTION = re.compile(r"^\s*\(?([a-dA-D])[).]\s+(.+)$")
RE_INLINE_OPTIONS = re.compile(r"\(([a-d])\)\s*([^()]+?)(?=\s*\([a-d]\)|$)")
RE_MARKS = re.compile(r"[(\[]\s*(\d{1,2}(?:\.5)?)\s*(?:marks?|m)?\s*[)\]]\s*$", re.I)
RE_SECTION = re.compile(r"^\s*section\s*[-–:]?\s*([A-Ea-e])\b", re.I)
RE_SECTION_RULE = re.compile(
    r"section\s+([A-E])\s+(?:has|consists of|contains|comprises)\s+(\d{1,2})\s+(?:questions?|mcqs?|q)\b[^.]{0,80}?"
    r"(?:of|carrying|with)\s+(\d{1,2}(?:\.5)?)\s+marks?\s+each", re.I)
RE_MAX = re.compile(r"(?:maximum|max\.?)\s+marks?\s*[:\-–]?\s*(\d{1,3})", re.I)
RE_TIME = re.compile(r"time\s*(?:allowed)?\s*[:\-–]?\s*(\d{1,3}(?:\.\d)?)\s*(hours?|hrs?|minutes?|mins?)", re.I)
RE_ANSWER = re.compile(r"^\s*(?:Q\.?\s*)?(\d{1,2})\s*[.):\-–]\s*(?:ans(?:wer)?\s*[:.\-–]?\s*)?\(?([a-dA-D])\)?(?:\s|$|[.,])",
                       re.I)


@dataclass
class ProposedQuestion:
    number: int
    text: str
    qtype: str
    marks: float | None
    options: list[str] = field(default_factory=list)
    section: str = ""
    page: int = 0
    answer: str = ""  # option index as text, when an answer key matched
    include: bool = True


@dataclass
class PaperProposal:
    questions: list[ProposedQuestion]
    sections: list[Section]
    max_marks: float | None = None
    duration_min: int | None = None
    flags: list[str] = field(default_factory=list)


def _guess_type(text: str, options: list[str], marks: float | None) -> str:
    low = text.lower()
    if "assertion" in low and "reason" in low:
        return "assertion"
    if options:
        return "mcq"
    if any(k in low for k in ("case study", "case-based", "read the following passage", "read the passage",
                              "read the following text")):
        return "case"
    if any(k in low for k in ("source", "read the source")) and "source-based" in low:
        return "source"
    if "fill in the blank" in low or "____" in text:
        return "fill"
    if marks is None:
        return "sa"
    if marks <= 1:
        return "vsa"
    if marks <= 3:
        return "sa"
    return "la"


def parse_paper(pages: list[str]) -> PaperProposal:
    text = "\n".join(pages)
    proposal = PaperProposal([], [])
    m = RE_MAX.search(text)
    if m:
        proposal.max_marks = float(m.group(1))
    m = RE_TIME.search(text)
    if m:
        value = float(m.group(1))
        proposal.duration_min = int(value * 60 if m.group(2).lower().startswith("h") else value)
    for m in RE_SECTION_RULE.finditer(text):
        name, count, marks = m.group(1).upper(), int(m.group(2)), float(m.group(3))
        if not any(s.name == f"Section {name}" for s in proposal.sections):
            qtype = "mcq" if marks <= 1 else ("vsa" if marks <= 2 else "sa" if marks <= 3 else "la")
            proposal.sections.append(Section(f"Section {name}", qtype, count, marks))

    section = ""
    current: ProposedQuestion | None = None
    expected = 1
    for page_no, page in enumerate(pages, start=1):
        for raw in page.splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            sm = RE_SECTION.match(line)
            if sm and len(line.strip()) < 40:
                section = f"Section {sm.group(1).upper()}"
                continue
            qm = RE_QSTART.match(line)
            if qm and int(qm.group(1)) == expected:
                if current:
                    proposal.questions.append(current)
                current = ProposedQuestion(int(qm.group(1)), qm.group(2).strip(), "", None, section=section, page=page_no)
                expected += 1
                continue
            if current is None:
                continue
            om = RE_OPTION.match(line)
            if om and len(current.options) < 6:
                current.options.append(om.group(2).strip())
                continue
            current.text += "\n" + line.strip()
    if current:
        proposal.questions.append(current)

    for q in proposal.questions:
        mm = RE_MARKS.search(q.text.splitlines()[0]) or RE_MARKS.search(q.text)
        if mm:
            q.marks = float(mm.group(1))
            q.text = RE_MARKS.sub("", q.text).strip()
        if not q.options:
            inline = RE_INLINE_OPTIONS.findall(q.text)
            if len(inline) >= 3:
                q.options = [o.strip() for _, o in inline]
                q.text = q.text[:q.text.find("(a)")].strip() or q.text
        if q.marks is None:
            rule = next((s for s in proposal.sections if s.name == q.section), None)
            if rule:
                q.marks = rule.marks_each
        q.qtype = _guess_type(q.text, q.options, q.marks)
        if q.qtype == "assertion":
            q.options = []
        if len(q.text) < 8:
            q.include = False
    if not proposal.questions:
        proposal.flags.append("No numbered questions were recognised in this document.")
    unknown = sum(1 for q in proposal.questions if q.marks is None)
    if unknown:
        proposal.flags.append(f"{unknown} question(s) have no marks shown; set them before saving.")
    if proposal.sections and proposal.max_marks:
        total = sum(s.total for s in proposal.sections)
        if abs(total - proposal.max_marks) > 1e-6:
            proposal.flags.append(f"Section rules add up to {total:g} marks but the paper says {proposal.max_marks:g}; "
                                  "the paper may have internal choices or the rules weren't all recognised.")
    return proposal


def parse_answer_key(pages: list[str]) -> dict[int, int]:
    """Map question number → option index from a marking scheme / answer key ('1. (b)', 'Q2 Ans: c')."""
    key: dict[int, int] = {}
    for page in pages:
        for line in page.splitlines():
            m = RE_ANSWER.match(line)
            if m:
                key.setdefault(int(m.group(1)), "abcd".index(m.group(2).lower()))
    return key


def apply_answer_key(proposal: PaperProposal, key: dict[int, int]) -> int:
    matched = 0
    for q in proposal.questions:
        if q.qtype in ("mcq", "assertion") and q.number in key:
            limit = 4 if q.qtype == "assertion" else len(q.options)
            if 0 <= key[q.number] < limit:
                q.answer = str(key[q.number])
                matched += 1
    return matched
