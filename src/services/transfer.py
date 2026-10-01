"""Export (JSON / CSV) and validated JSON import.

JSON export contains every DayOS table and can be imported again. Import
*replaces* the current data: the file is fully validated first, a safety
backup is written, and all rows are inserted in a single transaction, so a
malformed file can never leave the database half-imported.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.database.connection import Database, open_connection
from src.database.schema import LATEST_VERSION
from src.version import APP_VERSION

log = logging.getLogger(__name__)

EXPORT_FORMAT = "dayos-export"
EXPORT_FORMAT_VERSION = 1
MAX_IMPORT_BYTES = 200 * 1024 * 1024

# Parent tables first so foreign keys resolve during import. Feature modules append their
# tables with :func:`register_tables`. Rebuildable data (the search index, the HTTP cache) is
# never exported; clipboard history is exported only when the user asks for it.
TABLE_ORDER = [
    "settings", "subjects", "goals", "goal_progress", "goal_milestones",
    "projects", "project_milestones", "project_logs",
    "tasks", "subtasks", "task_dependencies", "notes",
    "habits", "habit_logs", "journal", "weekly_reviews", "events", "event_skips", "timetable", "timetable_skips",
    "study_sessions", "exams", "chapters", "revision_logs", "mistakes", "mock_tests",
    "inbox", "reminders", "notification_state", "entity_links", "file_refs", "routine_items", "routine_logs",
    # StudyForge
    "sf_courses", "sf_documents", "sf_document_pages", "sf_nodes", "sf_questions", "sf_blueprints", "sf_tests",
    "sf_test_items", "sf_attempts", "sf_answers", "sf_topic_state", "sf_review_log", "sf_flashcards", "sf_materials",
    "sf_mistake_categories",
]
NOT_EXPORTED = {"http_cache", "sqlite_sequence"}
NOT_EXPORTED_PREFIXES = ("search_index",)
PRIVATE_TABLES: set[str] = set()  # exported only on request (e.g. clipboard history)


def register_tables(tables: list[str], private: bool = False) -> None:
    for table in tables:
        if table not in TABLE_ORDER:
            TABLE_ORDER.append(table)
        if private:
            PRIVATE_TABLES.add(table)


def unexported_tables(conn) -> list[str]:
    """Tables in the database that export would miss (used by tests to keep exports complete)."""
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return [n for n in names if n not in TABLE_ORDER and n not in NOT_EXPORTED
            and not n.startswith(NOT_EXPORTED_PREFIXES)]

CSV_EXPORTS: dict[str, str] = {
    "tasks": """SELECT t.id, t.title, t.description, t.due_date, t.due_time,
                  CASE t.priority WHEN 0 THEN 'low' WHEN 2 THEN 'high' ELSE 'normal' END AS priority,
                  t.category, s.name AS subject, g.title AS goal, t.estimate_minutes, t.created_at, t.completed_at
                FROM tasks t LEFT JOIN subjects s ON s.id = t.subject_id LEFT JOIN goals g ON g.id = t.goal_id
                ORDER BY t.id""",
    "notes": "SELECT id, title, tags, pinned, created_at, updated_at, content FROM notes ORDER BY id",
    "study_sessions": """SELECT ss.id, ss.date, ss.started_at, ss.ended_at, s.name AS subject,
                  ROUND(ss.actual_seconds / 60.0, 1) AS minutes, ss.planned_minutes, ss.completed, ss.source, ss.note
                FROM study_sessions ss LEFT JOIN subjects s ON s.id = ss.subject_id ORDER BY ss.started_at""",
    "habits": "SELECT id, name, description, weekdays, start_date, archived, created_at FROM habits ORDER BY id",
    "habit_logs": """SELECT h.name AS habit, l.date FROM habit_logs l JOIN habits h ON h.id = l.habit_id
                ORDER BY l.date, h.name""",
    "goals": """SELECT id, title, category, status, target_date, target_value, current_value, unit,
                  created_at, completed_at, description FROM goals ORDER BY id""",
    "goal_progress": """SELECT g.title AS goal, p.date, p.value, p.note FROM goal_progress p
                JOIN goals g ON g.id = p.goal_id ORDER BY p.date, p.id""",
    "events": """SELECT e.id, e.title, e.kind, e.date, e.start_time, e.end_time, s.name AS subject,
                  e.category, e.description FROM events e LEFT JOIN subjects s ON s.id = e.subject_id ORDER BY e.date""",
    "timetable": """SELECT t.id, t.title, t.weekday, t.start_time, t.end_time, s.name AS subject, t.location,
                  t.valid_from, t.valid_until FROM timetable t LEFT JOIN subjects s ON s.id = t.subject_id""",
    "exams": """SELECT x.id, x.title, s.name AS subject, x.exam_date, x.exam_time, x.syllabus, x.notes
                FROM exams x LEFT JOIN subjects s ON s.id = x.subject_id ORDER BY x.exam_date""",
    "chapters": """SELECT c.id, x.title AS exam, c.name, c.status, c.last_reviewed, c.next_review, c.review_count
                FROM chapters c JOIN exams x ON x.id = c.exam_id ORDER BY x.exam_date, c.position""",
    "mock_tests": """SELECT m.id, m.title, s.name AS subject, m.date, m.marks, m.max_marks,
                  ROUND(100.0 * m.marks / m.max_marks, 1) AS percent, m.notes
                FROM mock_tests m LEFT JOIN subjects s ON s.id = m.subject_id ORDER BY m.date""",
    "mistakes": """SELECT m.id, s.name AS subject, c.name AS chapter, m.question, m.correction, m.resolved, m.created_at
                FROM mistakes m LEFT JOIN subjects s ON s.id = m.subject_id LEFT JOIN chapters c ON c.id = m.chapter_id""",
    "journal": "SELECT date, intention, went_well, reflection FROM journal ORDER BY date",
}


class TransferError(RuntimeError):
    """A user-presentable export/import problem."""


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def export_json(db_path: Path, out_path: Path, include_private: bool = False) -> Path:
    """Write every table to one JSON file (atomically)."""
    conn = open_connection(db_path)
    try:
        tables: dict[str, list[dict[str, Any]]] = {}
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in TABLE_ORDER:
            if table not in existing or (table in PRIVATE_TABLES and not include_private):
                continue
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            data = [dict(r) for r in rows]
            if table == "settings":
                data = [r for r in data if not str(r["key"]).startswith("state.")]
            tables[table] = data
        payload = {
            "format": EXPORT_FORMAT,
            "format_version": EXPORT_FORMAT_VERSION,
            "schema_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
            "app_version": APP_VERSION,
            "exported_at": datetime.now().replace(microsecond=0).isoformat(sep=" "),
            "tables": tables,
        }
    finally:
        conn.close()
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=1))
    except OSError as exc:
        raise TransferError(f"Could not write the export file: {exc.strerror or exc}") from exc
    return out_path


def export_csv(db_path: Path, out_dir: Path) -> Path:
    """Write readable CSV files (one per record type) into a new folder."""
    folder = out_dir / f"dayos-csv-{_stamp()}"
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise TransferError(f"Could not create the export folder: {exc.strerror or exc}") from exc
    conn = open_connection(db_path)
    try:
        for name, sql in CSV_EXPORTS.items():
            cur = conn.execute(sql)
            headers = [c[0] for c in cur.description]
            target = folder / f"{name}.csv"
            tmp = target.with_suffix(".tmp")
            with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(headers)
                for row in cur:
                    writer.writerow(["" if v is None else v for v in row])
            os.replace(tmp, target)
    except OSError as exc:
        raise TransferError(f"Could not write CSV files: {exc.strerror or exc}") from exc
    finally:
        conn.close()
    return folder


def load_export(path: Path) -> dict[str, Any]:
    """Read and structurally validate a JSON export. Raises TransferError."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TransferError(f"Could not open the file: {exc.strerror or exc}") from exc
    if size > MAX_IMPORT_BYTES:
        raise TransferError("The file is too large to be a DayOS export.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise TransferError("The file is not a text JSON file.") from None
    except json.JSONDecodeError as exc:
        raise TransferError(f"The file is not valid JSON (line {exc.lineno}, column {exc.colno}).") from None
    if not isinstance(payload, dict) or payload.get("format") != EXPORT_FORMAT:
        raise TransferError("This JSON file is not a DayOS export.")
    if payload.get("format_version") != EXPORT_FORMAT_VERSION:
        raise TransferError("This export uses an unsupported format version.")
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 1:
        raise TransferError("The export is missing its schema version.")
    if schema_version > LATEST_VERSION:
        raise TransferError("This export was made by a newer version of DayOS. Update DayOS to import it.")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise TransferError("The export does not contain any tables.")
    unknown = set(tables) - set(TABLE_ORDER)
    if unknown:
        raise TransferError(f"The export contains unknown tables: {', '.join(sorted(unknown))}.")
    for name, rows in tables.items():
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise TransferError(f"The '{name}' section of the export is malformed.")
    return payload


def import_json(db: Database, path: Path, backups_dir: Path) -> dict[str, int]:
    """Replace all data with the export's contents. Returns rows imported per table."""
    from src.services.backup import create_backup  # local import avoids a cycle

    payload = load_export(path)
    tables: dict[str, list[dict[str, Any]]] = payload["tables"]
    columns = {
        t: {r[1] for r in db.query(f"PRAGMA table_info({t})")} for t in TABLE_ORDER
    }
    # Private tables (clipboard history) are only replaced when the export contains them.
    replace_tables = [t for t in TABLE_ORDER if t not in PRIVATE_TABLES or t in tables]
    for table, rows in tables.items():
        for i, row in enumerate(rows, start=1):
            extra = set(row) - columns[table]
            if extra:
                raise TransferError(f"Row {i} of '{table}' has unknown fields: {', '.join(sorted(extra))}.")
            for key, value in row.items():
                if value is not None and not isinstance(value, (str, int, float)):
                    raise TransferError(f"Row {i} of '{table}' has an invalid value for '{key}'.")
    create_backup(db.path, backups_dir, label="pre-import")
    counts: dict[str, int] = {}
    current_table = ""
    current_row = 0
    try:
        with db.transaction():
            # Tables reference each other in both directions (e.g. mistakes -> StudyForge topics), so
            # foreign keys are checked once at the end of the import instead of row by row.
            db.execute("PRAGMA defer_foreign_keys = ON")
            for table in reversed(replace_tables):
                if table == "settings":
                    db.execute("DELETE FROM settings WHERE key NOT LIKE 'state.%'")
                else:
                    db.execute(f"DELETE FROM {table}")
            for table in replace_tables:
                current_table = table
                rows = tables.get(table, [])
                if table == "settings":
                    rows = [r for r in rows if not str(r.get("key", "")).startswith("state.")]
                for current_row, row in enumerate(rows, start=1):
                    if not row:
                        continue
                    cols = ", ".join(row)
                    marks = ", ".join("?" for _ in row)
                    db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))
                counts[table] = len(rows)
            problems = db.query("PRAGMA foreign_key_check")
            if problems:
                raise TransferError(
                    f"The export has records pointing to missing data (first problem in '{problems[0][0]}')."
                )
    except sqlite3.IntegrityError as exc:
        raise TransferError(
            f"Row {current_row} of '{current_table}' is invalid ({exc}). Nothing was changed."
        ) from None
    except sqlite3.Error as exc:
        raise TransferError(f"Import failed ({exc}). Nothing was changed.") from None
    log.info("Imported export %s", Path(path).name)
    return counts
