from __future__ import annotations

from datetime import date
from typing import Any

from src.models import Subtask, Task, TaskSnapshot, from_row
from src.repositories.base import Repository, clean_text, optional_id, positive_int
from src.services.dates import ValidationError, iso, now_stamp, parse_date, parse_time, time_str, today

FILTERS = ["today", "upcoming", "overdue", "nodate", "completed", "all"]
SORTS = ["due", "priority", "created", "title"]

_SELECT = """
SELECT t.*, s.name AS subject_name, g.title AS goal_title,
       (SELECT COUNT(*) FROM subtasks st WHERE st.task_id = t.id) AS subtask_total,
       (SELECT COUNT(*) FROM subtasks st WHERE st.task_id = t.id AND st.done = 1) AS subtask_done
FROM tasks t
LEFT JOIN subjects s ON s.id = t.subject_id
LEFT JOIN goals g ON g.id = t.goal_id
"""

_ORDER = {
    "due": "t.due_date IS NULL, t.due_date, t.due_time IS NULL, t.due_time, t.priority DESC, t.id",
    "priority": "t.priority DESC, t.due_date IS NULL, t.due_date, t.id",
    "created": "t.created_at DESC, t.id DESC",
    "title": "t.title COLLATE NOCASE, t.id",
}


class TaskRepository(Repository):
    # -- validation -------------------------------------------------------
    def _clean(self, data: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "title" in data:
            out["title"] = clean_text(data["title"], field="Task title", required=True, max_len=200)
        if "description" in data:
            out["description"] = clean_text(data["description"], field="Description", max_len=5000)
        if "due_date" in data:
            d = parse_date(data["due_date"], field="Due date")
            out["due_date"] = iso(d) if d else None
        if "due_time" in data:
            out["due_time"] = time_str(parse_time(data["due_time"], field="Due time"))
        if "priority" in data:
            priority = int(data["priority"])
            if priority not in (0, 1, 2):
                raise ValidationError("Priority must be low, normal or high.")
            out["priority"] = priority
        if "category" in data:
            out["category"] = clean_text(data["category"], field="Category", max_len=60)
        if "subject_id" in data:
            out["subject_id"] = optional_id(data["subject_id"])
        if "goal_id" in data:
            out["goal_id"] = optional_id(data["goal_id"])
        if "estimate_minutes" in data:
            out["estimate_minutes"] = positive_int(data["estimate_minutes"], field="Estimated duration")
        return out

    # -- CRUD ---------------------------------------------------------------
    def create(self, title: str, **fields: Any) -> int:
        data = self._clean({"title": title, **fields})
        if data.get("due_time") and not data.get("due_date"):
            raise ValidationError("Choose a due date before setting a due time.")
        data["created_at"] = now_stamp()
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self.db.transaction():
            return self.db.insert(f"INSERT INTO tasks ({cols}) VALUES ({marks})", list(data.values()))

    def update(self, task_id: int, **fields: Any) -> None:
        data = self._clean(fields)
        if not data:
            return
        current = self.get(task_id)
        if current is None:
            raise ValidationError("This task no longer exists.")
        due_date = data.get("due_date", current.due_date)
        due_time = data.get("due_time", current.due_time)
        if due_time and not due_date:
            raise ValidationError("Choose a due date before setting a due time.")
        assignments = ", ".join(f"{k} = ?" for k in data)
        with self.db.transaction():
            self.db.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", [*data.values(), task_id])

    def get(self, task_id: int) -> Task | None:
        row = self.db.query_one(_SELECT + " WHERE t.id = ?", (task_id,))
        return from_row(Task, row) if row else None

    def set_completed(self, task_id: int, completed: bool) -> None:
        with self.db.transaction():
            if completed:
                self.db.execute(
                    "UPDATE tasks SET completed_at = ? WHERE id = ? AND completed_at IS NULL",
                    (now_stamp(), task_id),
                )
            else:
                self.db.execute("UPDATE tasks SET completed_at = NULL WHERE id = ?", (task_id,))

    def delete(self, task_id: int) -> TaskSnapshot | None:
        """Delete a task and its own subtasks. Returns a snapshot for undo."""
        row = self.db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            return None
        subs = self.db.query("SELECT * FROM subtasks WHERE task_id = ? ORDER BY position", (task_id,))
        snapshot = TaskSnapshot(task=dict(row), subtasks=[dict(s) for s in subs])
        with self.db.transaction():
            self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return snapshot

    def restore(self, snapshot: TaskSnapshot) -> int:
        """Undo a deletion, keeping the original id when it is still free."""
        task = dict(snapshot.task)
        for key in ("subject_id", "goal_id"):
            table = "subjects" if key == "subject_id" else "goals"
            if task.get(key) and not self.db.scalar(f"SELECT 1 FROM {table} WHERE id = ?", (task[key],)):
                task[key] = None
        if self.db.scalar("SELECT 1 FROM tasks WHERE id = ?", (task["id"],)):
            task.pop("id")
        cols = ", ".join(task)
        marks = ", ".join("?" for _ in task)
        with self.db.transaction():
            new_id = self.db.insert(f"INSERT INTO tasks ({cols}) VALUES ({marks})", list(task.values()))
            for sub in snapshot.subtasks:
                self.db.execute(
                    "INSERT INTO subtasks (task_id, title, done, position) VALUES (?, ?, ?, ?)",
                    (new_id, sub["title"], sub["done"], sub["position"]),
                )
        return new_id

    # -- queries ------------------------------------------------------------
    def list(
        self,
        filter_name: str = "all",
        search: str = "",
        sort: str = "due",
        ref: date | None = None,
        limit: int = 500,
    ) -> list[Task]:
        ref_iso = iso(ref or today())
        where: list[str] = []
        params: list[Any] = []
        if filter_name == "today":
            where.append("t.due_date = ?")
            params.append(ref_iso)
        elif filter_name == "upcoming":
            where.append("t.completed_at IS NULL AND t.due_date > ?")
            params.append(ref_iso)
        elif filter_name == "overdue":
            where.append("t.completed_at IS NULL AND t.due_date < ?")
            params.append(ref_iso)
        elif filter_name == "nodate":
            where.append("t.completed_at IS NULL AND t.due_date IS NULL")
        elif filter_name == "completed":
            where.append("t.completed_at IS NOT NULL")
        if search.strip():
            like = f"%{search.strip()}%"
            where.append(
                "(t.title LIKE ? OR t.description LIKE ? OR t.category LIKE ? OR IFNULL(s.name,'') LIKE ?)"
            )
            params.extend([like] * 4)
        sql = _SELECT
        if where:
            sql += " WHERE " + " AND ".join(where)
        order = _ORDER.get(sort, _ORDER["due"])
        if filter_name == "completed" and sort == "due":
            order = "t.completed_at DESC, t.id DESC"
        elif filter_name in ("today", "all"):
            order = "t.completed_at IS NOT NULL, " + order
        sql += f" ORDER BY {order} LIMIT ?"
        params.append(int(limit))
        return [from_row(Task, r) for r in self.db.query(sql, params)]

    def counts(self, ref: date | None = None) -> dict[str, int]:
        ref_iso = iso(ref or today())
        row = self.db.query_one(
            """
            SELECT
              SUM(due_date = ?) AS today,
              SUM(completed_at IS NULL AND due_date > ?) AS upcoming,
              SUM(completed_at IS NULL AND due_date < ?) AS overdue,
              SUM(completed_at IS NULL AND due_date IS NULL) AS nodate,
              SUM(completed_at IS NOT NULL) AS completed,
              COUNT(*) AS total
            FROM tasks
            """,
            (ref_iso, ref_iso, ref_iso),
        )
        return {k: int(row[k] or 0) for k in row.keys()} if row else {}

    def for_day(self, day: date) -> tuple[list[Task], list[Task]]:
        """(overdue open tasks, tasks due that day including completed ones)."""
        overdue = self.list("overdue", ref=day, sort="due", limit=100)
        due = self.list("today", ref=day, sort="due", limit=200)
        return overdue, due

    def completed_on(self, day: date) -> int:
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM tasks WHERE substr(completed_at, 1, 10) = ?", (iso(day),), 0
            )
        )

    def categories(self) -> list[str]:
        rows = self.db.query(
            "SELECT DISTINCT category FROM tasks WHERE category != '' ORDER BY category COLLATE NOCASE"
        )
        return [r[0] for r in rows]

    def for_goal(self, goal_id: int) -> list[Task]:
        return [
            from_row(Task, r)
            for r in self.db.query(_SELECT + " WHERE t.goal_id = ? ORDER BY t.completed_at IS NOT NULL, t.due_date", (goal_id,))
        ]

    # -- subtasks -----------------------------------------------------------
    def subtasks(self, task_id: int) -> list[Subtask]:
        rows = self.db.query("SELECT * FROM subtasks WHERE task_id = ? ORDER BY position, id", (task_id,))
        return [from_row(Subtask, r) for r in rows]

    def replace_subtasks(self, task_id: int, items: list[tuple[str, bool]]) -> None:
        cleaned = [
            (clean_text(title, field="Checklist item", required=True, max_len=200), bool(done))
            for title, done in items
            if str(title).strip()
        ]
        with self.db.transaction():
            self.db.execute("DELETE FROM subtasks WHERE task_id = ?", (task_id,))
            self.db.executemany(
                "INSERT INTO subtasks (task_id, title, done, position) VALUES (?, ?, ?, ?)",
                [(task_id, title, int(done), i) for i, (title, done) in enumerate(cleaned)],
            )

    def set_subtask_done(self, subtask_id: int, done: bool) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE subtasks SET done = ? WHERE id = ?", (int(done), subtask_id))
