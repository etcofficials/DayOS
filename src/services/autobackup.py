"""Automatic backups: a verified snapshot at most once per day or week (the user's choice).

Runs on a worker thread a little after start-up, never on the UI thread. Only automatic
backups (``dayos-backup-<stamp>-auto.db``) are rotated, keeping the newest N; manual,
pre-upgrade, pre-import and pre-restore backups are never removed by DayOS.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from src.services.backup import create_backup

log = logging.getLogger(__name__)

INTERVALS = {"off": None, "daily": timedelta(days=1), "weekly": timedelta(days=7)}
AUTO_PATTERN = re.compile(r"^dayos-backup-\d{8}-\d{6}-auto(-\d+)?\.db$")


def auto_backups(backups_dir: Path) -> list[Path]:
    """Automatic backups, newest first."""
    if not backups_dir.exists():
        return []
    files = [p for p in backups_dir.iterdir() if p.is_file() and AUTO_PATTERN.match(p.name)]
    return sorted(files, key=lambda p: p.name, reverse=True)


def last_auto(backups_dir: Path) -> datetime | None:
    files = auto_backups(backups_dir)
    if not files:
        return None
    try:
        return datetime.strptime(files[0].name[len("dayos-backup-"):len("dayos-backup-") + 15], "%Y%m%d-%H%M%S")
    except ValueError:
        return datetime.fromtimestamp(files[0].stat().st_mtime)


def is_due(backups_dir: Path, interval: str, now: datetime | None = None) -> bool:
    step = INTERVALS.get(interval)
    if step is None:
        return False
    last = last_auto(backups_dir)
    return last is None or (now or datetime.now()) - last >= step


def prune(backups_dir: Path, keep: int) -> list[Path]:
    """Remove automatic backups beyond the newest ``keep``. Returns what was removed."""
    removed = []
    for path in auto_backups(backups_dir)[max(1, keep):]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            log.warning("Could not remove old automatic backup %s", path.name)
    return removed


def run(db_path: Path, backups_dir: Path, interval: str, keep: int) -> Path | None:
    """Create an automatic backup if one is due (call from a worker thread)."""
    if not is_due(backups_dir, interval):
        return None
    path = create_backup(db_path, backups_dir, label="auto")
    prune(backups_dir, keep)
    return path
