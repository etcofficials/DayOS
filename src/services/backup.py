"""Consistent SQLite backups and safe restore.

* Backups use SQLite's online backup API, so they are consistent even while
  DayOS is running. Each backup is written to a temporary file, verified with
  ``PRAGMA integrity_check`` and only then renamed into place.
* Backups are never deleted or overwritten automatically.
* Restoring first validates the chosen file, then writes a "pre-restore"
  safety backup of the current data, then copies the backup into the live
  database in one step and upgrades its schema if it came from an older version.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.database.connection import Database, DatabaseError, open_connection
from src.database.schema import LATEST_VERSION, migrate

log = logging.getLogger(__name__)

REQUIRED_TABLES = {"settings", "tasks", "notes", "habits", "goals", "study_sessions", "exams"}
COUNTED_TABLES = ["tasks", "notes", "habits", "goals", "events", "study_sessions", "exams", "mock_tests"]


class BackupError(RuntimeError):
    """A user-presentable backup/restore problem."""


@dataclass
class BackupInfo:
    path: Path
    schema_version: int
    counts: dict[str, int]
    size_bytes: int
    modified: datetime


def _unique_path(directory: Path, stem: str, suffix: str = ".db") -> Path:
    candidate = directory / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{n}{suffix}"
        n += 1
    return candidate


def create_backup(db_path: Path, backups_dir: Path, label: str = "") -> Path:
    """Write a verified, timestamped snapshot of ``db_path``. Returns its path."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(ch for ch in label if ch.isalnum() or ch in "-_")
    stem = f"dayos-backup-{stamp}" + (f"-{safe_label}" if safe_label else "")
    final = _unique_path(backups_dir, stem)
    partial = final.with_suffix(".partial")
    try:
        source = open_connection(db_path)
        try:
            dest = sqlite3.connect(str(partial))
            try:
                source.backup(dest)
                dest.execute("PRAGMA journal_mode = DELETE")
                result = dest.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise BackupError(f"The backup failed verification: {result}")
            finally:
                dest.close()
        finally:
            source.close()
        os.replace(partial, final)
    except sqlite3.Error as exc:
        raise BackupError(f"Could not create a backup: {exc}") from exc
    except OSError as exc:
        raise BackupError(f"Could not write the backup file: {exc.strerror or exc}") from exc
    finally:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                log.warning("Could not remove partial backup %s", partial)
    log.info("Backup created: %s", final.name)
    return final


def inspect_backup(path: Path) -> BackupInfo:
    """Validate a backup file without modifying it."""
    path = Path(path)
    if not path.is_file():
        raise BackupError("The selected backup file does not exist.")
    with path.open("rb") as fh:
        if fh.read(16) != b"SQLite format 3\x00":
            raise BackupError("The selected file is not a DayOS backup (it is not an SQLite database).")
    try:
        conn = open_connection(path, readonly=True)
    except sqlite3.Error as exc:
        raise BackupError(f"The backup could not be opened: {exc}") from exc
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise BackupError(f"The backup is damaged: {integrity}")
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if version < 1 or not REQUIRED_TABLES <= tables:
            raise BackupError("The selected file is an SQLite database but not a DayOS backup.")
        if version > LATEST_VERSION:
            raise BackupError("This backup was made by a newer version of DayOS. Update DayOS to restore it.")
        counts = {t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in COUNTED_TABLES if t in tables}
    except sqlite3.Error as exc:
        raise BackupError(f"The backup could not be read: {exc}") from exc
    finally:
        conn.close()
    stat = path.stat()
    return BackupInfo(path, version, counts, stat.st_size, datetime.fromtimestamp(stat.st_mtime))


def restore_backup(db: Database, backup_path: Path, backups_dir: Path) -> Path:
    """Replace the live data with ``backup_path``. Returns the safety-backup path."""
    inspect_backup(backup_path)
    safety = create_backup(db.path, backups_dir, label="pre-restore")
    try:
        source = open_connection(backup_path, readonly=True)
        try:
            source.backup(db.conn)
        finally:
            source.close()
        db.execute("PRAGMA foreign_keys = ON")
        migrate(db)
        problems = db.integrity_check()
        if problems:
            raise BackupError("The restored data failed verification: " + "; ".join(problems[:3]))
    except (sqlite3.Error, DatabaseError) as exc:
        raise BackupError(
            f"Restore failed: {exc}\n\nYour previous data was saved first to:\n{safety}"
        ) from exc
    log.info("Restored backup %s (safety copy %s)", Path(backup_path).name, safety.name)
    return safety


def list_backups(backups_dir: Path) -> list[Path]:
    if not backups_dir.exists():
        return []
    return sorted(backups_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
