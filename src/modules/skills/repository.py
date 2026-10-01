"""Skill roadmaps: baseline, goal, milestones, prerequisites, resources, practice tasks and
evidence of progress. There are no scores — only what you did and what you made.

Time is logged as ``learn`` (reading, watching, courses), ``practice`` (exercises,
drills) or ``build`` (real work you produced), so reviews can tell consuming from
producing without judging either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.repositories.base import Repository, clean_text
from src.repositories.notes import normalize_url
from src.services.dates import ValidationError, iso, now_stamp, today

MODES = {"learn": "Learning (reading, videos, courses)", "practice": "Practice (exercises, drills)",
         "build": "Building (real work you made)"}
ITEM_KINDS = {"milestone": "Milestones", "resource": "Learning resources", "practice": "Practice tasks"}
STATUSES = {"active": "Active", "paused": "Paused", "done": "Reached my goal"}
CATEGORY_SUGGESTIONS = ["Programming", "Mathematics", "Video editing", "Graphic design", "Writing", "Communication",
                        "Research", "Languages", "Music", "Other"]


@dataclass
class Skill:
    id: int
    name: str
    category: str = ""
    baseline: str = ""
    goal: str = ""
    status: str = "active"
    review_date: str | None = None
    notes: str = ""
    position: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SkillItem:
    id: int
    skill_id: int
    kind: str
    title: str
    url: str
    done_at: str | None
    position: int


@dataclass
class SkillLog:
    id: int
    skill_id: int
    date: str
    minutes: int | None
    mode: str
    note: str
    evidence_url: str


class SkillRepository(Repository):
    def list(self, include_done: bool = True) -> list[Skill]:
        sql = "SELECT * FROM skills" + ("" if include_done else " WHERE status != 'done'")
        return [Skill(**dict(r)) for r in self.db.query(sql + " ORDER BY status = 'done', position, name")]

    def get(self, skill_id: int) -> Skill | None:
        row = self.db.query_one("SELECT * FROM skills WHERE id = ?", (skill_id,))
        return Skill(**dict(row)) if row else None

    def save(self, skill_id: int | None, *, name: str, category: str = "", baseline: str = "", goal: str = "",
             status: str = "active", review_date: date | None = None, notes: str = "") -> int:
        name = clean_text(name, field="Skill", required=True, max_len=80)
        if status not in STATUSES:
            raise ValidationError("Unknown status.")
        if self.db.scalar("SELECT 1 FROM skills WHERE name = ? COLLATE NOCASE AND id IS NOT ?", (name, skill_id)):
            raise ValidationError(f"You already have a skill called “{name}”.")
        values = (name, clean_text(category, field="Category", max_len=40),
                  clean_text(baseline, field="Where you are now", max_len=2000),
                  clean_text(goal, field="Desired outcome", max_len=2000), status,
                  iso(review_date) if review_date else None, clean_text(notes, field="Notes", max_len=20000))
        stamp = now_stamp()
        with self.db.transaction():
            if skill_id is None:
                pos = int(self.db.scalar("SELECT COALESCE(MAX(position), 0) + 1 FROM skills", default=1))
                return self.db.insert(
                    "INSERT INTO skills (name, category, baseline, goal, status, review_date, notes, position, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (*values, pos, stamp, stamp))
            self.db.execute("UPDATE skills SET name = ?, category = ?, baseline = ?, goal = ?, status = ?, "
                            "review_date = ?, notes = ?, updated_at = ? WHERE id = ?", (*values, stamp, skill_id))
            return skill_id

    def delete(self, skill_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))

    # prerequisites
    def prerequisites(self, skill_id: int) -> list[Skill]:
        return [Skill(**dict(r)) for r in self.db.query(
            "SELECT s.* FROM skill_prereqs p JOIN skills s ON s.id = p.requires_id WHERE p.skill_id = ? "
            "ORDER BY s.name", (skill_id,))]

    def add_prerequisite(self, skill_id: int, requires_id: int) -> None:
        if skill_id == requires_id:
            raise ValidationError("A skill can't depend on itself.")
        # refuse cycles: requires_id must not (indirectly) depend on skill_id
        stack, seen = [requires_id], set()
        while stack:
            current = stack.pop()
            if current == skill_id:
                raise ValidationError("That would make the two skills depend on each other.")
            if current in seen:
                continue
            seen.add(current)
            stack.extend(int(r[0]) for r in self.db.query(
                "SELECT requires_id FROM skill_prereqs WHERE skill_id = ?", (current,)))
        with self.db.transaction():
            self.db.execute("INSERT OR IGNORE INTO skill_prereqs (skill_id, requires_id) VALUES (?, ?)",
                            (skill_id, requires_id))

    def remove_prerequisite(self, skill_id: int, requires_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM skill_prereqs WHERE skill_id = ? AND requires_id = ?", (skill_id, requires_id))

    # roadmap items
    def items(self, skill_id: int, kind: str | None = None) -> list[SkillItem]:
        sql = "SELECT id, skill_id, kind, title, url, done_at, position FROM skill_items WHERE skill_id = ?"
        params: tuple = (skill_id,)
        if kind:
            sql += " AND kind = ?"
            params += (kind,)
        return [SkillItem(**dict(r)) for r in self.db.query(sql + " ORDER BY kind, position, id", params)]

    def add_item(self, skill_id: int, kind: str, title: str, url: str = "") -> int:
        if kind not in ITEM_KINDS:
            raise ValidationError("Unknown item type.")
        title = clean_text(title, field="Title", required=True, max_len=200)
        pos = int(self.db.scalar("SELECT COALESCE(MAX(position), 0) + 1 FROM skill_items WHERE skill_id = ?",
                                 (skill_id,), default=1))
        with self.db.transaction():
            return self.db.insert("INSERT INTO skill_items (skill_id, kind, title, url, position, created_at) "
                                  "VALUES (?, ?, ?, ?, ?, ?)", (skill_id, kind, title, normalize_url(url), pos,
                                                                now_stamp()))

    def set_item_done(self, item_id: int, done: bool) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE skill_items SET done_at = ? WHERE id = ?", (now_stamp() if done else None, item_id))

    def delete_item(self, item_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM skill_items WHERE id = ?", (item_id,))

    # activity and evidence
    def log(self, skill_id: int, mode: str, minutes: int | None = None, note: str = "", evidence_url: str = "",
            day: date | None = None) -> int:
        if mode not in MODES:
            raise ValidationError("Choose learning, practice or building.")
        if minutes is not None and (minutes <= 0 or minutes > 24 * 60):
            raise ValidationError("Minutes must be between 1 and 1440.")
        if minutes is None and not note.strip() and not evidence_url.strip():
            raise ValidationError("Add the time spent, a note or a link to what you made.")
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO skill_logs (skill_id, date, minutes, mode, note, evidence_url, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (skill_id, iso(day or today()), minutes, mode,
                                                 clean_text(note, field="Note", max_len=2000),
                                                 normalize_url(evidence_url), now_stamp()))

    def logs(self, skill_id: int | None = None, start: date | None = None, end: date | None = None,
             limit: int = 500) -> list[SkillLog]:
        where, params = [], []
        if skill_id is not None:
            where.append("skill_id = ?")
            params.append(skill_id)
        if start:
            where.append("date >= ?")
            params.append(iso(start))
        if end:
            where.append("date <= ?")
            params.append(iso(end))
        sql = "SELECT id, skill_id, date, minutes, mode, note, evidence_url FROM skill_logs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return [SkillLog(**dict(r)) for r in self.db.query(sql + " ORDER BY date DESC, id DESC LIMIT ?",
                                                           (*params, limit))]

    def delete_log(self, log_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM skill_logs WHERE id = ?", (log_id,))

    def week_summary(self, week_start: date) -> dict:
        """Activity in one week: minutes by mode, evidence entries and milestones reached, per skill."""
        end = week_start + timedelta(days=6)
        per_skill: dict[int, dict] = {}
        for log in self.logs(start=week_start, end=end, limit=10000):
            s = per_skill.setdefault(log.skill_id, {"learn": 0, "practice": 0, "build": 0, "evidence": 0,
                                                    "milestones": 0})
            s[log.mode] += log.minutes or 0
            if log.evidence_url or (log.mode == "build" and log.note):
                s["evidence"] += 1
        for row in self.db.query("SELECT skill_id, COUNT(*) FROM skill_items WHERE kind = 'milestone' AND done_at "
                                 "BETWEEN ? AND ? GROUP BY skill_id", (iso(week_start), iso(end) + " 23:59:59")):
            per_skill.setdefault(int(row[0]), {"learn": 0, "practice": 0, "build": 0, "evidence": 0,
                                               "milestones": 0})["milestones"] = int(row[1])
        totals = {k: sum(s[k] for s in per_skill.values()) for k in ("learn", "practice", "build", "evidence",
                                                                     "milestones")}
        return {"per_skill": per_skill, "totals": totals}

    def due_reviews(self, day: date | None = None) -> list[Skill]:
        day = day or today()
        return [s for s in self.list(include_done=False) if s.review_date and s.review_date <= iso(day)]
