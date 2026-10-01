"""FilePilot: read-only scanning, duplicates by content, and safe, recorded file operations."""

import ctypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.modules.filepilot import operations, scanner  # noqa: E402
from src.modules.filepilot.duplicates import find_duplicates  # noqa: E402
from src.modules.filepilot.operations import OperationHistory, execute, move_file, plan_moves, plan_recycle  # noqa: E402
from tests.helpers import TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def write(path, data: bytes, age_days: float = 0) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return str(path)


class FilePilotDataTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.home / "scan"
        self.downloads = str(self.root / "Downloads")
        write(self.root / "a" / "report.pdf", b"x" * 3000)
        write(self.root / "a" / "deep" / "movie.mp4", b"v" * 50_000)
        write(self.root / "Screenshots" / "Screenshot 2026.png", b"p" * 10)
        write(self.root / "Downloads" / "tool_setup.exe", b"e" * 500, age_days=200)
        write(self.root / "Downloads" / "fresh.zip", b"z" * 700)
        hidden = write(self.root / "secret.txt", b"h" * 5)
        ctypes.windll.kernel32.SetFileAttributesW(hidden, 0x2)

    def test_scan_sizes_categories_and_hidden(self):
        result = scanner.scan([str(self.root)], downloads=self.downloads)
        names = {os.path.basename(f.path): f.category for f in result.files}
        self.assertEqual(names, {"report.pdf": "pdf", "movie.mp4": "videos", "Screenshot 2026.png": "screenshots",
                                 "tool_setup.exe": "installers", "fresh.zip": "archives"})
        self.assertEqual(result.folder_sizes[str(self.root / "a")], 53_000)
        self.assertEqual(result.folder_sizes[str(self.root)], 3000 + 50_000 + 10 + 500 + 700)
        self.assertGreaterEqual(result.skipped, 1)  # the hidden file
        with_hidden = scanner.scan([str(self.root)], include_hidden=True, downloads=self.downloads)
        self.assertEqual(len(with_hidden.files), 6)
        old = scanner.old_downloads(result.files, 90, downloads=self.downloads)
        self.assertEqual([os.path.basename(f.path) for f in old], ["tool_setup.exe"])
        self.assertEqual(scanner.largest(result.files, 10_000)[0].path, str(self.root / "a" / "deep" / "movie.mp4"))

    def test_junctions_are_not_followed_and_nested_roots_once(self):
        outside = self.home / "outside"
        write(outside / "big.bin", b"o" * 1000)
        link = self.root / "link"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if made.returncode != 0:
            self.skipTest("could not create a junction")
        result = scanner.scan([str(self.root), str(self.root / "a")], downloads=self.downloads)
        self.assertNotIn("big.bin", {os.path.basename(f.path) for f in result.files})
        self.assertEqual(len([f for f in result.files if f.path.endswith("report.pdf")]), 1)
        os.rmdir(link)  # removes only the junction, never the target

    def test_scan_can_be_cancelled(self):
        cancel = threading.Event()
        cancel.set()
        result = scanner.scan([str(self.root)], cancel)
        self.assertTrue(result.cancelled)

    def test_duplicates_by_content_not_name(self):
        d = self.home / "dups"
        a = write(d / "one" / "photo.jpg", b"same content" * 100)
        b = write(d / "two" / "copy of photo.jpg", b"same content" * 100)
        write(d / "three" / "photo.jpg", b"diff content" * 100)  # same name and size, other bytes
        big1 = bytearray(os.urandom(300_000))
        big2 = bytearray(big1)
        big2[150_000] ^= 0xFF  # same size, same start and end, differs in the middle
        write(d / "big1.bin", bytes(big1))
        write(d / "big2.bin", bytes(big2))
        mid1 = bytearray(os.urandom(100_000))
        mid2 = bytearray(mid1)
        mid2[80_000] ^= 0xFF  # 64-128 KB: differs after the first 64 KB
        write(d / "mid1.bin", bytes(mid1))
        write(d / "mid2.bin", bytes(mid2))
        os.link(a, d / "hardlink.jpg")  # same file on disk: not a real duplicate
        result = scanner.scan([str(d)])
        groups = find_duplicates(result.files, min_size=1)
        self.assertEqual(len(groups), 1)
        paths = {os.path.normcase(f.path) for f in groups[0].files}
        self.assertIn(os.path.normcase(b), paths)
        self.assertEqual(len(paths), 2)
        self.assertEqual(groups[0].wasted, 1200)

    def test_moves_never_overwrite_and_are_recorded_and_undoable(self):
        dest = self.home / "dest"
        write(dest / "report.pdf", b"existing - must survive")
        files = scanner.scan([str(self.root / "a")]).files
        ops = plan_moves(files, str(dest), {}, [])
        by_name = {os.path.basename(o.source): o for o in ops}
        self.assertEqual(by_name["report.pdf"].status, "conflict")
        self.assertEqual(by_name["movie.mp4"].status, "ready")
        batch = execute(ops, self.paths.db_path, conflict="skip")
        self.assertEqual(len(batch.done), 1)
        self.assertEqual(len(batch.skipped), 1)
        self.assertEqual((dest / "report.pdf").read_bytes(), b"existing - must survive")
        self.assertTrue((self.root / "a" / "report.pdf").exists())
        self.assertTrue((dest / "movie.mp4").exists())
        ops2 = plan_moves([f for f in files if f.path.endswith("report.pdf")], str(dest), {}, [])
        batch2 = execute(ops2, self.paths.db_path, conflict="rename")
        self.assertEqual(len(batch2.done), 1)
        self.assertEqual((dest / "report (2).pdf").read_bytes(), b"x" * 3000)
        self.assertEqual((dest / "report.pdf").read_bytes(), b"existing - must survive")
        history = OperationHistory(self.ctx.db)
        self.assertEqual([b.done for b in history.batches()], [1, 1])
        restored, problems = history.undo_batch(batch.batch_id)
        self.assertEqual((restored, problems), (1, []))
        self.assertTrue((self.root / "a" / "deep" / "movie.mp4").exists())
        self.assertFalse((dest / "movie.mp4").exists())
        # undo never overwrites a file that reappeared at the original place
        write(self.root / "a" / "report.pdf", b"new file with the old name")
        restored, problems = history.undo_batch(batch2.batch_id)
        self.assertEqual(restored, 0)
        self.assertEqual(len(problems), 1)
        self.assertEqual((self.root / "a" / "report.pdf").read_bytes(), b"new file with the old name")

    def test_changed_missing_and_protected_files_are_skipped(self):
        files = scanner.scan([str(self.root / "a")]).files
        pdf = next(f for f in files if f.path.endswith(".pdf"))
        mp4 = next(f for f in files if f.path.endswith(".mp4"))
        write(pdf.path, b"changed after the scan")
        ops = plan_moves([pdf, mp4], str(self.home / "dest"), {}, [str(self.root / "a" / "deep")])
        self.assertEqual({os.path.basename(o.source): o.status for o in ops},
                         {"report.pdf": "ready", "movie.mp4": "blocked"})
        batch = execute(ops, self.paths.db_path)
        self.assertEqual(batch.done, [])
        self.assertIn("changed since the scan", batch.skipped[0][1])
        windows = scanner.FileInfo(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "notepad.exe"), 1, 0,
                                   "other")
        self.assertEqual(plan_recycle([windows], {})[0].status, "blocked")
        self.assertEqual(plan_moves([windows], str(self.home), {})[0].status, "blocked")

    def test_cross_drive_move_is_verified(self):
        scratch = tempfile.mkdtemp(prefix="dayos-fp-")
        try:
            src = write(self.root / "cross.bin", os.urandom(200_000))
            target = os.path.join(scratch, "cross.bin")
            data = Path(src).read_bytes()
            move_file(src, target)
            self.assertFalse(os.path.exists(src))
            self.assertEqual(Path(target).read_bytes(), data)
            self.assertEqual([n for n in os.listdir(scratch) if n.endswith(".dayos-part")], [])
            with self.assertRaises(FileExistsError):
                move_file(write(self.root / "again.bin", b"x"), target)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_recycle_uses_the_recycle_bin_helper_only(self):
        f = scanner.scan([str(self.root / "Downloads")]).files[0]
        ops = plan_recycle([f], {f.path: "Old download"})
        with mock.patch("src.modules.filepilot.win32fs.recycle", return_value=(True, "Sent")) as recycle, \
                mock.patch("src.modules.filepilot.win32fs.can_recycle", return_value=True):
            ops = plan_recycle([f], {f.path: "Old download"})
            batch = execute(ops, self.paths.db_path)
        recycle.assert_called_once_with(f.path)
        self.assertEqual(batch.done, [f.path])
        row = self.ctx.db.query_one("SELECT action, reason, status FROM fp_operations")
        self.assertEqual(tuple(row), ("recycle", "Old download", "done"))


class FilePilotUiTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow
        from src.ui.theme import theme

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.ctx.settings.set("capture.global", False)
        self.window = MainWindow(self.ctx)
        self.window.show()
        self.window.navigate("filepilot")
        self.page = self.window.page("filepilot")
        self.root = self.home / "scan"
        write(self.root / "one" / "a.jpg", b"dup" * 30_000, age_days=3)
        write(self.root / "two" / "b.jpg", b"dup" * 30_000, age_days=1)
        write(self.root / "big.iso", b"i" * 2_000_000)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        pump(20)
        super().tearDown()

    def wait_idle(self, timeout=15.0):
        end = time.time() + timeout
        while self.page.busy and time.time() < end:
            pump(30)
        self.assertFalse(self.page.busy)

    def test_scan_review_move_and_undo(self):
        from src.modules.filepilot.ui.preview import PreviewDialog

        self.assertFalse(self.page.tabs.isVisibleTo(self.page))  # never scans by itself
        self.page.add_root(str(self.root))
        self.ctx.settings.set("filepilot.large_mb", 1)
        self.page.refresh()
        self.page.start_scan()
        self.wait_idle()
        self.assertTrue(self.page.tabs.isVisibleTo(self.page))
        self.assertEqual(self.page.large.table.rowCount(), 1)
        self.assertEqual(len(self.page.duplicates), 1)
        self.page.dups.select_extra("newest")
        files, reasons, whole = self.page.dups.checked()
        self.assertEqual([os.path.basename(f.path) for f in files], ["a.jpg"])
        self.assertIn("Same content", reasons[files[0].path])
        dest = self.home / "archive"
        dest.mkdir()
        with mock.patch.object(PreviewDialog, "exec", return_value=1):
            self.page.move_files(files, reasons, str(dest))
        self.wait_idle()
        self.assertTrue((dest / "a.jpg").exists())
        self.assertFalse((self.root / "one" / "a.jpg").exists())
        self.assertEqual(self.page.duplicates, [])
        batch = OperationHistory(self.ctx.db).batches()[0]
        with mock.patch("src.modules.filepilot.ui.page.confirm", return_value=True):
            self.page.undo(batch.batch_id)
        self.assertTrue((self.root / "one" / "a.jpg").exists())

    def test_every_copy_cannot_be_ticked_and_cancel_is_safe(self):
        self.page.add_root(str(self.root))
        self.page.start_scan()
        self.wait_idle()
        top = self.page.dups.tree.topLevelItem(0)
        for c in range(top.childCount()):
            top.child(c).setCheckState(0, Qt.CheckState.Checked)
        files, _reasons, whole = self.page.dups.checked()
        self.assertEqual((files, len(whole)), ([], 1))
        self.assertFalse(self.page.dups.recycle_btn.isEnabled())
        with mock.patch("src.modules.filepilot.ui.page.show_error") as err:
            self.page.dups._act("recycle")
            err.assert_called_once()
        self.page.start_scan()
        self.page.cancel()
        self.wait_idle()
        self.assertTrue((self.root / "big.iso").exists())


if __name__ == "__main__":
    unittest.main()
