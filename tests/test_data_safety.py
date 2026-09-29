"""Backups, restore, export/import, settings and statistics."""

import csv
import json
import unittest
from datetime import date, datetime, timedelta

from src.repositories.study import new_session_uid
from src.services import stats
from src.services.backup import BackupError, create_backup, inspect_backup, list_backups, restore_backup
from src.services.transfer import TransferError, export_csv, export_json, import_json, load_export
from tests.helpers import FIXED_NOW, TempHomeTestCase

TODAY = FIXED_NOW.date()


class BackupTests(TempHomeTestCase):
    def test_backup_is_consistent_and_restorable(self):
        self.ctx.tasks.create("Before backup")
        path = create_backup(self.paths.db_path, self.paths.backups_dir, label="manual")
        self.assertTrue(path.name.startswith("dayos-backup-") and path.suffix == ".db")
        info = inspect_backup(path)
        self.assertEqual(info.counts["tasks"], 1)
        self.ctx.tasks.create("After backup")
        self.ctx.notes.create("Note after backup")
        safety = restore_backup(self.ctx.db, path, self.paths.backups_dir)
        self.assertEqual([t.title for t in self.ctx.tasks.list("all")], ["Before backup"])
        self.assertEqual(self.ctx.notes.count(), 0)
        # the pre-restore safety copy holds the replaced data
        self.assertEqual(inspect_backup(safety).counts["tasks"], 2)
        self.assertEqual(self.ctx.db.integrity_check(), [])
        # data persists after reopening
        self.reopen()
        self.assertEqual(len(self.ctx.tasks.list("all")), 1)

    def test_backups_never_overwrite_each_other(self):
        first = create_backup(self.paths.db_path, self.paths.backups_dir, label="same")
        second = create_backup(self.paths.db_path, self.paths.backups_dir, label="same")
        self.assertNotEqual(first, second)
        self.assertEqual(len(list_backups(self.paths.backups_dir)), 2)
        self.assertEqual(list(self.paths.backups_dir.glob("*.partial")), [])

    def test_invalid_backups_are_rejected_without_changes(self):
        self.ctx.tasks.create("Precious")
        junk = self.home / "junk.db"
        junk.write_bytes(b"not a database at all")
        with self.assertRaises(BackupError):
            inspect_backup(junk)
        import sqlite3

        other = self.home / "other.db"
        conn = sqlite3.connect(other)
        conn.execute("CREATE TABLE something (x)")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()
        with self.assertRaises(BackupError):
            restore_backup(self.ctx.db, other, self.paths.backups_dir)
        with self.assertRaises(BackupError):
            inspect_backup(self.home / "missing.db")
        self.assertEqual([t.title for t in self.ctx.tasks.list("all")], ["Precious"])


