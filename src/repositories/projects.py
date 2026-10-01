"""Projects: descriptions, status, milestones (see MilestoneRepository), linked tasks, logs."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.models import Project, ProjectLog, from_row
from src.repositories.base import Repository, clean_text, optional_id
from src.services.dates import ValidationError, iso, now_stamp, parse_date, today

STATUSES = {"idea": "Idea", "active": "Active", "paused": "Paused", "done": "Done", "archived": "Archived"}
LOG_KINDS = {"note": "Note", "changelog": "Changelog", "release": "Release", "time": "Time logged"}

_SELECT = """
SELECT p.*, g.title AS goal_title,
       (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id AND t.completed_at IS NULL) AS open_tasks,
       (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id AND t.completed_at IS NOT NULL) AS done_tasks,
       COALESCE((SELECT SUM(minutes) FROM project_logs l WHERE l.project_id = p.id AND l.kind = 'time'), 0)
     + COALESCE((SELECT SUM(actual_seconds) / 60 FROM study_sessions ss WHERE ss.project_id = p.id), 0) AS minutes
FROM projects p LEFT JOIN goals g ON g.id = p.goal_id
"""


def safe_repo_url(url: str) -> str:
    """Accept only http(s) repository links (never file:, javascript: or similar)."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("https://", "http://")):
        raise ValidationError("Repository links must start with https://")
    if any(ch.isspace() for ch in url):
        raise ValidationError("Repository links can't contain spaces.")
    return url[:300]


class ProjectRepository(Repository):
    def _clean(self, data: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "name" in data:
            out["name"] = clean_text(data["name"], field="Project name", required=True, max_len=120)
        if "description" in data:
            out["description"] = clean_text(data["description"], field="Description", max_len=10000)
        if "status" in data:
            if data["status"] not in STATUSES:
                raise ValidationError("Unknown project status.")
            out["status"] = data["status"]
        if "goal_id" in data:
            out["goal_id"] = optional_id(data["goal_id"])
        if "repo_url" in data:
            out["repo_url"] = safe_repo_url(data["repo_url"])
        for key, label in (("start_date", "Start date"), ("target_date", "Target date")):
            if key in data:
                d = parse_date(data[key], field=label)
                out[key] = iso(d) if d else None
        if out.get("start_date") and out.get("target_date") and out["target_date"] < out["start_date"]:
            raise ValidationError("The target date must be on or after the start date.")
        return out

    def create(self, name: str, **fields: Any) -> int:
        data = self._clean({"name": name, **fields})
        data["created_at"] = data["updated_at"] = now_stamp()
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self.db.transaction():
            return self.db.insert(f"INSERT INTO projects ({cols}) VALUES ({marks})", list(data.values()))

    def update(self, project_id: int, **fields: Any) -> None:
        data = self._clean(fields)
        if not data:
            return
        data["updated_at"] = now_stamp()
        assignments = ", ".join(f"{k} = ?" for k in data)
        with self.db.transaction():
            self.db.execute(f"UPDATE projects SET {assignments} WHERE id = ?", [*data.values(), project_id])

    def delete(self, project_id: int) -> None:
        """Delete a project; its tasks stay (unlinked), its logs and milestones go with it."""
        with self.db.transaction():
            self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def get(self, project_id: int) -> Project | None:
        row = self.db.query_one(_SELECT + " WHERE p.id = ?", (project_id,))
        return from_row(Project, row) if row else None

    def list(self, statuses: tuple[str, ...] | None = None, search: str = "") -> list[Project]:
        where, params = [], []
        if statuses:
            where.append(f"p.status IN ({', '.join('?' for _ in statuses)})")
            params.extend(statuses)
        if search.strip():
            where.append("(p.name LIKE ? OR p.description LIKE ?)")
            params.extend([f"%{search.strip()}%"] * 2)
        sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "")
        sql += (" ORDER BY CASE p.status WHEN 'active' THEN 0 WHEN 'idea' THEN 1 WHEN 'paused' THEN 2 "
                "WHEN 'done' THEN 3 ELSE 4 END, p.target_date IS NULL, p.target_date, p.name COLLATE NOCASE")
        return [from_row(Project, r) for r in self.db.query(sql, params)]

    def choices(self) -> list[tuple[int, str]]:
        return [(p.id, p.name) for p in self.list(("idea", "active", "paused"))]

    # -- logs (notes, changelog, releases, time) ----------------------------------------
    def add_log(self, project_id: int, kind: str, text: str = "", day: date | None = None,
                minutes: int | None = None, version: str = "") -> int:
        if kind not in LOG_KINDS:
            raise ValidationError("Unknown log type.")
        text = clean_text(text, field="Text", max_len=10000)
        version = clean_text(version, field="Version", max_len=40)
        if kind == "time":
            if not minutes or int(minutes) <= 0:
                raise ValidationError("Enter the minutes you spent.")
            minutes = int(minutes)
        elif not text and not version:
            raise ValidationError("Write something for this entry.")
        else:
            minutes = None
        with self.db.transaction():
            log_id = self.db.insert(
                "INSERT INTO project_logs (project_id, kind, date, minutes, version, text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, kind, iso(day or today()), minutes, version, text, now_stamp()))
            self.db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now_stamp(), project_id))
        return log_id

    def logs(self, project_id: int, kind: str | None = None, limit: int = 300) -> list[ProjectLog]:
        sql = "SELECT * FROM project_logs WHERE project_id = ?"
        params: list[Any] = [project_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY date DESC, id DESC LIMIT ?"
        params.append(limit)
        return [from_row(ProjectLog, r) for r in self.db.query(sql, params)]

    def delete_log(self, log_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM project_logs WHERE id = ?", (log_id,))

    def minutes_between(self, start: date, end: date) -> int:
        logged = self.db.scalar("SELECT SUM(minutes) FROM project_logs WHERE kind = 'time' AND date BETWEEN ? AND ?",
                                (iso(start), iso(end)), 0)
        focus = self.db.scalar("SELECT SUM(actual_seconds) / 60 FROM study_sessions WHERE project_id IS NOT NULL "
                               "AND date BETWEEN ? AND ?", (iso(start), iso(end)), 0)
        return int(logged or 0) + int(focus or 0)
