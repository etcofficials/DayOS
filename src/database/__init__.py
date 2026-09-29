"""Database access: connection, schema and migrations."""

from __future__ import annotations

import logging
from pathlib import Path

from src.database.connection import Database, DatabaseError, open_connection
from src.database.schema import LATEST_VERSION, migrate

log = logging.getLogger(__name__)

__all__ = ["Database", "DatabaseError", "open_connection", "init_database", "LATEST_VERSION"]


def init_database(db_path: Path, backups_dir: Path | None = None) -> Database:
    """Open (creating if needed) and migrate the database.

    Before an existing database is upgraded to a newer schema, a consistent
    snapshot is written to ``backups_dir`` so an update can never lose data.
    """
    db = Database(db_path)

    def backup_first(current: int, target: int) -> None:
        if backups_dir is None:
            return
        from src.services.backup import create_backup

        path = create_backup(db.path, backups_dir, label=f"pre-upgrade-v{current}-to-v{target}")
        log.info("Pre-upgrade backup written to %s", path)

    try:
        migrate(db, before_upgrade=backup_first)
    except Exception:
        db.close()
        raise
    return db