class TransferTests(TempHomeTestCase):
    def populate(self):
        sid = self.ctx.subjects.create("Art")
        gid = self.ctx.goals.create("Portfolio", target_value=10, unit="pieces")
        self.ctx.goals.log_progress(gid, 2)
        tid = self.ctx.tasks.create("Sketch", subject_id=sid, goal_id=gid, due_date=TODAY)
        self.ctx.tasks.replace_subtasks(tid, [("pencils", True)])
        self.ctx.notes.create("Ideas", "colour study", "art")
        hid = self.ctx.habits.create("Draw daily")
        self.ctx.habits.set_done(hid, TODAY, True)
        self.ctx.study.record(session_uid=new_session_uid(), subject_id=sid, started_at=FIXED_NOW, actual_seconds=900)
        xid = self.ctx.exams.create_exam(title="Art theory", subject_id=sid, exam_date=TODAY + timedelta(days=5))
        cid = self.ctx.exams.add_chapter(xid, "Colour")
        self.ctx.exams.log_revision(cid, "okay")
        self.ctx.exams.add_test(title="Quiz", subject_id=sid, exam_id=xid, date=TODAY, marks=7, max_marks=10)
        self.ctx.schedule.create_entry(title="Studio", weekday=2, start_time="14:00", end_time="16:00")
        self.ctx.journal.save(TODAY, intention="Paint")
        self.ctx.settings.set("theme", "light")
        self.ctx.settings.set("state.study.active", {"x": 1})

    def snapshot(self):
        from src.services.transfer import TABLE_ORDER

        out = {}
        for table in TABLE_ORDER:
            rows = [dict(r) for r in self.ctx.db.query(f"SELECT * FROM {table} ORDER BY rowid")]
            if table == "settings":
                rows = [r for r in rows if not r["key"].startswith("state.")]
            out[table] = rows
        return out

    def test_json_round_trip_restores_everything(self):
        self.populate()
        before = self.snapshot()
        out = export_json(self.paths.db_path, self.paths.exports_dir / "export.json")
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["format"], "dayos-export")
        self.assertNotIn("state.study.active", [r["key"] for r in payload["tables"]["settings"]])
        # wipe by importing into a brand-new home
        self.reopen()
        self.ctx.tasks.create("Will be replaced")
        counts = import_json(self.ctx.db, out, self.paths.backups_dir)
        self.assertEqual(counts["tasks"], 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ctx.db.integrity_check(), [])
        self.assertTrue(any("pre-import" in p.name for p in list_backups(self.paths.backups_dir)))
        # app state keys are preserved by import
        self.assertEqual(self.ctx.db.scalar("SELECT value FROM settings WHERE key = 'state.study.active'"), '{"x": 1}')

    def test_malformed_files_are_rejected(self):
        bad = self.home / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(TransferError):
            load_export(bad)
        bad.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
        with self.assertRaises(TransferError):
            load_export(bad)
        bad.write_text(json.dumps({"format": "dayos-export", "format_version": 1, "schema_version": 1,
                                   "tables": {"evil; DROP TABLE tasks": []}}), encoding="utf-8")
        with self.assertRaises(TransferError):
            load_export(bad)
        bad.write_bytes(b"\xff\xfe\x00garbage")
        with self.assertRaises(TransferError):
            load_export(bad)

    def test_invalid_rows_roll_back_completely(self):
        self.ctx.tasks.create("Original")
        bad = self.home / "bad_rows.json"
        payload = {"format": "dayos-export", "format_version": 1, "schema_version": 1, "tables": {
            "notes": [{"id": 1, "title": "ok", "content": "", "tags": "", "pinned": 0,
                       "created_at": "x", "updated_at": "x"}],
            "tasks": [{"id": 1, "title": "", "created_at": "x"}],  # empty title violates CHECK
        }}
        bad.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(TransferError):
            import_json(self.ctx.db, bad, self.paths.backups_dir)
        self.assertEqual([t.title for t in self.ctx.tasks.list("all")], ["Original"])
        self.assertEqual(self.ctx.notes.count(), 0)
        payload["tables"] = {"tasks": [{"id": 1, "title": "x", "created_at": "x", "hacker_column": 1}]}
        bad.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(TransferError):
            import_json(self.ctx.db, bad, self.paths.backups_dir)
        payload["tables"] = {"subtasks": [{"id": 1, "task_id": 999, "title": "orphan"}]}
        bad.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(TransferError):
            import_json(self.ctx.db, bad, self.paths.backups_dir)
        self.assertEqual([t.title for t in self.ctx.tasks.list("all")], ["Original"])

    def test_csv_export(self):
        self.populate()
        folder = export_csv(self.paths.db_path, self.paths.exports_dir)
        with (folder / "tasks.csv").open(encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[0]["title"], "Sketch")
        self.assertEqual(rows[0]["subject"], "Art")
        self.assertTrue((folder / "study_sessions.csv").exists())
        self.assertEqual(list(folder.glob("*.tmp")), [])


