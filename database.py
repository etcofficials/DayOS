"""Database maintenance helper.

The database layer itself lives in ``src/database``. This script offers a
few safe maintenance commands without opening the app:

    .venv\\Scripts\\python.exe database.py check     # initialize/migrate, then integrity check
    .venv\\Scripts\\python.exe database.py backup    # write a verified backup to backups\\
    .venv\\Scripts\\python.exe database.py info      # schema version and record counts
"""

from __future__ import annotations

import sys

from src.config import AppPaths, default_home, ensure_writable
from src.database import Database, DatabaseError, init_database  # re-exported for convenience

__all__ = ["Database", "DatabaseError", "init_database", "main"]


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "check"
    paths = AppPaths(default_home())
    ensure_writable(paths)
    if command == "backup":
        from src.services.backup import create_backup

        init_database(paths.db_path, paths.backups_dir).close()
        print(f"Backup written: {create_backup(paths.db_path, paths.backups_dir, label='manual')}")
        return 0
    db = init_database(paths.db_path, paths.backups_dir)
    try:
        if command == "info":
            from src.services.backup import COUNTED_TABLES

            print(f"Database: {db.path}\nSchema version: {db.user_version}")
            for table in COUNTED_TABLES:
                print(f"  {table}: {db.scalar(f'SELECT COUNT(*) FROM {table}', default=0)}")
            return 0
        problems = db.integrity_check()
        if problems:
            print("Problems found:\n  " + "\n  ".join(problems))
            return 2
        print(f"OK - {db.path} (schema version {db.user_version})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
