import sqlite3
import unittest

from src.database import Database, DatabaseError, init_database
from src.database.schema import LATEST_VERSION, MIGRATIONS, migrate
from tests.helpers import TempHomeTestCase

EXPECTED_TABLES = {
    "settings", "subjects", "goals", "goal_progress", "tasks", "subtasks", "notes", "habits", "habit_logs",
    "journal", "events", "timetable", "timetable_skips", "study_sessions", "exams", "chapters",
    "revision_logs", "mistakes", "mock_tests",
}


class DatabaseInitTests(TempHomeTestCase):
    def tables(self):
        return {r[0] for r in self.ctx.db.query("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_initialization_creates_schema(self):
        self.assertEqual(self.ctx.db.user_version, LATEST_VERSION)
        self.assertTrue(EXPECTED_TABLES <= self.tables())
        self.assertEqual(self.ctx.db.integrity_check(), [])

    def test_repeated_initialization_is_safe_and_keeps_data(self):
        self.ctx.tasks.create("Keep me")
        for _ in range(3):
            self.reopen()
        self.assertEqual([t.title for t in self.ctx.tasks.list("all")], ["Keep me"])
        self.assertEqual(self.ctx.db.user_version, LATEST_VERSION)

    def test_foreign_keys_are_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ctx.db.transaction():
                self.ctx.db.execute("INSERT INTO subtasks (task_id, title) VALUES (999, 'orphan')")

    def test_transaction_rolls_back_on_error(self):
        with self.assertRaises(RuntimeError):
            with self.ctx.db.transaction():
                self.ctx.db.execute(
                    "INSERT INTO notes (title, created_at, updated_at) VALUES ('x', 'now', 'now')")
                raise RuntimeError("boom")
        self.assertEqual(self.ctx.notes.count(), 0)

    def test_nested_transaction_uses_savepoint(self):
        with self.ctx.db.transaction():
            self.ctx.notes.create("outer")
            with self.assertRaises(ValueError):
                with self.ctx.db.transaction():
                    self.ctx.db.execute(
                        "INSERT INTO notes (title, created_at, updated_at) VALUES ('inner', 'a', 'a')")
                    raise ValueError
        self.assertEqual([n.title for n in self.ctx.notes.list()], ["outer"])

    def test_newer_schema_is_refused_without_changes(self):
        self.ctx.db.execute(f"PRAGMA user_version = {LATEST_VERSION + 5}")
        self.ctx.close()
        with self.assertRaises(DatabaseError):
            init_database(self.paths.db_path, self.paths.backups_dir)
        # the file is untouched and still reports the newer version
        raw = sqlite3.connect(self.paths.db_path)
        self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], LATEST_VERSION + 5)
        raw.execute(f"PRAGMA user_version = {LATEST_VERSION}")
        raw.close()
        self.ctx = self.reopen_raw()

    def reopen_raw(self):
        from src.context import AppContext

        return AppContext.open(self.paths)


class MigrationTests(TempHomeTestCase):
    def test_future_migration_applies_and_backs_up_first(self):
        self.ctx.tasks.create("Existing task")
        calls = []

        def add_column(db: Database) -> None:
            db.execute("ALTER TABLE tasks ADD COLUMN colour TEXT NOT NULL DEFAULT ''")

        def before(current, target):
            calls.append((current, target))
            from src.services.backup import create_backup

            create_backup(self.ctx.db.path, self.paths.backups_dir, label="pre-upgrade")

        migrations = MIGRATIONS + [(LATEST_VERSION + 1, add_column)]
        version = migrate(self.ctx.db, migrations, before)
        self.assertEqual(version, LATEST_VERSION + 1)
        self.assertEqual(calls, [(LATEST_VERSION, LATEST_VERSION + 1)])
        self.assertEqual(len(list(self.paths.backups_dir.glob("*pre-upgrade*.db"))), 1)
        row = self.ctx.db.query_one("SELECT title, colour FROM tasks")
        self.assertEqual((row["title"], row["colour"]), ("Existing task", ""))
        # running again is a no-op
        self.assertEqual(migrate(self.ctx.db, migrations, before), LATEST_VERSION + 1)
        self.assertEqual(len(calls), 1)

    def test_failed_migration_rolls_back(self):
        def broken(db: Database) -> None:
            db.execute("CREATE TABLE temp_new (id INTEGER)")
            db.execute("THIS IS NOT SQL")

        with self.assertRaises(sqlite3.Error):
            migrate(self.ctx.db, MIGRATIONS + [(LATEST_VERSION + 1, broken)])
        self.assertEqual(self.ctx.db.user_version, LATEST_VERSION)
        tables = {r[0] for r in self.ctx.db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("temp_new", tables)


if __name__ == "__main__":
    unittest.main()
