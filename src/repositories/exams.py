from __future__ import annotations

from datetime import date
from typing import Any

from src.models import CHAPTER_STATUSES, Chapter, Exam, Mistake, MockTest, RevisionLog, from_row
from src.repositories.base import Repository, clean_text, optional_id
from src.services import revision
from src.services.dates import ValidationError, iso, now_stamp, parse_date, parse_time, time_str, today

_EXAM_SELECT = """
SELECT x.*, s.name AS subject_name,
       (SELECT COUNT(*) FROM chapters c WHERE c.exam_id = x.id) AS chapter_total,
       (SELECT COUNT(*) FROM chapters c WHERE c.exam_id = x.id AND c.status IN ('revised', 'mastered')) AS chapter_ready
FROM exams x LEFT JOIN subjects s ON s.id = x.subject_id
"""

_CHAPTER_SELECT = """
SELECT c.*, x.title AS exam_title, x.exam_date AS exam_date, s.name AS subject_name
FROM chapters c JOIN exams x ON x.id = c.exam_id LEFT JOIN subjects s ON s.id = x.subject_id
"""


class ExamRepository(Repository):
    # -- exams ----------------------------------------------------------------
    def _clean_exam(self, data: dict[str, Any]) -> dict[str, Any]:
        exam_date = parse_date(data.get("exam_date"), field="Exam date", required=True)
        return {
            "title": clean_text(data.get("title"), field="Exam title", required=True, max_len=150),
            "subject_id": optional_id(data.get("subject_id")),
            "exam_date": iso(exam_date),  # type: ignore[arg-type]
            "exam_time": time_str(parse_time(data.get("exam_time"), field="Exam time")),
            "syllabus": clean_text(data.get("syllabus", ""), field="Syllabus", max_len=5000),
            "notes": clean_text(data.get("notes", ""), field="Notes", max_len=5000),
        }

    def create_exam(self, **data: Any) -> int:
        clean = self._clean_exam(data)
        clean["created_at"] = now_stamp()
        cols = ", ".join(clean)
        marks = ", ".join("?" for _ in clean)
        with self.db.transaction():
            return self.db.insert(f"INSERT INTO exams ({cols}) VALUES ({marks})", list(clean.values()))

    def update_exam(self, exam_id: int, **data: Any) -> None:
        clean = self._clean_exam(data)
        assignments = ", ".join(f"{k} = ?" for k in clean)
        with self.db.transaction():
            self.db.execute(f"UPDATE exams SET {assignments} WHERE id = ?", [*clean.values(), exam_id])

    def delete_exam(self, exam_id: int) -> None:
        """Deletes the exam with its chapters and their revision logs.

        Mistakes linked to those chapters are kept (their chapter is cleared);
        mock tests linked to the exam are kept (their exam is cleared).
        """
        with self.db.transaction():
            self.db.execute("DELETE FROM exams WHERE id = ?", (exam_id,))

    def get_exam(self, exam_id: int) -> Exam | None:
        row = self.db.query_one(_EXAM_SELECT + " WHERE x.id = ?", (exam_id,))
        return from_row(Exam, row) if row else None

    def exams(self, include_past: bool = True) -> list[Exam]:
        sql = _EXAM_SELECT
        params: list = []
        if not include_past:
            sql += " WHERE x.exam_date >= ?"
            params.append(iso(today()))
        sql += " ORDER BY x.exam_date < ?, CASE WHEN x.exam_date >= ? THEN x.exam_date END, x.exam_date DESC"
        params.extend([iso(today()), iso(today())])
        return [from_row(Exam, r) for r in self.db.query(sql, params)]

    def upcoming(self, start: date, end: date) -> list[Exam]:
        rows = self.db.query(_EXAM_SELECT + " WHERE x.exam_date BETWEEN ? AND ? ORDER BY x.exam_date, x.exam_time",
                             (iso(start), iso(end)))
        return [from_row(Exam, r) for r in rows]

    # -- chapters -------------------------------------------------------------
    def add_chapter(self, exam_id: int, name: str) -> int:
        name = clean_text(name, field="Chapter name", required=True, max_len=150)
        position = int(self.db.scalar("SELECT COALESCE(MAX(position), -1) + 1 FROM chapters WHERE exam_id = ?", (exam_id,), 0))
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO chapters (exam_id, name, position, created_at) VALUES (?, ?, ?, ?)",
                (exam_id, name, position, now_stamp()),
            )

    def add_chapters(self, exam_id: int, names: list[str]) -> int:
        added = 0
        with self.db.transaction():
            for name in names:
                if name.strip():
                    self.add_chapter(exam_id, name)
                    added += 1
        return added

    def rename_chapter(self, chapter_id: int, name: str) -> None:
        name = clean_text(name, field="Chapter name", required=True, max_len=150)
        with self.db.transaction():
            self.db.execute("UPDATE chapters SET name = ? WHERE id = ?", (name, chapter_id))

    def set_chapter_status(self, chapter_id: int, status: str) -> None:
        if status not in CHAPTER_STATUSES:
            raise ValidationError("Unknown chapter status.")
        with self.db.transaction():
            self.db.execute("UPDATE chapters SET status = ? WHERE id = ?", (status, chapter_id))

    def set_next_review(self, chapter_id: int, day: date | None) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE chapters SET next_review = ? WHERE id = ?", (iso(day) if day else None, chapter_id))

    def delete_chapter(self, chapter_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM chapters WHERE id = ?", (chapter_id,))

    def get_chapter(self, chapter_id: int) -> Chapter | None:
        row = self.db.query_one(_CHAPTER_SELECT + " WHERE c.id = ?", (chapter_id,))
        return from_row(Chapter, row) if row else None

    def chapters(self, exam_id: int) -> list[Chapter]:
        rows = self.db.query(_CHAPTER_SELECT + " WHERE c.exam_id = ? ORDER BY c.position, c.id", (exam_id,))
        return [from_row(Chapter, r) for r in rows]

    def all_chapters(self) -> list[Chapter]:
        rows = self.db.query(_CHAPTER_SELECT + " ORDER BY x.exam_date DESC, c.position")
        return [from_row(Chapter, r) for r in rows]

    # -- revision -------------------------------------------------------------
    def log_revision(self, chapter_id: int, outcome: str, note: str = "", day: date | None = None) -> revision.ReviewResult:
        chapter = self.get_chapter(chapter_id)
        if chapter is None:
            raise ValidationError("This chapter no longer exists.")
        day = day or today()
        if day > today():
            raise ValidationError("Revision can't be logged for a future date.")
        exam_day = date.fromisoformat(chapter.exam_date) if chapter.exam_date else None
        result = revision.schedule_next(outcome, chapter.interval_days, day, exam_day)
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO revision_logs (chapter_id, date, outcome, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (chapter_id, iso(day), outcome, clean_text(note, field="Note", max_len=500), now_stamp()),
            )
            self.db.execute(
                """UPDATE chapters SET status = ?, last_reviewed = ?, next_review = ?, interval_days = ?,
                   review_count = review_count + 1 WHERE id = ?""",
                (result.status, iso(day), iso(result.next_review), result.interval_days, chapter_id),
            )
        return result

    def revision_logs(self, chapter_id: int) -> list[RevisionLog]:
        rows = self.db.query("SELECT * FROM revision_logs WHERE chapter_id = ? ORDER BY date DESC, id DESC", (chapter_id,))
        return [from_row(RevisionLog, r) for r in rows]

    def revision_queue(self, ref: date | None = None, limit: int = 50) -> list[Chapter]:
        ref = ref or today()
        rows = self.db.query(
            _CHAPTER_SELECT
            + """ WHERE (c.next_review IS NOT NULL AND c.next_review <= ? AND c.status != 'mastered')
                   OR (c.next_review IS NULL AND c.status IN ('learning', 'needs_revision') AND x.exam_date >= ?)""",
            (iso(ref), iso(ref)),
        )
        chapters = [from_row(Chapter, r) for r in rows]
        chapters.sort(
            key=lambda c: revision.queue_sort_key(
                date.fromisoformat(c.next_review) if c.next_review else None,
                date.fromisoformat(c.exam_date) if c.exam_date else None,
                c.status,
                ref,
            )
        )
        return chapters[:limit]

    def revisions_between(self, start: date, end: date) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM revision_logs WHERE date BETWEEN ? AND ?", (iso(start), iso(end)), 0))

    # -- mistakes -------------------------------------------------------------
    def add_mistake(self, question: str, correction: str = "", subject_id: Any = None, chapter_id: Any = None) -> int:
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO mistakes (subject_id, chapter_id, question, correction, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    optional_id(subject_id),
                    optional_id(chapter_id),
                    clean_text(question, field="Mistake", required=True, max_len=3000),
                    clean_text(correction, field="Correction", max_len=3000),
                    now_stamp(),
                ),
            )

    def update_mistake(self, mistake_id: int, question: str, correction: str, subject_id: Any, chapter_id: Any) -> None:
        with self.db.transaction():
            self.db.execute(
                "UPDATE mistakes SET question = ?, correction = ?, subject_id = ?, chapter_id = ? WHERE id = ?",
                (
                    clean_text(question, field="Mistake", required=True, max_len=3000),
                    clean_text(correction, field="Correction", max_len=3000),
                    optional_id(subject_id),
                    optional_id(chapter_id),
                    mistake_id,
                ),
            )

    def set_mistake_resolved(self, mistake_id: int, resolved: bool) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE mistakes SET resolved = ? WHERE id = ?", (int(resolved), mistake_id))

    def delete_mistake(self, mistake_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM mistakes WHERE id = ?", (mistake_id,))

    def mistakes(self, subject_id: int | None = None, include_resolved: bool = True, search: str = "") -> list[Mistake]:
        sql = """SELECT m.*, s.name AS subject_name, c.name AS chapter_name FROM mistakes m
                 LEFT JOIN subjects s ON s.id = m.subject_id LEFT JOIN chapters c ON c.id = m.chapter_id"""
        where, params = [], []
        if subject_id:
            where.append("m.subject_id = ?")
            params.append(subject_id)
        if not include_resolved:
            where.append("m.resolved = 0")
        if search.strip():
            where.append("(m.question LIKE ? OR m.correction LIKE ?)")
            params.extend([f"%{search.strip()}%"] * 2)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.resolved, m.created_at DESC LIMIT 500"
        return [from_row(Mistake, r) for r in self.db.query(sql, params)]

    # -- mock tests -----------------------------------------------------------
    def _clean_test(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            marks = float(data.get("marks"))
            max_marks = float(data.get("max_marks"))
        except (TypeError, ValueError):
            raise ValidationError("Marks must be numbers.") from None
        if max_marks <= 0:
            raise ValidationError("Maximum marks must be greater than zero.")
        if marks < 0:
            raise ValidationError("Marks obtained can't be negative.")
        if marks > max_marks:
            raise ValidationError("Marks obtained can't be more than the maximum marks.")
        day = parse_date(data.get("date"), field="Test date", required=True)
        if day > today():  # type: ignore[operator]
            raise ValidationError("A test result can't be dated in the future.")
        return {
            "title": clean_text(data.get("title"), field="Test name", required=True, max_len=150),
            "subject_id": optional_id(data.get("subject_id")),
            "exam_id": optional_id(data.get("exam_id")),
            "date": iso(day),  # type: ignore[arg-type]
            "marks": marks,
            "max_marks": max_marks,
            "notes": clean_text(data.get("notes", ""), field="Notes", max_len=2000),
        }

    def add_test(self, **data: Any) -> int:
        clean = self._clean_test(data)
        clean["created_at"] = now_stamp()
        cols = ", ".join(clean)
        marks = ", ".join("?" for _ in clean)
        with self.db.transaction():
            return self.db.insert(f"INSERT INTO mock_tests ({cols}) VALUES ({marks})", list(clean.values()))

    def update_test(self, test_id: int, **data: Any) -> None:
        clean = self._clean_test(data)
        assignments = ", ".join(f"{k} = ?" for k in clean)
        with self.db.transaction():
            self.db.execute(f"UPDATE mock_tests SET {assignments} WHERE id = ?", [*clean.values(), test_id])

    def delete_test(self, test_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM mock_tests WHERE id = ?", (test_id,))

    def tests(self, start: date | None = None, end: date | None = None, subject_id: int | None = None) -> list[MockTest]:
        sql = "SELECT m.*, s.name AS subject_name FROM mock_tests m LEFT JOIN subjects s ON s.id = m.subject_id"
        where, params = [], []
        if start:
            where.append("m.date >= ?")
            params.append(iso(start))
        if end:
            where.append("m.date <= ?")
            params.append(iso(end))
        if subject_id:
            where.append("m.subject_id = ?")
            params.append(subject_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.date DESC, m.id DESC LIMIT 500"
        return [from_row(MockTest, r) for r in self.db.query(sql, params)]
