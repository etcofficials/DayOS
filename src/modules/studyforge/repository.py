"""StudyForge data access (no Qt). One facade, ``StudyForge``, groups the repositories."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from typing import Any, Iterable

from src.database import Database
from src.modules.studyforge.models import (
    ASSERTION_OPTIONS,
    NODE_KINDS,
    QTYPES,
    Answer,
    Attempt,
    Blueprint,
    Course,
    Document,
    Flashcard,
    Material,
    Node,
    Question,
    Section,
    Test,
    TestItem,
    TopicState,
)
from src.models import from_row
from src.repositories.base import Repository, clean_text, optional_id
from src.repositories.notes import normalize_tags
from src.services.dates import ValidationError, iso, now_stamp, parse_date, today

COURSE_KINDS = {"school": "School", "college": "College / university", "exam": "Exam preparation",
                "skill": "Skill", "custom": "Other"}


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").casefold()).strip()
    return re.sub(r"[^\w\s]", "", text)


def content_hash(qtype: str, text: str, options: list[str]) -> str:
    base = qtype + "|" + normalize_text(text) + "|" + "|".join(normalize_text(o) for o in options)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


class DuplicateQuestion(ValidationError):
    def __init__(self, existing_id: int) -> None:
        super().__init__("This question is already in the bank for this course.")
        self.existing_id = existing_id


# -- courses, nodes, documents ------------------------------------------------------------

class CourseRepository(Repository):
    def create(self, name: str, kind: str = "custom", session: str = "", authority: str = "", level: str = "",
               description: str = "") -> int:
        if kind not in COURSE_KINDS:
            raise ValidationError("Unknown course type.")
        name = clean_text(name, field="Course name", required=True, max_len=120)
        stamp = now_stamp()
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO sf_courses (name, kind, session, authority, level, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, kind, clean_text(session, field="Session", max_len=40),
                 clean_text(authority, field="Board or authority", max_len=80),
                 clean_text(level, field="Level", max_len=60), clean_text(description, field="Description", max_len=2000),
                 stamp, stamp))

    def update(self, course_id: int, **fields: Any) -> None:
        allowed = {"name": 120, "session": 40, "authority": 80, "level": 60, "description": 2000}
        data = {k: clean_text(v, field=k.title(), required=(k == "name"), max_len=allowed[k])
                for k, v in fields.items() if k in allowed}
        if "kind" in fields:
            if fields["kind"] not in COURSE_KINDS:
                raise ValidationError("Unknown course type.")
            data["kind"] = fields["kind"]
        if "status" in fields:
            data["status"] = "archived" if fields["status"] == "archived" else "active"
        if not data:
            return
        data["updated_at"] = now_stamp()
        with self.db.transaction():
            self.db.execute(f"UPDATE sf_courses SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                            [*data.values(), course_id])

    def delete(self, course_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM sf_courses WHERE id = ?", (course_id,))

    def get(self, course_id: int) -> Course | None:
        row = self.db.query_one("SELECT * FROM sf_courses WHERE id = ?", (course_id,))
        return from_row(Course, row) if row else None

    def list(self, include_archived: bool = False) -> list[Course]:
        sql = "SELECT * FROM sf_courses" + ("" if include_archived else " WHERE status = 'active'")
        return [from_row(Course, r) for r in self.db.query(sql + " ORDER BY status, name COLLATE NOCASE")]

    # -- nodes --------------------------------------------------------------------------
    def add_node(self, course_id: int, kind: str, title: str, parent_id: int | None = None,
                 source_doc_id: int | None = None, source_ref: str = "", confidence: float | None = None,
                 subject_id: int | None = None, exam_date: date | None = None) -> int:
        if kind not in NODE_KINDS:
            raise ValidationError("Unknown level in the course map.")
        title = clean_text(title, field="Title", required=True, max_len=200)
        if parent_id is not None:
            parent = self.node(parent_id)
            if parent is None or parent.course_id != course_id:
                raise ValidationError("That parent item isn't part of this course.")
        position = int(self.db.scalar(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM sf_nodes WHERE course_id = ? AND parent_id IS ?",
            (course_id, parent_id), 0))
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO sf_nodes (course_id, parent_id, kind, title, position, subject_id, exam_date, "
                "source_doc_id, source_ref, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (course_id, parent_id, kind, title, position, optional_id(subject_id), iso(exam_date) if exam_date else None,
                 optional_id(source_doc_id), clean_text(source_ref, field="Source", max_len=200), confidence,
                 now_stamp()))

    def update_node(self, node_id: int, **fields: Any) -> None:
        data: dict[str, Any] = {}
        if "title" in fields:
            data["title"] = clean_text(fields["title"], field="Title", required=True, max_len=200)
        if "kind" in fields:
            if fields["kind"] not in NODE_KINDS:
                raise ValidationError("Unknown level in the course map.")
            data["kind"] = fields["kind"]
        if "notes" in fields:
            data["notes"] = clean_text(fields["notes"], field="Notes", max_len=5000)
        if "exam_date" in fields:
            d = parse_date(fields["exam_date"], field="Exam date")
            data["exam_date"] = iso(d) if d else None
        if "weight" in fields:
            w = fields["weight"]
            data["weight"] = None if w in (None, "") else float(w)
        if "subject_id" in fields:
            data["subject_id"] = optional_id(fields["subject_id"])
        if not data:
            return
        with self.db.transaction():
            self.db.execute(f"UPDATE sf_nodes SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                            [*data.values(), node_id])

    def move_node(self, node_id: int, delta: int) -> None:
        node = self.node(node_id)
        if node is None:
            return
        siblings = [n.id for n in self.children(node.course_id, node.parent_id)]
        i = siblings.index(node_id)
        j = max(0, min(len(siblings) - 1, i + delta))
        if i == j:
            return
        siblings.insert(j, siblings.pop(i))
        with self.db.transaction():
            for pos, nid in enumerate(siblings):
                self.db.execute("UPDATE sf_nodes SET position = ? WHERE id = ?", (pos, nid))

    def delete_node(self, node_id: int) -> None:
        """Deletes the node and its sub-items. Questions and cards linked to them stay (unlinked)."""
        with self.db.transaction():
            self.db.execute("DELETE FROM sf_nodes WHERE id = ?", (node_id,))

    def node(self, node_id: int) -> Node | None:
        row = self.db.query_one("SELECT * FROM sf_nodes WHERE id = ?", (node_id,))
        return from_row(Node, row) if row else None

    def children(self, course_id: int, parent_id: int | None) -> list[Node]:
        rows = self.db.query("SELECT * FROM sf_nodes WHERE course_id = ? AND parent_id IS ? ORDER BY position, id",
                             (course_id, parent_id))
        return [from_row(Node, r) for r in rows]

    def nodes(self, course_id: int) -> list[Node]:
        rows = self.db.query("SELECT * FROM sf_nodes WHERE course_id = ? ORDER BY parent_id IS NOT NULL, position, id",
                             (course_id,))
        return [from_row(Node, r) for r in rows]

    def tree(self, course_id: int) -> list[Node]:
        nodes = self.nodes(course_id)
        by_id = {n.id: n for n in nodes}
        roots: list[Node] = []
        for n in sorted(nodes, key=lambda x: (x.position, x.id)):
            parent = by_id.get(n.parent_id) if n.parent_id else None
            (parent.children if parent else roots).append(n)
        return roots

    def descendants(self, node_ids: Iterable[int]) -> set[int]:
        ids = {int(i) for i in node_ids}
        if not ids:
            return set()
        marks = ",".join("?" for _ in ids)
        rows = self.db.query(
            f"""WITH RECURSIVE sub(id) AS (SELECT id FROM sf_nodes WHERE id IN ({marks})
                UNION SELECT n.id FROM sf_nodes n JOIN sub ON n.parent_id = sub.id) SELECT id FROM sub""",
            list(ids))
        return {int(r[0]) for r in rows}

    def path(self, node_id: int) -> list[Node]:
        out: list[Node] = []
        node = self.node(node_id)
        guard = 0
        while node is not None and guard < 20:
            out.insert(0, node)
            node = self.node(node.parent_id) if node.parent_id else None
            guard += 1
        return out

    def path_text(self, node_id: int | None) -> str:
        return " › ".join(n.title for n in self.path(node_id)) if node_id else ""

    def chapter_of(self, node_id: int) -> Node | None:
        for n in reversed(self.path(node_id)):
            if n.kind == "chapter":
                return n
        return None

    def exam_date_for(self, node_id: int) -> date | None:
        """Nearest exam date set on the node or any of its ancestors."""
        for n in reversed(self.path(node_id)):
            if n.exam_date:
                return n.exam_day
        return None

    def topic_nodes(self, course_id: int) -> list[Node]:
        """Leaf-level study units (topics, or chapters without topics) for revision."""
        nodes = self.nodes(course_id)
        parents = {n.parent_id for n in nodes if n.parent_id}
        return [n for n in nodes if n.kind in ("chapter", "topic", "objective", "unit") and n.id not in parents]

    def import_map(self, course_id: int, items: list[dict], parent_id: int | None = None,
                   source_doc_id: int | None = None) -> int:
        """Insert a reviewed course map: [{"kind", "title", "children": [...], "source_ref", "confidence"}]."""
        count = 0
        with self.db.transaction():
            for item in items:
                if not str(item.get("title", "")).strip() or item.get("skip"):
                    continue
                nid = self.add_node(course_id, item.get("kind", "chapter"), item["title"], parent_id, source_doc_id,
                                    str(item.get("source_ref", "")), item.get("confidence"))
                count += 1 + self.import_map(course_id, item.get("children", []), nid, source_doc_id)
        return count

    # -- documents ------------------------------------------------------------------------
    def add_document(self, course_id: int | None, title: str, pages: list[str], *, filename: str = "", path: str = "",
                     kind: str = "other", official: bool = False, sha256: str = "", session: str = "",
                     authority: str = "", version: str = "", status: str = "parsed",
                     problems: list[str] | None = None) -> int:
        title = clean_text(title, field="Title", required=True, max_len=200)
        with self.db.transaction():
            doc_id = self.db.insert(
                "INSERT INTO sf_documents (course_id, title, filename, path, kind, official, sha256, pages, text_chars, "
                "session, authority, syllabus_version, status, problems, imported_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (course_id, title, filename[:255], path[:1000], kind, int(official), sha256, len(pages),
                 sum(len(p) for p in pages), session[:40], authority[:80], version[:40], status,
                 json.dumps(problems or []), now_stamp()))
            self.db.executemany("INSERT INTO sf_document_pages (document_id, page, text) VALUES (?, ?, ?)",
                                [(doc_id, i + 1, text) for i, text in enumerate(pages)])
        return doc_id

    def documents(self, course_id: int | None = None) -> list[Document]:
        if course_id is None:
            rows = self.db.query("SELECT * FROM sf_documents ORDER BY imported_at DESC")
        else:
            rows = self.db.query("SELECT * FROM sf_documents WHERE course_id = ? ORDER BY imported_at DESC", (course_id,))
        return [from_row(Document, r) for r in rows]

    def document(self, doc_id: int) -> Document | None:
        row = self.db.query_one("SELECT * FROM sf_documents WHERE id = ?", (doc_id,))
        return from_row(Document, row) if row else None

    def document_pages(self, doc_id: int) -> list[str]:
        return [r[0] for r in self.db.query("SELECT text FROM sf_document_pages WHERE document_id = ? ORDER BY page",
                                            (doc_id,))]

    def find_document_by_hash(self, sha256: str, course_id: int | None) -> Document | None:
        row = self.db.query_one("SELECT * FROM sf_documents WHERE sha256 = ? AND course_id IS ?", (sha256, course_id))
        return from_row(Document, row) if row else None

    def delete_document(self, doc_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM sf_documents WHERE id = ?", (doc_id,))


# -- question bank --------------------------------------------------------------------------

def validate_question(qtype: str, text: str, options: list[str], answer: Any, marks: float,
                      rubric: list[dict] | None = None, allow_missing_key: bool = False) -> tuple[list[str], str]:
    """Check a question is well-formed. Returns (options, answer as stored text).

    ``allow_missing_key`` is used only for questions imported from papers without a marking
    scheme: they are stored without a key and always marked by hand.
    """
    if allow_missing_key and qtype in ("mcq", "assertion", "multi", "tf", "fill", "numerical")             and not str(answer).strip():
        if qtype not in QTYPES:
            raise ValidationError("Unknown question type.")
        opts = list(ASSERTION_OPTIONS) if qtype == "assertion" else [str(o).strip() for o in options if str(o).strip()]
        return opts, ""
    if qtype not in QTYPES:
        raise ValidationError("Unknown question type.")
    if marks is None or float(marks) <= 0:
        raise ValidationError("Marks must be more than zero.")
    options = [str(o).strip() for o in options if str(o).strip()]
    if qtype == "assertion":
        options = list(ASSERTION_OPTIONS)
    if qtype in ("mcq", "assertion"):
        if len(options) < 2:
            raise ValidationError("A multiple-choice question needs at least two options.")
        try:
            idx = int(answer)
        except (TypeError, ValueError):
            raise ValidationError("Choose the correct option.") from None
        if not 0 <= idx < len(options):
            raise ValidationError("Choose the correct option.")
        return options, str(idx)
    if qtype == "multi":
        if len(options) < 2:
            raise ValidationError("A multiple-select question needs at least two options.")
        idx = sorted({int(i) for i in (answer if isinstance(answer, (list, tuple, set)) else json.loads(answer or "[]"))})
        if not idx or any(not 0 <= i < len(options) for i in idx):
            raise ValidationError("Tick at least one correct option.")
        return options, json.dumps(idx)
    if qtype == "tf":
        value = str(answer).strip().lower()
        if value not in ("true", "false"):
            raise ValidationError("Choose whether the statement is true or false.")
        return [], value
    if qtype == "fill":
        accepted = [a.strip() for a in str(answer).split("|") if a.strip()]
        if not accepted:
            raise ValidationError("Give the accepted answer (separate alternatives with |).")
        return [], "|".join(accepted)
    if qtype == "numerical":
        data = answer if isinstance(answer, dict) else json.loads(answer) if str(answer).strip().startswith("{") \
            else {"value": answer}
        try:
            value = float(str(data.get("value")).replace(",", ""))
            tol = float(data.get("tolerance") or 0)
        except (TypeError, ValueError):
            raise ValidationError("A numerical answer needs a number (and optionally a tolerance).") from None
        if tol < 0:
            raise ValidationError("Tolerance can't be negative.")
        return [], json.dumps({"value": value, "tolerance": tol, "unit": str(data.get("unit") or "")[:20]})
    if qtype == "match":
        pairs = [o for o in options if "=>" in o]
        if len(pairs) < 2 or len(pairs) != len(options):
            raise ValidationError("Write each matching pair as “left => right”, one per line (at least two).")
        return pairs, ""
    # subjective: model answer and/or rubric
    if not str(answer).strip() and not rubric:
        raise ValidationError("Add a model answer or marking points so the answer can be checked.")
    return options, clean_text(str(answer), field="Model answer", max_len=20000)


class QuestionBank(Repository):
    _SELECT = ("SELECT q.*, n.title AS node_title, "
               "(SELECT COUNT(*) FROM sf_test_items i JOIN sf_answers a ON a.item_id = i.id "
               " WHERE i.question_id = q.id AND a.marks IS NOT NULL) AS times_used, "
               "(SELECT COALESCE(SUM(a.marks / i.marks), 0) FROM sf_test_items i JOIN sf_answers a ON a.item_id = i.id "
               " WHERE i.question_id = q.id AND a.marks IS NOT NULL) AS times_correct "
               "FROM sf_questions q LEFT JOIN sf_nodes n ON n.id = q.node_id")

    def add(self, course_id: int | None, qtype: str, text: str, *, node_id: int | None = None,
            options: list[str] | None = None, answer: Any = "", explanation: str = "", marks: float = 1,
            difficulty: int = 2, rubric: list[dict] | None = None, origin: str = "user", verified: bool = False,
            source_doc_id: int | None = None, source_ref: str = "", tags: str = "", media_path: str = "",
            allow_missing_key: bool = False) -> int:
        text = clean_text(text, field="Question", required=True, max_len=20000)
        if origin not in ("official", "imported", "user", "ai"):
            raise ValidationError("Unknown question origin.")
        if not 1 <= int(difficulty) <= 5:
            raise ValidationError("Difficulty must be 1 to 5.")
        opts, stored_answer = validate_question(qtype, text, options or [], answer, float(marks), rubric,
                                                allow_missing_key and origin in ("official", "imported"))
        digest = content_hash(qtype, text, opts)
        existing = self.db.scalar("SELECT id FROM sf_questions WHERE course_id IS ? AND content_hash = ?",
                                  (course_id, digest))
        if existing:
            raise DuplicateQuestion(int(existing))
        stamp = now_stamp()
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO sf_questions (course_id, node_id, qtype, difficulty, marks, text, options, answer, explanation, "
                "rubric, origin, verified, source_doc_id, source_ref, tags, media_path, content_hash, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (course_id, optional_id(node_id), qtype, int(difficulty), float(marks), text, json.dumps(opts),
                 stored_answer, clean_text(explanation, field="Explanation", max_len=20000),
                 json.dumps(_clean_rubric(rubric)), origin, int(bool(verified)), optional_id(source_doc_id),
                 clean_text(source_ref, field="Source", max_len=200), normalize_tags(tags), media_path[:1000],
                 digest, stamp, stamp))

    def update(self, question_id: int, **fields: Any) -> None:
        q = self.get(question_id)
        if q is None:
            raise ValidationError("This question no longer exists.")
        qtype = fields.get("qtype", q.qtype)
        text = clean_text(fields.get("text", q.text), field="Question", required=True, max_len=20000)
        rubric = fields.get("rubric", q.rubric_points)
        opts, stored_answer = validate_question(qtype, text, fields.get("options", q.option_list),
                                                fields.get("answer", q.answer), float(fields.get("marks", q.marks)), rubric,
                                                q.origin in ("official", "imported"))
        digest = content_hash(qtype, text, opts)
        clash = self.db.scalar("SELECT id FROM sf_questions WHERE course_id IS ? AND content_hash = ? AND id != ?",
                               (q.course_id, digest, question_id))
        if clash:
            raise DuplicateQuestion(int(clash))
        data = {
            "qtype": qtype, "text": text, "options": json.dumps(opts), "answer": stored_answer,
            "marks": float(fields.get("marks", q.marks)), "difficulty": int(fields.get("difficulty", q.difficulty)),
            "explanation": clean_text(fields.get("explanation", q.explanation), field="Explanation", max_len=20000),
            "rubric": json.dumps(_clean_rubric(rubric)), "node_id": optional_id(fields.get("node_id", q.node_id)),
            "verified": int(bool(fields.get("verified", q.verified))), "tags": normalize_tags(fields.get("tags", q.tags)),
            "source_ref": clean_text(fields.get("source_ref", q.source_ref), field="Source", max_len=200),
            "content_hash": digest, "updated_at": now_stamp(),
        }
        with self.db.transaction():
            self.db.execute(f"UPDATE sf_questions SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                            [*data.values(), question_id])

    def set_verified(self, question_id: int, verified: bool) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE sf_questions SET verified = ?, updated_at = ? WHERE id = ?",
                            (int(verified), now_stamp(), question_id))

    def delete(self, question_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM sf_questions WHERE id = ?", (question_id,))

    def get(self, question_id: int) -> Question | None:
        row = self.db.query_one(self._SELECT + " WHERE q.id = ?", (question_id,))
        return from_row(Question, row) if row else None

    def list(self, course_id: int | None = None, node_ids: set[int] | None = None, qtypes: set[str] | None = None,
             origin: str | None = None, verified: bool | None = None, search: str = "", difficulty: tuple[int, int] | None = None,
             limit: int = 2000) -> list[Question]:
        where, params = [], []
        if course_id is not None:
            where.append("q.course_id = ?")
            params.append(course_id)
        if node_ids is not None:
            if not node_ids:
                return []
            where.append(f"q.node_id IN ({','.join('?' for _ in node_ids)})")
            params.extend(node_ids)
        if qtypes:
            where.append(f"q.qtype IN ({','.join('?' for _ in qtypes)})")
            params.extend(qtypes)
        if origin:
            where.append("q.origin = ?")
            params.append(origin)
        if verified is not None:
            where.append("q.verified = ?")
            params.append(int(verified))
        if difficulty:
            where.append("q.difficulty BETWEEN ? AND ?")
            params.extend(difficulty)
        if search.strip():
            where.append("(q.text LIKE ? OR q.tags LIKE ? OR q.explanation LIKE ?)")
            params.extend([f"%{search.strip()}%"] * 3)
        sql = self._SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY q.node_id, q.id LIMIT ?"
        params.append(limit)
        return [from_row(Question, r) for r in self.db.query(sql, params)]

    def counts_by_node(self, course_id: int) -> dict[int, int]:
        return {int(r[0]): int(r[1]) for r in self.db.query(
            "SELECT node_id, COUNT(*) FROM sf_questions WHERE course_id = ? AND node_id IS NOT NULL GROUP BY node_id",
            (course_id,))}

    def recently_used(self, course_id: int, tests: int = 3) -> set[int]:
        rows = self.db.query(
            "SELECT DISTINCT i.question_id FROM sf_test_items i WHERE i.test_id IN "
            "(SELECT id FROM sf_tests WHERE course_id = ? ORDER BY id DESC LIMIT ?) AND i.question_id IS NOT NULL",
            (course_id, tests))
        return {int(r[0]) for r in rows}

    # -- import / export ---------------------------------------------------------------------
    def export(self, course_id: int | None = None) -> list[dict]:
        out = []
        for q in self.list(course_id):
            out.append({"qtype": q.qtype, "text": q.text, "options": q.option_list, "answer": q.answer,
                        "explanation": q.explanation, "marks": q.marks, "difficulty": q.difficulty,
                        "rubric": q.rubric_points, "origin": q.origin, "verified": bool(q.verified),
                        "source_ref": q.source_ref, "tags": q.tags, "topic": q.node_title or ""})
        return out

    def import_items(self, course_id: int, items: list[dict], node_lookup: dict[str, int] | None = None,
                     default_origin: str = "imported") -> tuple[int, int, list[str]]:
        """Add questions from an exported list. Returns (added, duplicates skipped, problems)."""
        added = dupes = 0
        problems: list[str] = []
        node_lookup = {k.casefold(): v for k, v in (node_lookup or {}).items()}
        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                problems.append(f"Item {i}: not a question.")
                continue
            origin = item.get("origin", default_origin)
            if origin == "official":
                origin = "imported"  # an exported file can't prove a question is official
            try:
                self.add(course_id, str(item.get("qtype", "")), str(item.get("text", "")),
                         node_id=node_lookup.get(str(item.get("topic", "")).casefold()),
                         options=list(item.get("options") or []), answer=item.get("answer", ""),
                         explanation=str(item.get("explanation", "")), marks=float(item.get("marks", 1)),
                         difficulty=int(item.get("difficulty", 2)), rubric=item.get("rubric") or [],
                         origin=origin if origin in ("imported", "user", "ai") else "imported",
                         verified=bool(item.get("verified")) and origin != "ai",
                         source_ref=str(item.get("source_ref", "")), tags=str(item.get("tags", "")))
                added += 1
            except DuplicateQuestion:
                dupes += 1
            except (ValidationError, ValueError, TypeError) as exc:
                problems.append(f"Item {i}: {exc}")
        return added, dupes, problems


def _clean_rubric(rubric: list[dict] | None) -> list[dict]:
    out = []
    for point in rubric or []:
        if not isinstance(point, dict):
            continue
        text = str(point.get("text", "")).strip()
        if not text:
            continue
        try:
            marks = float(point.get("marks", 1))
        except (TypeError, ValueError):
            marks = 1.0
        out.append({"text": text[:500], "marks": max(0.0, marks)})
    return out


# -- blueprints, tests, attempts ---------------------------------------------------------

class TestRepository(Repository):
    def save_blueprint(self, course_id: int | None, name: str, max_marks: float, duration_min: int,
                       sections: list[Section], *, blueprint_id: int | None = None, subject_node_id: int | None = None,
                       session: str = "", instructions: str = "", status: str = "user", source_doc_id: int | None = None,
                       source_note: str = "", version: str = "", coverage: dict[int, float] | None = None) -> int:
        name = clean_text(name, field="Blueprint name", required=True, max_len=120)
        if status not in ("verified", "provisional", "user"):
            raise ValidationError("Unknown blueprint status.")
        if status == "verified" and not (source_doc_id or source_note.strip()):
            raise ValidationError("A blueprint can only be marked verified with the official source it came from.")
        if float(max_marks) <= 0 or int(duration_min) <= 0:
            raise ValidationError("Maximum marks and duration must be more than zero.")
        if not sections:
            raise ValidationError("Add at least one section.")
        for s in sections:
            if s.qtype not in QTYPES or s.count <= 0 or s.marks_each <= 0:
                raise ValidationError(f"Section “{s.name or s.qtype}” needs a question type, a count and marks.")
        total = sum(s.total for s in sections)
        if abs(total - float(max_marks)) > 1e-6:
            raise ValidationError(f"The sections add up to {total:g} marks, not {float(max_marks):g}. Adjust the counts "
                                  "or the maximum marks.")
        data = dict(course_id=course_id, subject_node_id=optional_id(subject_node_id), name=name,
                    session=clean_text(session, field="Session", max_len=40), max_marks=float(max_marks),
                    duration_min=int(duration_min), instructions=clean_text(instructions, field="Instructions", max_len=10000),
                    status=status, source_doc_id=optional_id(source_doc_id),
                    source_note=clean_text(source_note, field="Source", max_len=500),
                    version=clean_text(version, field="Version", max_len=40),
                    sections=json.dumps([s.to_dict() for s in sections]),
                    coverage=json.dumps({str(k): v for k, v in (coverage or {}).items()}), updated_at=now_stamp())
        with self.db.transaction():
            if blueprint_id:
                self.db.execute(f"UPDATE sf_blueprints SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                                [*data.values(), blueprint_id])
                return blueprint_id
            data["created_at"] = data["updated_at"]
            return self.db.insert(f"INSERT INTO sf_blueprints ({', '.join(data)}) VALUES ({', '.join('?' for _ in data)})",
                                  list(data.values()))

    def blueprints(self, course_id: int | None = None) -> list[Blueprint]:
        sql = "SELECT * FROM sf_blueprints" + (" WHERE course_id = ?" if course_id is not None else "")
        return [from_row(Blueprint, r) for r in self.db.query(sql + " ORDER BY name",
                                                               (course_id,) if course_id is not None else ())]

    def blueprint(self, blueprint_id: int) -> Blueprint | None:
        row = self.db.query_one("SELECT * FROM sf_blueprints WHERE id = ?", (blueprint_id,))
        return from_row(Blueprint, row) if row else None

    def delete_blueprint(self, blueprint_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM sf_blueprints WHERE id = ?", (blueprint_id,))

    # -- tests ------------------------------------------------------------------------------
    def create_test(self, course_id: int | None, title: str, items: list[dict], *, blueprint_id: int | None = None,
                    mode: str = "practice", duration_min: int | None = None, config: dict | None = None,
                    instructions: str = "") -> int:
        """``items``: [{"question": Question, "section": str, "marks": float, "choice_group": int|None}]."""
        if not items:
            raise ValidationError("The test has no questions.")
        if mode not in ("practice", "timed"):
            raise ValidationError("Unknown test mode.")
        if mode == "timed" and not duration_min:
            raise ValidationError("A timed test needs a duration.")
        groups: dict[int, list[float]] = {}
        for it in items:
            if it.get("choice_group") is not None:
                groups.setdefault(int(it["choice_group"]), []).append(float(it["marks"]))
        total = sum(float(it["marks"]) for it in items if it.get("choice_group") is None)
        total += sum(max(v) for v in groups.values())
        title = clean_text(title, field="Test title", required=True, max_len=150)
        with self.db.transaction():
            test_id = self.db.insert(
                "INSERT INTO sf_tests (course_id, blueprint_id, title, mode, duration_min, total_marks, config, "
                "instructions, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (course_id, optional_id(blueprint_id), title, mode, duration_min, total, json.dumps(config or {}),
                 clean_text(instructions, field="Instructions", max_len=10000), now_stamp()))
            for pos, it in enumerate(items):
                q: Question = it["question"]
                self.db.execute(
                    "INSERT INTO sf_test_items (test_id, position, section, question_id, snapshot, marks, choice_group) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (test_id, pos, str(it.get("section", "")), q.id or None, json.dumps(q.snapshot()), float(it["marks"]),
                     it.get("choice_group")))
        return test_id

    def tests(self, course_id: int | None = None, limit: int = 200) -> list[Test]:
        sql = ("SELECT t.*, (SELECT COUNT(*) FROM sf_attempts a WHERE a.test_id = t.id AND a.status != 'in_progress') "
               "AS attempts, (SELECT MAX(a.score * 100.0 / a.max_score) FROM sf_attempts a WHERE a.test_id = t.id "
               "AND a.status = 'marked' AND a.max_score > 0) AS best FROM sf_tests t")
        params: tuple = ()
        if course_id is not None:
            sql += " WHERE t.course_id = ?"
            params = (course_id,)
        return [from_row(Test, r) for r in self.db.query(sql + " ORDER BY t.id DESC LIMIT ?", (*params, limit))]

    def test(self, test_id: int) -> Test | None:
        row = self.db.query_one("SELECT * FROM sf_tests WHERE id = ?", (test_id,))
        return from_row(Test, row) if row else None

    def items(self, test_id: int) -> list[TestItem]:
        return [from_row(TestItem, r) for r in self.db.query(
            "SELECT * FROM sf_test_items WHERE test_id = ? ORDER BY position", (test_id,))]

    def delete_test(self, test_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM sf_tests WHERE id = ?", (test_id,))

    # -- attempts --------------------------------------------------------------------------
    def start_attempt(self, test_id: int) -> int:
        with self.db.transaction():
            return self.db.insert("INSERT INTO sf_attempts (test_id, started_at) VALUES (?, ?)", (test_id, now_stamp()))

    def open_attempt(self, test_id: int) -> Attempt | None:
        row = self.db.query_one("SELECT * FROM sf_attempts WHERE test_id = ? AND status = 'in_progress' "
                                "ORDER BY id DESC LIMIT 1", (test_id,))
        return from_row(Attempt, row) if row else None

    def unfinished_attempts(self) -> list[Attempt]:
        rows = self.db.query("SELECT a.*, t.title AS test_title FROM sf_attempts a JOIN sf_tests t ON t.id = a.test_id "
                             "WHERE a.status = 'in_progress' ORDER BY a.started_at DESC")
        return [from_row(Attempt, r) for r in rows]

    def attempt(self, attempt_id: int) -> Attempt | None:
        row = self.db.query_one("SELECT a.*, t.title AS test_title FROM sf_attempts a JOIN sf_tests t ON t.id = a.test_id "
                                "WHERE a.id = ?", (attempt_id,))
        return from_row(Attempt, row) if row else None

    def attempts(self, course_id: int | None = None, limit: int = 300) -> list[Attempt]:
        sql = ("SELECT a.*, t.title AS test_title FROM sf_attempts a JOIN sf_tests t ON t.id = a.test_id "
               "WHERE a.status != 'in_progress'")
        params: list = []
        if course_id is not None:
            sql += " AND t.course_id = ?"
            params.append(course_id)
        sql += " ORDER BY a.submitted_at DESC LIMIT ?"
        params.append(limit)
        return [from_row(Attempt, r) for r in self.db.query(sql, params)]

    def save_answer(self, attempt_id: int, item_id: int, response: str, flagged: bool = False, time_s: int = 0) -> None:
        """Autosave one answer while the test is in progress."""
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO sf_answers (attempt_id, item_id, response, flagged, time_s, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(attempt_id, item_id) DO UPDATE SET response = excluded.response, flagged = excluded.flagged, "
                "time_s = sf_answers.time_s + excluded.time_s, updated_at = excluded.updated_at",
                (attempt_id, item_id, response[:20000], int(flagged), max(0, int(time_s)), now_stamp()))

    def set_elapsed(self, attempt_id: int, elapsed_s: int) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE sf_attempts SET elapsed_s = ? WHERE id = ?", (int(elapsed_s), attempt_id))

    def answers(self, attempt_id: int) -> dict[int, Answer]:
        return {int(r["item_id"]): from_row(Answer, r) for r in self.db.query(
            "SELECT * FROM sf_answers WHERE attempt_id = ?", (attempt_id,))}

    def set_mark(self, attempt_id: int, item_id: int, marks: float | None, marker: str, correct: int | None,
                 feedback: str = "") -> None:
        if marker not in ("none", "auto", "self", "ai"):
            raise ValidationError("Unknown marker.")
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO sf_answers (attempt_id, item_id, marks, marker, correct, feedback, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(attempt_id, item_id) DO UPDATE SET marks = excluded.marks, "
                "marker = excluded.marker, correct = excluded.correct, feedback = excluded.feedback, "
                "updated_at = excluded.updated_at",
                (attempt_id, item_id, marks, marker, correct, feedback[:5000], now_stamp()))

    def finish_attempt(self, attempt_id: int, score: float, max_score: float, fully_marked: bool,
                       has_estimates: bool) -> None:
        with self.db.transaction():
            self.db.execute(
                "UPDATE sf_attempts SET submitted_at = COALESCE(submitted_at, ?), status = ?, score = ?, max_score = ?, "
                "has_estimates = ? WHERE id = ?",
                (now_stamp(), "marked" if fully_marked else "submitted", score, max_score, int(has_estimates), attempt_id))

    def discard_attempt(self, attempt_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM sf_attempts WHERE id = ? AND status = 'in_progress'", (attempt_id,))


# -- revision state, flashcards, materials -------------------------------------------------

class RevisionRepository(Repository):
    def state(self, node_id: int) -> TopicState:
        row = self.db.query_one("SELECT * FROM sf_topic_state WHERE node_id = ?", (node_id,))
        return from_row(TopicState, row) if row else TopicState(node_id=node_id)

    def states(self, node_ids: Iterable[int]) -> dict[int, TopicState]:
        ids = list(node_ids)
        if not ids:
            return {}
        rows = self.db.query(f"SELECT * FROM sf_topic_state WHERE node_id IN ({','.join('?' for _ in ids)})", ids)
        found = {int(r["node_id"]): from_row(TopicState, r) for r in rows}
        return {i: found.get(i, TopicState(node_id=i)) for i in ids}

    def save_state(self, st: TopicState) -> None:
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO sf_topic_state (node_id, ease, interval_days, due_date, last_practiced, reps, lapses, attempts, "
                "correct, confidence, manual_due, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(node_id) DO UPDATE SET ease = excluded.ease, interval_days = excluded.interval_days, "
                "due_date = excluded.due_date, last_practiced = excluded.last_practiced, reps = excluded.reps, "
                "lapses = excluded.lapses, attempts = excluded.attempts, correct = excluded.correct, "
                "confidence = excluded.confidence, manual_due = excluded.manual_due, updated_at = excluded.updated_at",
                (st.node_id, st.ease, st.interval_days, st.due_date, st.last_practiced, st.reps, st.lapses, st.attempts,
                 st.correct, st.confidence, st.manual_due, now_stamp()))

    def log(self, node_id: int, source: str, score: float, detail: str = "", day: date | None = None) -> None:
        with self.db.transaction():
            self.db.execute("INSERT INTO sf_review_log (node_id, date, source, score, detail, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (node_id, iso(day or today()), source, max(0.0, min(1.0, score)), detail[:300], now_stamp()))

    def history(self, node_id: int, limit: int = 30) -> list[tuple[str, str, float, str]]:
        return [(r[0], r[1], float(r[2]), r[3]) for r in self.db.query(
            "SELECT date, source, score, detail FROM sf_review_log WHERE node_id = ? ORDER BY date DESC, id DESC LIMIT ?",
            (node_id, limit))]

    # -- flashcards ------------------------------------------------------------------------
    def add_card(self, course_id: int | None, front: str, back: str = "", *, node_id: int | None = None,
                 kind: str = "card", source_ref: str = "", ai_generated: bool = False) -> int:
        if kind not in ("card", "formula", "definition", "keyterm", "qa"):
            raise ValidationError("Unknown card type.")
        stamp = now_stamp()
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO sf_flashcards (course_id, node_id, kind, front, back, source_ref, ai_generated, reviewed, "
                "due_date, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (course_id, optional_id(node_id), kind, clean_text(front, field="Front", required=True, max_len=5000),
                 clean_text(back, field="Back", max_len=10000), clean_text(source_ref, field="Source", max_len=200),
                 int(ai_generated), 0 if ai_generated else 1, iso(today()), stamp, stamp))

    def update_card(self, card_id: int, front: str, back: str, node_id: int | None, kind: str,
                    reviewed: bool | None = None) -> None:
        with self.db.transaction():
            self.db.execute(
                "UPDATE sf_flashcards SET front = ?, back = ?, node_id = ?, kind = ?, reviewed = COALESCE(?, reviewed), "
                "updated_at = ? WHERE id = ?",
                (clean_text(front, field="Front", required=True, max_len=5000), clean_text(back, field="Back", max_len=10000),
                 optional_id(node_id), kind, None if reviewed is None else int(reviewed), now_stamp(), card_id))

    def delete_card(self, card_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM sf_flashcards WHERE id = ?", (card_id,))

    def cards(self, course_id: int | None = None, node_ids: set[int] | None = None, due_only: bool = False,
              kind: str | None = None, ref: date | None = None) -> list[Flashcard]:
        sql = ("SELECT c.*, n.title AS node_title FROM sf_flashcards c LEFT JOIN sf_nodes n ON n.id = c.node_id WHERE 1")
        params: list = []
        if course_id is not None:
            sql += " AND c.course_id = ?"
            params.append(course_id)
        if node_ids is not None:
            if not node_ids:
                return []
            sql += f" AND c.node_id IN ({','.join('?' for _ in node_ids)})"
            params.extend(node_ids)
        if due_only:
            sql += " AND (c.due_date IS NULL OR c.due_date <= ?)"
            params.append(iso(ref or today()))
        if kind:
            sql += " AND c.kind = ?"
            params.append(kind)
        return [from_row(Flashcard, r) for r in self.db.query(sql + " ORDER BY c.due_date, c.id", params)]

    def card(self, card_id: int) -> Flashcard | None:
        row = self.db.query_one("SELECT c.*, n.title AS node_title FROM sf_flashcards c LEFT JOIN sf_nodes n "
                                "ON n.id = c.node_id WHERE c.id = ?", (card_id,))
        return from_row(Flashcard, row) if row else None

    def save_card_schedule(self, card: Flashcard) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE sf_flashcards SET ease = ?, interval_days = ?, due_date = ?, reps = ?, lapses = ?, "
                            "updated_at = ? WHERE id = ?",
                            (card.ease, card.interval_days, card.due_date, card.reps, card.lapses, now_stamp(), card.id))


class MaterialRepository(Repository):
    KINDS = {"notes": "Revision notes", "summary": "Chapter summary", "formula_sheet": "Formula sheet",
             "definitions": "Definitions", "keyterms": "Key terms"}

    def add(self, course_id: int | None, title: str, body: str = "", *, kind: str = "notes", node_id: int | None = None,
            source_doc_id: int | None = None, source_ref: str = "", ai_generated: bool = False) -> int:
        if kind not in self.KINDS:
            raise ValidationError("Unknown material type.")
        stamp = now_stamp()
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO sf_materials (course_id, node_id, kind, title, body, source_doc_id, source_ref, ai_generated, "
                "reviewed, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (course_id, optional_id(node_id), kind, clean_text(title, field="Title", required=True, max_len=200),
                 clean_text(body, field="Body", max_len=200000), optional_id(source_doc_id),
                 clean_text(source_ref, field="Source", max_len=200), int(ai_generated), 0 if ai_generated else 1,
                 stamp, stamp))

    def update(self, material_id: int, title: str, body: str, kind: str, node_id: int | None,
               reviewed: bool | None = None) -> None:
        if kind not in self.KINDS:
            raise ValidationError("Unknown material type.")
        with self.db.transaction():
            self.db.execute(
                "UPDATE sf_materials SET title = ?, body = ?, kind = ?, node_id = ?, reviewed = COALESCE(?, reviewed), "
                "updated_at = ? WHERE id = ?",
                (clean_text(title, field="Title", required=True, max_len=200), clean_text(body, field="Body", max_len=200000),
                 kind, optional_id(node_id), None if reviewed is None else int(reviewed), now_stamp(), material_id))

    def delete(self, material_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM sf_materials WHERE id = ?", (material_id,))

    def list(self, course_id: int | None = None, kind: str | None = None, search: str = "") -> list[Material]:
        sql = "SELECT m.*, n.title AS node_title FROM sf_materials m LEFT JOIN sf_nodes n ON n.id = m.node_id WHERE 1"
        params: list = []
        if course_id is not None:
            sql += " AND m.course_id = ?"
            params.append(course_id)
        if kind:
            sql += " AND m.kind = ?"
            params.append(kind)
        if search.strip():
            sql += " AND (m.title LIKE ? OR m.body LIKE ?)"
            params.extend([f"%{search.strip()}%"] * 2)
        return [from_row(Material, r) for r in self.db.query(sql + " ORDER BY m.kind, m.title COLLATE NOCASE", params)]

    def get(self, material_id: int) -> Material | None:
        row = self.db.query_one("SELECT m.*, n.title AS node_title FROM sf_materials m LEFT JOIN sf_nodes n "
                                "ON n.id = m.node_id WHERE m.id = ?", (material_id,))
        return from_row(Material, row) if row else None


class MistakeRepository(Repository):
    """The shared mistake notebook (``mistakes`` table, also used by the Exams page)."""

    def categories(self) -> list[str]:
        return [r[0] for r in self.db.query("SELECT name FROM sf_mistake_categories ORDER BY builtin DESC, name")]

    def add_category(self, name: str) -> None:
        name = clean_text(name, field="Category", required=True, max_len=60)
        with self.db.transaction():
            self.db.execute("INSERT OR IGNORE INTO sf_mistake_categories (name) VALUES (?)", (name,))

    def add(self, question: str, *, node_id: int | None = None, question_id: int | None = None, user_answer: str = "",
            expected_answer: str = "", explanation: str = "", category: str = "", attempt_id: int | None = None,
            subject_id: int | None = None) -> int:
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO mistakes (subject_id, question, correction, node_id, question_id, user_answer, expected_answer, "
                "explanation, category, attempt_id, next_review, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (optional_id(subject_id), clean_text(question, field="Question", required=True, max_len=20000),
                 clean_text(explanation, field="Correction", max_len=20000), optional_id(node_id), optional_id(question_id),
                 clean_text(user_answer, field="Your answer", max_len=20000),
                 clean_text(expected_answer, field="Expected answer", max_len=20000),
                 clean_text(explanation, field="Explanation", max_len=20000),
                 clean_text(category, field="Category", max_len=60), optional_id(attempt_id),
                 iso(today() + timedelta(days=1)), now_stamp()))

    def exists_for(self, attempt_id: int, question_id: int | None) -> bool:
        return bool(self.db.scalar("SELECT 1 FROM mistakes WHERE attempt_id = ? AND question_id IS ?",
                                   (attempt_id, question_id)))

    def list(self, *, course_node_ids: set[int] | None = None, category: str = "", status: str = "open",
             search: str = "", due_only: bool = False) -> list[dict]:
        sql = ("SELECT m.*, n.title AS node_title, s.name AS subject_name FROM mistakes m "
               "LEFT JOIN sf_nodes n ON n.id = m.node_id LEFT JOIN subjects s ON s.id = m.subject_id WHERE 1")
        params: list = []
        if course_node_ids is not None:
            if not course_node_ids:
                return []
            sql += f" AND m.node_id IN ({','.join('?' for _ in course_node_ids)})"
            params.extend(course_node_ids)
        if category:
            sql += " AND m.category = ?"
            params.append(category)
        if status == "open":
            sql += " AND m.resolved = 0"
        elif status == "resolved":
            sql += " AND m.resolved = 1"
        if due_only:
            sql += " AND m.resolved = 0 AND (m.next_review IS NULL OR m.next_review <= ?)"
            params.append(iso(today()))
        if search.strip():
            sql += " AND (m.question LIKE ? OR m.explanation LIKE ? OR m.correction LIKE ?)"
            params.extend([f"%{search.strip()}%"] * 3)
        return [dict(r) for r in self.db.query(sql + " ORDER BY m.resolved, m.created_at DESC", params)]

    def update(self, mistake_id: int, *, category: str | None = None, explanation: str | None = None,
               expected_answer: str | None = None) -> None:
        data = {}
        if category is not None:
            data["category"] = clean_text(category, field="Category", max_len=60)
        if explanation is not None:
            data["explanation"] = data["correction"] = clean_text(explanation, field="Explanation", max_len=20000)
        if expected_answer is not None:
            data["expected_answer"] = clean_text(expected_answer, field="Expected answer", max_len=20000)
        if data:
            with self.db.transaction():
                self.db.execute(f"UPDATE mistakes SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                                [*data.values(), mistake_id])

    def retried(self, mistake_id: int, got_it: bool) -> None:
        """Record a retry: right answers push the next retry further out; three in a row resolves it."""
        row = self.db.query_one("SELECT reviews FROM mistakes WHERE id = ?", (mistake_id,))
        if row is None:
            return
        reviews = int(row[0] or 0)
        if got_it:
            reviews += 1
            days = {1: 3, 2: 7}.get(reviews, 14)
            resolved = 1 if reviews >= 3 else 0
        else:
            reviews, days, resolved = 0, 1, 0
        with self.db.transaction():
            self.db.execute("UPDATE mistakes SET reviews = ?, next_review = ?, resolved = ? WHERE id = ?",
                            (reviews, iso(today() + timedelta(days=days)), resolved, mistake_id))

    def category_counts(self, node_ids: set[int] | None = None) -> list[tuple[str, int]]:
        sql = "SELECT CASE WHEN category = '' THEN 'Uncategorised' ELSE category END AS c, COUNT(*) FROM mistakes"
        params: list = []
        if node_ids is not None:
            if not node_ids:
                return []
            sql += f" WHERE node_id IN ({','.join('?' for _ in node_ids)})"
            params.extend(node_ids)
        return [(r[0], int(r[1])) for r in self.db.query(sql + " GROUP BY c ORDER BY COUNT(*) DESC", params)]


class StudyForge:
    """Facade: ``ctx.services["studyforge"]``."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.courses = CourseRepository(db)
        self.bank = QuestionBank(db)
        self.tests = TestRepository(db)
        self.revision = RevisionRepository(db)
        self.materials = MaterialRepository(db)
        self.mistakes = MistakeRepository(db)
