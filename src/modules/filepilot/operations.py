"""Planned, previewed and recorded file operations: move and send to Recycle Bin.

Nothing happens automatically. The UI builds a plan, shows every operation with
its exact path, size and reason, and runs it only after the user confirms.
Rules enforced here, whatever the UI does:

* Nothing is ever overwritten: a destination conflict is skipped or the file is
  given a new name ("name (2).ext"), as the user chose in the preview.
* Files that changed since the scan, protected files and missing files are skipped.
* Moves are verified (size, and content for moves across drives) before the
  original is removed; results are recorded one by one, so the history is
  complete even if DayOS is closed mid-way.
* There is no permanent delete. Recycled files can be restored from the
  Recycle Bin; moves can be undone from the history.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from src.database import open_connection
from src.services.dates import now_stamp

from . import win32fs
from .scanner import FileInfo, is_protected, is_within

MTIME_TOLERANCE = 2.0


@dataclass
class PlannedOp:
    action: str  # move / recycle
    source: str
    size: int
    mtime: float
    reason: str
    destination: str = ""
    status: str = "ready"  # ready / conflict / blocked
    note: str = ""


@dataclass
class OpProgress:
    done: int = 0
    total: int = 0
    current: str = ""


@dataclass
class BatchResult:
    batch_id: str
    done: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


def unique_name(folder: str, name: str, taken: set[str] | None = None) -> str:
    stem, ext = os.path.splitext(name)
    candidate = os.path.join(folder, name)
    n = 2
    taken = taken or set()
    while os.path.lexists(candidate) or os.path.normcase(candidate) in taken:
        candidate = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return candidate


def plan_moves(files: list[FileInfo], destination: str, reasons: dict[str, str],
               protected_extra: list[str] | None = None) -> list[PlannedOp]:
    destination = os.path.abspath(destination)
    ops: list[PlannedOp] = []
    planned: set[str] = set()
    for f in files:
        op = PlannedOp("move", f.path, f.size, f.mtime, reasons.get(f.path, "Chosen by you"))
        target = os.path.join(destination, f.name)
        op.destination = target
        why = is_protected(f.path, protected_extra)
        if why:
            op.status, op.note = "blocked", f"Not moved: {why}."
        elif not os.path.lexists(f.path):
            op.status, op.note = "blocked", "The file no longer exists."
        elif is_within(destination, f.path):
            op.status, op.note = "blocked", "The destination is inside the file's own path."
        elif os.path.normcase(os.path.dirname(f.path)) == os.path.normcase(destination):
            op.status, op.note = "blocked", "It is already in that folder."
        elif is_protected(os.path.join(destination, "x"), protected_extra):
            op.status, op.note = "blocked", "That destination is a protected folder."
        elif os.path.lexists(target) or os.path.normcase(target) in planned:
            op.status = "conflict"
            op.note = f"“{f.name}” already exists there."
        planned.add(os.path.normcase(target))
        ops.append(op)
    return ops


def plan_recycle(files: list[FileInfo], reasons: dict[str, str],
                 protected_extra: list[str] | None = None) -> list[PlannedOp]:
    ops: list[PlannedOp] = []
    for f in files:
        op = PlannedOp("recycle", f.path, f.size, f.mtime, reasons.get(f.path, "Chosen by you"))
        why = is_protected(f.path, protected_extra)
        if why:
            op.status, op.note = "blocked", f"Not recycled: {why}."
        elif not os.path.lexists(f.path):
            op.status, op.note = "blocked", "The file no longer exists."
        elif not win32fs.can_recycle(f.path):
            op.status, op.note = "blocked", "This drive has no Recycle Bin. Move the file instead."
        ops.append(op)
    return ops


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _same_volume(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def move_file(source: str, target: str) -> None:
    """Move without ever overwriting; verified before the original is removed. Raises OSError."""
    if os.path.lexists(target):
        raise FileExistsError(f"“{os.path.basename(target)}” already exists in the destination.")
    size = os.path.getsize(source)
    folder = os.path.dirname(target)
    if _same_volume(source, folder):
        os.rename(source, target)  # on Windows this fails rather than replacing an existing file
        if not os.path.exists(target) or os.path.getsize(target) != size or os.path.lexists(source):
            raise OSError("The move could not be verified.")
        return
    part = unique_name(folder, os.path.basename(target) + ".dayos-part")
    try:
        shutil.copy2(source, part)
        if os.path.getsize(part) != size or _sha256(part) != _sha256(source):
            raise OSError("The copy didn't match the original, so the original was left in place.")
        if os.path.lexists(target):
            raise FileExistsError(f"“{os.path.basename(target)}” appeared in the destination meanwhile.")
        os.rename(part, target)
    except BaseException:
        if os.path.lexists(part):
            os.remove(part)  # only ever our own partial copy
        raise
    os.remove(source)


def _record(conn, batch_id: str, action: str, source: str, destination: str, size: int, reason: str, status: str,
            message: str) -> None:
    conn.execute(
        "INSERT INTO fp_operations (batch_id, action, source, destination, size, reason, status, message, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (batch_id, action, source, destination, int(size), reason[:300], status, message[:500], now_stamp()))


def execute(ops: list[PlannedOp], db_path: str | Path, conflict: str = "skip",
            cancel: threading.Event | None = None, progress: OpProgress | None = None) -> BatchResult:
    """Run confirmed operations (on a worker thread; uses its own database connection).

    ``conflict``: "skip" leaves conflicting files alone; "rename" keeps both by giving the
    moved file a new name. Blocked operations are never run.
    """
    if conflict not in ("skip", "rename"):
        raise ValueError(conflict)
    cancel = cancel or threading.Event()
    progress = progress or OpProgress()
    runnable = [op for op in ops if op.status in ("ready", "conflict")]
    progress.total = len(runnable)
    batch = BatchResult(uuid.uuid4().hex[:12])
    conn = open_connection(db_path)
    try:
        for op in runnable:
            progress.current = op.source
            if cancel.is_set():
                batch.cancelled = True
                batch.skipped.append((op.source, "cancelled"))
                continue
            status, message, final = _run_one(op, conflict)
            if status == "done":
                batch.done.append(op.source)
            elif status == "skipped":
                batch.skipped.append((op.source, message))
            else:
                batch.failed.append((op.source, message))
            _record(conn, batch.batch_id, op.action, op.source, final, op.size, op.reason, status, message)
            progress.done += 1
    finally:
        conn.close()
        progress.current = ""
    return batch


def _run_one(op: PlannedOp, conflict: str) -> tuple[str, str, str]:
    try:
        st = os.stat(op.source)
    except OSError:
        return "skipped", "The file no longer exists.", op.destination
    if st.st_size != op.size or abs(st.st_mtime - op.mtime) > MTIME_TOLERANCE:
        return "skipped", "The file changed since the scan; scan again to review it.", op.destination
    if op.action == "recycle":
        ok, message = win32fs.recycle(op.source)
        return ("done" if ok else "failed"), message, ""
    target = op.destination
    if os.path.lexists(target):
        if conflict == "skip":
            return "skipped", "A file with that name already exists in the destination.", target
        target = unique_name(os.path.dirname(target), os.path.basename(target))
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        move_file(op.source, target)
    except OSError as exc:
        return "failed", str(exc.strerror or exc), target
    return "done", "Moved and verified", target


# -- history and undo ---------------------------------------------------------------------
@dataclass
class HistoryBatch:
    batch_id: str
    created_at: str
    action: str
    done: int
    skipped: int
    failed: int
    undone: int
    bytes: int

    @property
    def can_undo(self) -> bool:
        return self.action == "move" and self.done > 0


class OperationHistory:
    def __init__(self, db) -> None:
        self.db = db

    def batches(self, limit: int = 100) -> list[HistoryBatch]:
        rows = self.db.query(
            "SELECT batch_id, MIN(created_at) AS created_at, MIN(action) AS action, "
            "SUM(status = 'done') AS done, SUM(status = 'skipped') AS skipped, SUM(status = 'failed') AS failed, "
            "SUM(status = 'undone') AS undone, SUM(CASE WHEN status IN ('done', 'undone') THEN size ELSE 0 END) AS bytes "
            "FROM fp_operations WHERE action != 'undo_move' GROUP BY batch_id ORDER BY created_at DESC, batch_id "
            "LIMIT ?", (limit,))
        return [HistoryBatch(r["batch_id"], r["created_at"], r["action"], int(r["done"] or 0),
                             int(r["skipped"] or 0), int(r["failed"] or 0), int(r["undone"] or 0),
                             int(r["bytes"] or 0)) for r in rows]

    def operations(self, batch_id: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM fp_operations WHERE batch_id = ? ORDER BY id", (batch_id,))]

    def undo_batch(self, batch_id: str) -> tuple[int, list[tuple[str, str]]]:
        """Move files from a move batch back where they came from (never overwriting)."""
        restored = 0
        problems: list[tuple[str, str]] = []
        undo_id = f"undo-{batch_id}"[:40]
        for op in self.operations(batch_id):
            if op["action"] != "move" or op["status"] != "done":
                continue
            src, dst = op["source"], op["destination"]
            if not os.path.lexists(dst):
                problems.append((dst, "it is no longer in the destination"))
                continue
            if os.path.lexists(src):
                problems.append((src, "a file with the original name is back in the original folder"))
                continue
            if os.path.getsize(dst) != int(op["size"]):
                problems.append((dst, "it has changed since it was moved"))
                continue
            try:
                os.makedirs(os.path.dirname(src), exist_ok=True)
                move_file(dst, src)
            except OSError as exc:
                problems.append((dst, str(exc.strerror or exc)))
                continue
            with self.db.transaction():
                self.db.execute("UPDATE fp_operations SET status = 'undone' WHERE id = ?", (op["id"],))
                _record(self.db, undo_id, "undo_move", dst, src, int(op["size"]), "Undo", "done", "Moved back")
            restored += 1
        return restored, problems

    def record_scan(self, roots: list[str], started: str, finished: str, files: int, total: int, errors: int,
                    cancelled: bool) -> None:
        import json

        with self.db.transaction():
            self.db.execute(
                "INSERT INTO fp_scans (roots, started_at, finished_at, files, bytes, errors, cancelled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (json.dumps(roots), started, finished, files, total, errors,
                                                 int(cancelled)))

    def last_scan(self) -> dict | None:
        row = self.db.query_one("SELECT * FROM fp_scans ORDER BY id DESC LIMIT 1")
        return dict(row) if row else None
