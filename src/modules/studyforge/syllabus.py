"""Turn syllabus / chapter-list text into a *proposed* course map for the user to review.

Documents vary a lot, so this is deliberately conservative: it recognises explicit
structure (Unit …, Chapter …, numbered lists, bullets under a chapter, learning
outcome lists, subject headings) and gives every item a confidence. Uncertain
items, duplicates, unreadable pages and dates are flagged; nothing is saved until
the user accepts the reviewed map.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SUBJECT_NAMES = [
    "Mathematics", "Maths", "Mathematics Standard", "Mathematics Basic", "Science", "Social Science", "English",
    "English Language and Literature", "Hindi", "Hindi Course A", "Hindi Course B", "Sanskrit", "Physics", "Chemistry",
    "Biology", "History", "Geography", "Political Science", "Civics", "Economics", "Computer Science",
    "Information Technology", "Computer Applications", "Accountancy", "Business Studies", "Psychology", "Sociology",
    "Environmental Studies", "Statistics", "Artificial Intelligence",
]
AUTHORITIES = [
    ("Central Board of Secondary Education", "CBSE"), ("CBSE", "CBSE"), ("ICSE", "CISCE"), ("CISCE", "CISCE"),
    ("International Baccalaureate", "IB"), ("Cambridge", "Cambridge"), ("NCERT", "NCERT"), ("AQA", "AQA"),
    ("Edexcel", "Pearson Edexcel"), ("College Board", "College Board"),
]

_ROMAN = r"[IVXLC]{1,6}"
RE_UNIT = re.compile(rf"^\s*unit\s*[-–:]?\s*({_ROMAN}|\d{{1,2}})\b\s*[:.\-–)]?\s*(.*)$", re.I)
RE_CHAPTER = re.compile(r"^\s*(?:chapter|ch\.?|lesson)\s*[-–:]?\s*(\d{1,2})\b\s*[:.\-–)]?\s*(.*)$", re.I)
RE_NUMBERED = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+([A-Z][^\n]{2,110})$")
RE_BULLET = re.compile(r"^\s*(?:[•●◦▪\-–*]|\(?[a-z]\)|\(?[ivx]{1,4}\))\s+(.{3,160})$")
RE_OUTCOMES = re.compile(r"^\s*(learning outcomes?|outcomes|objectives|learning objectives|students (?:will|should) be able to)\b",
                         re.I)
RE_SESSION = re.compile(r"\b(20\d\d)\s*[-–/]\s*((?:20)?\d\d)\b")
RE_TRAILING_NUMBER = re.compile(r"^(.*?)[\s.:\-–]+(\d{1,3})\s*$")
RE_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d\d)\b")
RE_CLASS = re.compile(r"\b(class|grade|std\.?|standard)\s*[-:]?\s*(x{1,2}i{0,2}|ix|x|\d{1,2})\b", re.I)


@dataclass
class ProposedNode:
    kind: str
    title: str
    confidence: float
    source_ref: str = ""
    weight: float | None = None
    flags: list[str] = field(default_factory=list)
    children: list["ProposedNode"] = field(default_factory=list)
    skip: bool = False

    def to_dict(self) -> dict:
        return {"kind": self.kind, "title": self.title, "confidence": self.confidence, "source_ref": self.source_ref,
                "weight": self.weight, "flags": list(self.flags), "skip": self.skip,
                "children": [c.to_dict() for c in self.children]}


@dataclass
class Proposal:
    nodes: list[ProposedNode]
    session: str = ""
    authority: str = ""
    level: str = ""
    dates: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def count(self) -> int:
        def walk(ns):
            return sum(1 + walk(n.children) for n in ns)
        return walk(self.nodes)


def _clean_title(text: str) -> tuple[str, float | None]:
    text = re.sub(r"\s+", " ", text).strip(" .:-–\t")
    weight = None
    m = RE_TRAILING_NUMBER.match(text)
    if m and len(m.group(1)) > 3:
        text, weight = m.group(1).strip(" .:-–"), float(m.group(2))
    return text[:200], weight


def _is_subject(line: str) -> str | None:
    clean = re.sub(r"[^A-Za-z ()]", " ", line).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean or len(clean) > 45:
        return None
    for name in sorted(SUBJECT_NAMES, key=len, reverse=True):
        if clean.lower() == name.lower() or clean.lower() == f"subject {name.lower()}":
            return name
    return None


def parse(pages: list[str]) -> Proposal:
    text = "\n".join(pages)
    proposal = Proposal(nodes=[])
    m = RE_SESSION.search(text[:20000])
    if m:
        proposal.session = f"{m.group(1)}–{m.group(2)[-2:]}"
    for needle, short in AUTHORITIES:
        if needle.lower() in text[:20000].lower():
            proposal.authority = short
            break
    m = RE_CLASS.search(text[:8000])
    if m:
        proposal.level = f"{m.group(1).title()} {m.group(2).upper()}"
    for m in RE_DATE.finditer(text):
        window = text[max(0, m.start() - 80):m.end() + 20].lower()
        if any(w in window for w in ("exam", "test", "assessment", "board")):
            proposal.dates.append(f"{m.group(0)} (near: “{text[max(0, m.start() - 40):m.start()].strip()[-40:]}”)")

    subject: ProposedNode | None = None
    unit: ProposedNode | None = None
    chapter: ProposedNode | None = None
    in_outcomes = False

    def container() -> list[ProposedNode]:
        if unit is not None:
            return unit.children
        if subject is not None:
            return subject.children
        return proposal.nodes

    for page_no, page in enumerate(pages, start=1):
        for raw in page.splitlines():
            line = raw.strip()
            if not line or len(line) > 220:
                continue
            ref = f"p. {page_no}"
            name = _is_subject(line)
            if name:
                subject = ProposedNode("subject", name, 0.8, ref)
                proposal.nodes.append(subject)
                unit = chapter = None
                in_outcomes = False
                continue
            m = RE_UNIT.match(line)
            if m and len(m.group(2)) >= 3:
                title, weight = _clean_title(m.group(2))
                unit = ProposedNode("unit", f"Unit {m.group(1).upper()}: {title}" if title else f"Unit {m.group(1)}",
                                    0.85, ref, weight)
                (subject.children if subject else proposal.nodes).append(unit)
                chapter = None
                in_outcomes = False
                continue
            m = RE_CHAPTER.match(line)
            if m and len(m.group(2)) >= 3:
                title, weight = _clean_title(m.group(2))
                chapter = ProposedNode("chapter", title, 0.9, ref, weight)
                container().append(chapter)
                in_outcomes = False
                continue
            if RE_OUTCOMES.match(line):
                in_outcomes = True
                continue
            m = RE_NUMBERED.match(line)
            if m and not in_outcomes:
                title, weight = _clean_title(m.group(2))
                if len(title) >= 3 and not title.endswith("?"):
                    chapter = ProposedNode("chapter", title, 0.65, ref, weight)
                    container().append(chapter)
                    continue
            m = RE_BULLET.match(line)
            if m and chapter is not None:
                title, _ = _clean_title(m.group(1))
                if len(title) >= 3:
                    kind = "objective" if in_outcomes else "topic"
                    chapter.children.append(ProposedNode(kind, title, 0.5 if kind == "topic" else 0.45, ref))

    _flag(proposal)
    blank = [i + 1 for i, p in enumerate(pages) if len(p.strip()) < 15]
    if blank:
        proposal.flags.append(f"{len(blank)} page(s) had no readable text and were not analysed.")
    if not proposal.nodes:
        proposal.flags.append("No chapters or units were recognised. You can type the course map yourself, "
                              "or paste a chapter list (one per line).")
    return proposal


def _flag(proposal: Proposal) -> None:
    def walk(nodes: list[ProposedNode]) -> None:
        seen: dict[str, ProposedNode] = {}
        for n in nodes:
            key = re.sub(r"\W+", " ", n.title.lower()).strip()
            if key in seen:
                n.flags.append("Duplicate of an item above — probably repeated in the document")
                n.skip = True
            else:
                seen[key] = n
            if n.confidence < 0.6 and "Duplicate" not in " ".join(n.flags):
                n.flags.append("Uncertain: recognised from a bullet point")
            walk(n.children)

    walk(proposal.nodes)


def from_lines(text: str, kind: str = "chapter") -> list[ProposedNode]:
    """A pasted list (one item per line; indent with spaces or '-' for sub-items) as nodes."""
    out: list[ProposedNode] = []
    parent: ProposedNode | None = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        child = raw.startswith(("  ", "\t", "-", "•", "*"))
        title = re.sub(r"^[\s\-•*\d.)]+", "", raw).strip()
        if not title:
            continue
        if child and parent is not None:
            parent.children.append(ProposedNode("topic", title[:200], 1.0, "typed"))
        else:
            parent = ProposedNode(kind, title[:200], 1.0, "typed")
            out.append(parent)
    return out