class SettingsTests(TempHomeTestCase):
    def test_defaults_persistence_and_validation(self):
        s = self.ctx.settings
        self.assertEqual((s.get("theme"), s.get("week_start"), s.get("clock_24h")), ("light", 0, True))
        s.set("theme", "dark")
        s.set("week_start", 6)
        with self.assertRaises(ValueError):
            s.set("theme", "neon")
        with self.assertRaises(ValueError):
            s.set("week_start", 9)
        with self.assertRaises(KeyError):
            s.set("unknown", 1)
        self.reopen()
        self.assertEqual((self.ctx.settings.get("theme"), self.ctx.settings.get("week_start")), ("dark", 6))

    def test_corrupt_values_fall_back_to_defaults(self):
        with self.ctx.db.transaction():
            self.ctx.db.execute("INSERT INTO settings (key, value) VALUES ('theme', '{broken')")
            self.ctx.db.execute("INSERT INTO settings (key, value) VALUES ('week_start', '\"monday\"')")
        self.reopen()
        self.assertEqual(self.ctx.settings.get("theme"), "light")
        self.assertEqual(self.ctx.settings.get("week_start"), 0)

    def test_reset_keeps_data_and_state(self):
        self.ctx.tasks.create("Keep")
        self.ctx.settings.set("theme", "dark")
        self.ctx.settings.set("state.window_geometry", "abc")
        self.ctx.settings.reset_preferences()
        self.assertEqual(self.ctx.settings.get("theme"), "light")
        self.assertEqual(self.ctx.settings.get("state.window_geometry"), "abc")
        self.assertEqual(len(self.ctx.tasks.list("all")), 1)


class StatsTests(TempHomeTestCase):
    def test_aggregate_day_and_week_buckets(self):
        start, end = date(2026, 9, 21), date(2026, 9, 27)
        daily = {date(2026, 9, 21): 2, date(2026, 9, 27): 1, date(2026, 9, 28): 99}
        buckets = stats.aggregate(daily, start, end)
        self.assertEqual(len(buckets), 7)
        self.assertEqual(sum(b.value for b in buckets), 3)  # value outside range excluded
        long_start = date(2026, 6, 30)
        weekly = stats.aggregate({date(2026, 7, 1): 3, date(2026, 9, 27): 4}, long_start, end, first_weekday=0)
        self.assertEqual(stats.bucket_kind(long_start, end), "week")
        self.assertEqual(weekly[0].start, long_start)  # first bucket clipped to range start
        self.assertEqual(weekly[-1].end, end)
        self.assertEqual(sum(b.value for b in weekly), 7)

    def test_task_and_study_stats_respect_local_date_boundaries(self):
        late = self.ctx.tasks.create("Late")
        early = self.ctx.tasks.create("Early")
        self.set_now(datetime(2026, 9, 26, 23, 59, 59))
        self.ctx.tasks.set_completed(late, True)
        self.set_now(datetime(2026, 9, 27, 0, 0, 0))
        self.ctx.tasks.set_completed(early, True)
        daily = stats.tasks_completed_daily(self.ctx.db, date(2026, 9, 27), date(2026, 9, 27))
        self.assertEqual(daily, {date(2026, 9, 27): 1.0})
        summary = stats.tasks_summary(self.ctx.db, date(2026, 9, 21), date(2026, 9, 27))
        self.assertEqual((summary["completed"], summary["created"]), (2, 2))
        self.ctx.study.record(session_uid=new_session_uid(), subject_id=None,
                              started_at=datetime(2026, 9, 27, 7), actual_seconds=3600)
        s = stats.study_summary(self.ctx.db, date(2026, 9, 27), date(2026, 9, 27))
        self.assertEqual((s["sessions"], s["seconds"], s["days"]), (1, 3600, 1))
        self.assertEqual(stats.study_daily_minutes(self.ctx.db, date(2026, 9, 27), date(2026, 9, 27)),
                         {date(2026, 9, 27): 60.0})
        activity = stats.recent_activity(self.ctx.db)
        self.assertEqual(activity[0][1], "study")


if __name__ == "__main__":
    unittest.main()
