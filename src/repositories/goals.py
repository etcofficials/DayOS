from __future__ import annotations

from datetime import date
from typing import Any

from src.models import Milestone, WeeklyReview, GOAL_STATUSES, Goal, GoalProgress, JournalEntry, from_row
from src.repositories.base import Repository, clean_text
from src.services.dates import ValidationError, iso, now_stamp, parse_date, today

_SELECT = """
SELECT g.*,
       (SELECT COUNT(*) FROM tasks t WHERE t.goal_id = g.id) AS linked_tasks,
       (SELECT COUNT(*) FROM tasks t WHERE t.goal_id = g.id AND t.completed_at IS NOT NULL) AS linked_done
FROM goals g
"""


def _number(value: Any, field: str, *, allow_none: bool = True, positive: bool = False) -> float | None:
    if value is None or str(value).strip() == "":
        if allow_none:
            return None
        raise ValidationError(f"{field} is required.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a number.") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise ValidationError(f"{field} must be a finite number.")
    if positive and number <= 0:
        raise ValidationError(f"{field} must be greater than zero.")
    if number < 0:
        raise ValidationError(f"{field} can't be negative.")
    return number


class GoalRepository(Repository):
    def _clean(self, data: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "title" in data:
            out["title"] = clean_text(data["title"], field="Goal title", required=True, max_len=150)
        if "description" in data:
            out["description"] = clean_text(data["description"], field="Description", max_len=2000)
        if "category" in data:
            out["category"] = clean_text(data["category"], field="Category", max_len=60)
        if "target_date" in data:
            d = parse_date(data["target_date"], field="Target date")
            out["target_date"] = iso(d) if d else None
        if "target_value" in data:
            out["target_value"] = _number(data["target_value"], "Target", positive=True)
        if "unit" in data:
            out["unit"] = clean_text(data["unit"], field="Unit", max_len=30)
        return out

    def create(self, title: str, **fields: Any) -> int:
        data = self._clean({"title": title, **fields})
        data["created_at"] = now_stamp()
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self.db.transaction():
            return self.db.insert(f"INSERT INTO goals ({cols}) VALUES ({marks})", list(data.values()))

    def update(self, goal_id: int, **fields: Any) -> None:
        data = self._clean(fields)
        if not data:
            return
        assignments = ", ".join(f"{k} = ?" for k in data)
        with self.db.transaction():
            self.db.execute(f"UPDATE goals SET {assignments} WHERE id = ?", [*data.values(), goal_id])

    def set_status(self, goal_id: int, status: str) -> None:
        if status not in GOAL_STATUSES:
            raise ValidationError("Unknown goal status.")
        completed_at = now_stamp() if status == "completed" else None
        with self.db.transaction():
            self.db.execute(
                "UPDATE goals SET status = ?, completed_at = ? WHERE id = ?", (status, completed_at, goal_id)
            )

    def delete(self, goal_id: int) -> None:
        """Delete a goal and its progress history. Linked tasks are kept (unlinked)."""
        with self.db.transaction():
            self.db.execute("DELETE FROM goals WHERE id = ?", (goal_id,))

    def get(self, goal_id: int) -> Goal | None:
        row = self.db.query_one(_SELECT + " WHERE g.id = ?", (goal_id,))
        return from_row(Goal, row) if row else None

    def list(self, status: str | None = None) -> list[Goal]:
        sql = _SELECT
        params: list = []
        if status:
            sql += " WHERE g.status = ?"
            params.append(status)
        sql += (
            " ORDER BY CASE g.status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,"
            " g.target_date IS NULL, g.target_date, g.id"
        )
        return [from_row(Goal, r) for r in self.db.query(sql, params)]

    # -- progress -------------------------------------------------------------
    def log_progress(self, goal_id: int, value: Any, note: str = "", day: date | None = None) -> None:
        """Record a new current value. Every update is kept as history."""
        number = _number(value, "Progress", allow_none=False)
        note = clean_text(note, field="Note", max_len=500)
        day = day or today()
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO goal_progress (goal_id, date, value, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (goal_id, iso(day), number, note, now_stamp()),
            )
            self.db.execute("UPDATE goals SET current_value = ? WHERE id = ?", (number, goal_id))

    def history(self, goal_id: int, limit: int = 200) -> list[GoalProgress]:
        rows = self.db.query(
            "SELECT * FROM goal_progress WHERE goal_id = ? ORDER BY date DESC, id DESC LIMIT ?", (goal_id, limit)
        )
        return [from_row(GoalProgress, r) for r in rows]

    def categories(self) -> list[str]:
        rows = self.db.query("SELECT DISTINCT category FROM goals WHERE category != '' ORDER BY category")
        return [r[0] for r in rows]


class JournalRepository(Repository):
    def get(self, day: date) -> JournalEntry:
        row = self.db.query_one("SELECT * FROM journal WHERE date = ?", (iso(day),))
        return from_row(JournalEntry, row) if row else JournalEntry(date=iso(day))

    def save(self, day: date, **fields: str) -> None:
        allowed = {"intention": 300, "reflection": 5000, "went_well": 2000, "improve": 2000}
        data = {k: clean_text(v, field=k.replace("_", " ").title(), max_len=allowed[k]) for k, v in fields.items() if k in allowed}
        if not data:
            return
        current = self.get(day)
        merged = {k: data.get(k, getattr(current, k)) for k in allowed}
        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO journal (date, intention, reflection, went_well, improve, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET intention = excluded.intention,
                    reflection = excluded.reflection, went_well = excluded.went_well,
                    improve = excluded.improve, updated_at = excluded.updated_at
                """,
                (iso(day), merged["intention"], merged["reflection"], merged["went_well"], merged["improve"],
                 now_stamp()),
            )

    def recent(self, limit: int = 30) -> list[JournalEntry]:
        rows = self.db.query(
            "SELECT * FROM journal WHERE intention != '' OR reflection != '' OR went_well != '' OR improve != '' "
            "ORDER BY date DESC LIMIT ?",
            (limit,),
        )
        return [from_row(JournalEntry, r) for r in rows]


class MilestoneRepository(Repository):
    """Milestones for goals (``goal_milestones``) and projects (``project_milestones``)."""

    TABLES = {"goal": ("goal_milestones", "goal_id", "target_date"),
              "project": ("project_milestones", "project_id", "due_date")}

    def _t(self, owner: str) -> tuple[str, str, str]:
        if owner not in self.TABLES:
            raise ValueError(owner)
        return self.TABLES[owner]

    def list(self, owner: str, owner_id: int) -> list[Milestone]:
        table, fk, _ = self._t(owner)
        rows = self.db.query(f"SELECT * FROM {table} WHERE {fk} = ? ORDER BY position, id", (owner_id,))
        return [from_row(Milestone, r) for r in rows]

    def add(self, owner: str, owner_id: int, title: str, when: date | None = None) -> int:
        table, fk, date_col = self._t(owner)
        title = clean_text(title, field="Milestone", required=True, max_len=200)
        position = int(self.db.scalar(f"SELECT COALESCE(MAX(position), -1) + 1 FROM {table} WHERE {fk} = ?",
                                      (owner_id,), 0))
        with self.db.transaction():
            return self.db.insert(
                f"INSERT INTO {table} ({fk}, title, {date_col}, position, created_at) VALUES (?, ?, ?, ?, ?)",
                (owner_id, title, iso(when) if when else None, position, now_stamp()))

    def update(self, owner: str, milestone_id: int, title: str, when: date | None) -> None:
        table, _, date_col = self._t(owner)
        title = clean_text(title, field="Milestone", required=True, max_len=200)
        with self.db.transaction():
            self.db.execute(f"UPDATE {table} SET title = ?, {date_col} = ? WHERE id = ?",
                            (title, iso(when) if when else None, milestone_id))

    def set_done(self, owner: str, milestone_id: int, done: bool) -> None:
        table, _, _ = self._t(owner)
        with self.db.transaction():
            self.db.execute(f"UPDATE {table} SET done_at = ? WHERE id = ?", (now_stamp() if done else None, milestone_id))

    def delete(self, owner: str, milestone_id: int) -> None:
        table, _, _ = self._t(owner)
        with self.db.transaction():
            self.db.execute(f"DELETE FROM {table} WHERE id = ?", (milestone_id,))

    def counts(self, owner: str, owner_id: int) -> tuple[int, int]:
        table, fk, _ = self._t(owner)
        row = self.db.query_one(f"SELECT COUNT(*), SUM(done_at IS NOT NULL) FROM {table} WHERE {fk} = ?", (owner_id,))
        return int(row[0] or 0), int(row[1] or 0)


class WeeklyReviewRepository(Repository):
    FIELDS = {"wins": 3000, "challenges": 3000, "priorities": 3000, "notes": 5000}

    def get(self, week_start: date) -> WeeklyReview:
        row = self.db.query_one("SELECT * FROM weekly_reviews WHERE week_start = ?", (iso(week_start),))
        return from_row(WeeklyReview, row) if row else WeeklyReview(week_start=iso(week_start))

    def save(self, week_start: date, **fields: str) -> None:
        data = {k: clean_text(v, field=k.title(), max_len=self.FIELDS[k]) for k, v in fields.items() if k in self.FIELDS}
        current = self.get(week_start)
        merged = {k: data.get(k, getattr(current, k)) for k in self.FIELDS}
        with self.db.transaction():
            self.db.execute(
                """INSERT INTO weekly_reviews (week_start, wins, challenges, priorities, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(week_start) DO UPDATE SET wins = excluded.wins, challenges = excluded.challenges,
                     priorities = excluded.priorities, notes = excluded.notes, updated_at = excluded.updated_at""",
                (iso(week_start), merged["wins"], merged["challenges"], merged["priorities"], merged["notes"],
                 now_stamp()))

    def recent(self, limit: int = 20) -> list[WeeklyReview]:
        rows = self.db.query("SELECT * FROM weekly_reviews ORDER BY week_start DESC LIMIT ?", (limit,))
        return [from_row(WeeklyReview, r) for r in rows]
