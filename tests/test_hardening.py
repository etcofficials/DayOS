"""Automatic backups, migrating a real v1 database copy, and repository hygiene checks."""

import shutil
import sqlite3
import subprocess
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from src.database import Database
from src.database.schema import LATEST_VERSION, migrate
from src.services import autobackup
from src.services.backup import create_backup, inspect_backup
from tests.helpers import TempHomeTestCase

ROOT = Path(__file__).resolve().parent.parent


class AutoBackupTests(TempHomeTestCase):
    def test_due_create_and_rotation_never_touch_other_backups(self):
        b = self.paths.backups_dir
        manual = create_backup(self.paths.db_path, b, label="manual")
        self.assertTrue(autobackup.is_due(b, "weekly"))
        self.assertFalse(autobackup.is_due(b, "off"))
        first = autobackup.run(self.paths.db_path, b, "weekly", keep=2)
        self.assertIsNotNone(first)
        self.assertEqual(inspect_backup(first).schema_version, LATEST_VERSION)
        self.assertFalse(autobackup.is_due(b, "weekly"))
        self.assertIsNone(autobackup.run(self.paths.db_path, b, "weekly", keep=2))
        self.assertTrue(autobackup.is_due(b, "weekly", datetime.now() + timedelta(days=8)))
        for stamp in ("20200101-000000", "20210101-000000", "20220101-000000"):
            shutil.copy(first, b / f"dayos-backup-{stamp}-auto.db")
        removed = autobackup.prune(b, keep=2)
        self.assertEqual(len(removed), 2)
        self.assertTrue(manual.exists())
        self.assertEqual(len(autobackup.auto_backups(b)), 2)


class RealDatabaseCopyMigration(unittest.TestCase):
    """Migrates a *copy* of the development database (never the original) to the latest schema."""

    def test_copy_of_dev_database_migrates_and_keeps_rows(self):
        source = ROOT / "data" / "dayos.db"
        if not source.exists():
            self.skipTest("no development database on this machine")
        tmp = ROOT / "tests" / ".tmp" / "dev-copy"
        tmp.mkdir(parents=True, exist_ok=True)
        copy = tmp / "dayos-copy.db"
        try:
            src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
            dst = sqlite3.connect(copy)
            src.backup(dst)
            before_version = src.execute("PRAGMA user_version").fetchone()[0]
            counts = {t: src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for (t,) in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE "
                                              "'sqlite_%' AND name NOT LIKE 'search_index%'")}
            src.close()
            dst.close()
            db = Database(copy)
            migrate(db)
            self.assertEqual(db.user_version, LATEST_VERSION)
            self.assertEqual(db.integrity_check(), [])
            for table, n in counts.items():
                if table == "settings":
                    continue  # migrations may add preference rows
                self.assertEqual(db.scalar(f"SELECT COUNT(*) FROM {table}"), n, table)
            db.close()
            self.assertLessEqual(before_version, LATEST_VERSION)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RepositoryHygiene(unittest.TestCase):
    def test_no_private_data_or_secrets_are_tracked(self):
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
        forbidden = [f for f in files if f.endswith((".db", ".db-wal", ".db-shm", ".log", ".partial"))
                     or f.startswith(("data/", "backups/", "exports/", "logs/", "dist/", "build/"))]
        self.assertEqual(forbidden, [])
        import re

        secret = re.compile(r"(sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|"
                            r"AKIA[0-9A-Z]{16})")
        for f in files:
            path = ROOT / f
            if f and path.is_file() and path.suffix in (".py", ".md", ".txt", ".json", ".spec", ".ps1", ".toml"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                hits = [m for m in secret.findall(text) if "x" * 10 not in m and "a" * 10 not in m]
                self.assertEqual(hits, [], f)


if __name__ == "__main__":
    unittest.main()
