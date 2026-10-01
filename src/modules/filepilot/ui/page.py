"""FilePilot page: scan folders you choose, review what uses space, and tidy up safely.

Scanning is read-only and runs in the background with progress and Cancel.
Nothing is moved or recycled until you preview the exact operations and confirm.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.modules.filepilot import scanner
from src.modules.filepilot.duplicates import DuplicateGroup, find_duplicates
from src.modules.filepilot.operations import OperationHistory, OpProgress, execute, plan_moves, plan_recycle
from src.modules.filepilot.scanner import CATEGORY_LABELS, FileInfo, ScanProgress, ScanResult, human_size
from src.services.dates import now_stamp
from src.ui.pages.base import Page
from src.ui.widgets.charts import HBarList
from src.ui.widgets.common import (
    Card,
    EmptyState,
    FlowLayout,
    PageHeader,
    button,
    chip,
    clear_layout,
    confirm,
    label,
    scroll_wrap,
    show_error,
    show_info,
    tool_button,
)
from src.ui.worker import run_in_background

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
PATH_ROLE = Qt.ItemDataRole.UserRole
MAX_ROWS = 2000


class SortItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:  # numeric / date columns sort by their raw value
        a, b = self.data(SORT_ROLE), other.data(SORT_ROLE)
        if a is not None and b is not None:
            return a < b
        return super().__lt__(other)


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts > 0 else ""


class FileTable(QWidget):
    """A sortable list of files with checkboxes and selection-based actions."""

    def __init__(self, page: "FilePilotPage", reason_fn, empty_text: str) -> None:
        super().__init__()
        self.page = page
        self.reason_fn = reason_fn
        self.files: dict[str, FileInfo] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        self.base_hint = empty_text
        self.hint = label(empty_text, "muted", wrap=True)
        lay.addWidget(self.hint)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "Name", "Folder", "Size", "Modified", "Type"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.setAccessibleName("Files")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for col, width in enumerate((34, 240, 330, 90, 100)):
            self.table.setColumnWidth(col, width)
        self.table.itemChanged.connect(lambda _i: self._update_selection())
        self.table.itemDoubleClicked.connect(lambda item: self.page.show_in_folder(item.data(PATH_ROLE)))
        lay.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.selection = label("", "caption")
        actions.addWidget(self.selection, 1)
        actions.addWidget(button("Select all", "link", on_click=lambda: self.set_all(True)))
        actions.addWidget(button("Clear", "link", on_click=lambda: self.set_all(False)))
        actions.addWidget(button("Show in folder", "ghost", "folder", self._show_current))
        self.move_btn = button("Move selected…", "soft", "upload", lambda: self.page.move_files(self.checked(),
                                                                                                self.reasons()))
        actions.addWidget(self.move_btn)
        self.recycle_btn = button("Recycle selected…", "ghost", "trash",
                                  lambda: self.page.recycle_files(self.checked(), self.reasons()))
        actions.addWidget(self.recycle_btn)
        lay.addLayout(actions)
        self._update_selection()

    def set_files(self, files: list[FileInfo], hint: str | None = None) -> None:
        if hint is not None:
            self.base_hint = hint
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        shown = files[:MAX_ROWS]
        self.files = {f.path: f for f in shown}
        self.table.setRowCount(len(shown))
        for row, f in enumerate(shown):
            check = SortItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setData(PATH_ROLE, f.path)
            check.setData(SORT_ROLE, 0)
            check.setData(Qt.ItemDataRole.AccessibleTextRole, f"Select {f.name}")
            values = [(f.name, f.name.lower()), (f.folder, f.folder.lower()), (human_size(f.size), f.size),
                      (_when(f.mtime), f.mtime), (CATEGORY_LABELS.get(f.category, f.category)
                                                  + (" · online-only" if f.cloud else ""), f.category)]
            self.table.setItem(row, 0, check)
            for col, (text, key) in enumerate(values, start=1):
                item = SortItem(text)
                item.setData(SORT_ROLE, key)
                item.setData(PATH_ROLE, f.path)
                item.setToolTip(f.path if col in (1, 2) else text)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        extra = f" Showing the first {MAX_ROWS:,}." if len(files) > MAX_ROWS else ""
        self.hint.setText(self.base_hint + extra)
        self._update_selection()

    def checked(self) -> list[FileInfo]:
        out = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                f = self.files.get(item.data(PATH_ROLE))
                if f is not None:
                    out.append(f)
        return out

    def reasons(self) -> dict[str, str]:
        return {f.path: self.reason_fn(f) for f in self.checked()}

    def set_all(self, on: bool) -> None:
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._update_selection()

    def _update_selection(self) -> None:
        chosen = self.checked()
        self.selection.setText(f"{len(chosen)} selected · {human_size(sum(f.size for f in chosen))}"
                               if chosen else "Tick files to move or recycle them.")
        self.move_btn.setEnabled(bool(chosen))
        self.recycle_btn.setEnabled(bool(chosen))

    def _show_current(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.page.show_in_folder(self.table.item(row, 0).data(PATH_ROLE))


class DuplicatesView(QWidget):
    def __init__(self, page: "FilePilotPage") -> None:
        super().__init__()
        self.page = page
        self.groups: list[DuplicateGroup] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        self.hint = label("Files with exactly the same content (checked with SHA-256), not just the same name. "
                          "At least one copy in each group is always kept.", "muted", wrap=True)
        lay.addWidget(self.hint)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["File", "Folder", "Size", "Modified"])
        self.tree.setAccessibleName("Duplicate groups")
        self.tree.itemChanged.connect(lambda _i, _c: self._update_selection())
        self.tree.itemDoubleClicked.connect(lambda item, _c: self.page.show_in_folder(item.data(0, PATH_ROLE))
                                            if item.data(0, PATH_ROLE) else None)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 360)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.selection = label("", "caption")
        row.addWidget(self.selection, 1)
        row.addWidget(button("Keep newest, select the rest", "link", on_click=lambda: self.select_extra(keep="newest")))
        row.addWidget(button("Keep oldest, select the rest", "link", on_click=lambda: self.select_extra(keep="oldest")))
        row.addWidget(button("Clear", "link", on_click=lambda: self.select_extra(keep=None)))
        self.move_btn = button("Move selected…", "soft", "upload", lambda: self._act("move"))
        row.addWidget(self.move_btn)
        self.recycle_btn = button("Recycle selected…", "ghost", "trash", lambda: self._act("recycle"))
        row.addWidget(self.recycle_btn)
        lay.addLayout(row)
        self._update_selection()

    def set_groups(self, groups: list[DuplicateGroup]) -> None:
        self.groups = groups
        self.tree.blockSignals(True)
        self.tree.clear()
        for gi, group in enumerate(groups[:500]):
            top = QTreeWidgetItem([f"{len(group.files)} copies · {human_size(group.size)} each", "",
                                   f"{human_size(group.wasted)} extra", ""])
            top.setData(0, Qt.ItemDataRole.UserRole + 2, gi)
            top.setToolTip(0, f"SHA-256 {group.sha256}")
            for f in group.files:
                child = QTreeWidgetItem([f.name, f.folder, human_size(f.size), _when(f.mtime)])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setData(0, PATH_ROLE, f.path)
                child.setToolTip(1, f.path)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(gi < 30)
        self.tree.blockSignals(False)
        self._update_selection()

    def select_extra(self, keep: str | None) -> None:
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            group = self.groups[int(top.data(0, Qt.ItemDataRole.UserRole + 2))]
            ordered = sorted(group.files, key=lambda f: f.mtime)
            kept = None if keep is None else (ordered[-1] if keep == "newest" else ordered[0]).path
            for c in range(top.childCount()):
                child = top.child(c)
                on = keep is not None and child.data(0, PATH_ROLE) != kept
                child.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self._update_selection()

    def checked(self) -> tuple[list[FileInfo], dict[str, str], list[str]]:
        """Chosen files, their reasons, and groups where every copy is ticked (not allowed)."""
        files: list[FileInfo] = []
        reasons: dict[str, str] = {}
        whole: list[str] = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            group = self.groups[int(top.data(0, Qt.ItemDataRole.UserRole + 2))]
            by_path = {f.path: f for f in group.files}
            ticked = [top.child(c).data(0, PATH_ROLE) for c in range(top.childCount())
                      if top.child(c).checkState(0) == Qt.CheckState.Checked]
            if ticked and len(ticked) == len(group.files):
                whole.append(group.files[0].name)
                continue
            keep = next(f for f in group.files if f.path not in ticked)
            for path in ticked:
                files.append(by_path[path])
                reasons[path] = f"Same content (SHA-256) as {keep.path}"
        return files, reasons, whole

    def _update_selection(self) -> None:
        files, _reasons, whole = self.checked()
        text = (f"{len(files)} selected · frees {human_size(sum(f.size for f in files))}" if files
                else "Tick the copies you don't need.")
        if whole:
            text += f" · Untick at least one copy of: {', '.join(whole[:3])}"
        self.selection.setText(text)
        self.move_btn.setEnabled(bool(files) and not whole)
        self.recycle_btn.setEnabled(bool(files) and not whole)

    def _act(self, action: str) -> None:
        files, reasons, whole = self.checked()
        if whole:
            show_error(self, "Keep one copy", "Every copy in a group is ticked. Untick at least one copy of each "
                                              "file so one is always kept.")
            return
        if action == "move":
            self.page.move_files(files, reasons)
        else:
            self.page.recycle_files(files, reasons)


class FilePilotPage(Page):
    domains = ("files", "settings")
    title = "FilePilot"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.history = OperationHistory(ctx.db)
        self.result: ScanResult | None = None
        self.duplicates: list[DuplicateGroup] = []
        self.cancel_event: threading.Event | None = None
        self.scan_progress: ScanProgress | None = None
        self.op_progress: OpProgress | None = None
        self.busy = False
        window.shutdown_hooks.append(self.cancel)

        header = PageHeader("FilePilot", "See what uses your space, find true duplicates and tidy up. Scanning only "
                                         "reads; nothing moves until you review and confirm it.",
                            eyebrow="Files & storage")
        header.add_action(button("Add folder…", "ghost", "plus", self.add_folder))
        self.cancel_btn = button("Cancel", "ghost", "stop", self.cancel)
        self.cancel_btn.hide()
        header.add_action(self.cancel_btn)
        self.scan_btn = button("Scan", "primary", "search", self.start_scan, "Scan the chosen folders")
        header.add_action(self.scan_btn)
        self.root.addWidget(header)

        roots_card = QWidget()
        rl = QVBoxLayout(roots_card)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.roots_flow = FlowLayout()
        rl.addLayout(self.roots_flow)
        quick = QHBoxLayout()
        quick.addWidget(label("Quick add:", "caption"))
        for name in ("Downloads", "Desktop", "Documents", "Pictures", "Videos", "Music"):
            path = Path.home() / name
            if path.is_dir():
                quick.addWidget(button(name, "link", on_click=lambda p=str(path): self.add_root(p)))
        quick.addStretch(1)
        rl.addLayout(quick)
        opts = QHBoxLayout()
        self.find_dups = QCheckBox("Find duplicates")
        self.find_dups.setChecked(True)
        opts.addWidget(self.find_dups)
        self.include_hidden = QCheckBox("Include hidden files")
        self.include_hidden.toggled.connect(lambda v: self._set("filepilot.include_hidden", v))
        opts.addWidget(self.include_hidden)
        opts.addSpacing(12)
        opts.addWidget(label("Large files from", "caption"))
        self.large_mb = QSpinBox()
        self.large_mb.setRange(1, 100000)
        self.large_mb.setSuffix(" MB")
        self.large_mb.setAccessibleName("Large file size")
        self.large_mb.valueChanged.connect(lambda v: (self._set("filepilot.large_mb", int(v)), self._fill_results()))
        opts.addWidget(self.large_mb)
        opts.addWidget(label("Old downloads after", "caption"))
        self.old_days = QSpinBox()
        self.old_days.setRange(7, 3650)
        self.old_days.setSuffix(" days")
        self.old_days.setAccessibleName("Old download age")
        self.old_days.valueChanged.connect(lambda v: (self._set("filepilot.old_days", int(v)), self._fill_results()))
        opts.addWidget(self.old_days)
        opts.addStretch(1)
        rl.addLayout(opts)
        self.root.addWidget(roots_card)

        prog = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setAccessibleName("Progress")
        self.progress.hide()
        prog.addWidget(self.progress, 1)
        self.root.addLayout(prog)
        self.status = label("", "caption", wrap=True)
        self.root.addWidget(self.status)

        self.tabs = QTabWidget()
        self.overview_holder = QWidget()
        self.overview = QVBoxLayout(self.overview_holder)
        self.overview.setContentsMargins(0, 10, 6, 0)
        self.overview.setSpacing(14)
        self.tabs.addTab(scroll_wrap(self.overview_holder), "Overview")
        self.large = FileTable(self, lambda f: f"Large file ({human_size(f.size)})",
                               "The biggest files in the scanned folders, largest first.")
        self.tabs.addTab(self.large, "Large files")
        self.dups = DuplicatesView(self)
        self.tabs.addTab(self.dups, "Duplicates")
        self.old = FileTable(self, lambda f: f"In Downloads and unchanged since {_when(f.mtime)}",
                             "Files in your Downloads folder that haven't changed for a while.")
        self.tabs.addTab(self.old, "Old downloads")
        self.by_type_holder = QWidget()
        bt = QVBoxLayout(self.by_type_holder)
        bt.setContentsMargins(0, 8, 0, 0)
        self.type_bar = QHBoxLayout()
        bt.addLayout(self.type_bar)
        self.by_type = FileTable(self, lambda f: f"{CATEGORY_LABELS.get(f.category, f.category)}",
                                 "Choose a type to list its files.")
        bt.addWidget(self.by_type, 1)
        self.tabs.addTab(self.by_type_holder, "By type")
        self.folders = QTableWidget(0, 2)
        self.folders.setHorizontalHeaderLabels(["Folder", "Size (with subfolders)"])
        self.folders.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.folders.verticalHeader().setVisible(False)
        self.folders.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.folders.setSortingEnabled(True)
        self.folders.setAccessibleName("Folder sizes")
        self.folders.itemDoubleClicked.connect(lambda item: self.open_folder(item.data(PATH_ROLE)))
        self.tabs.addTab(self.folders, "Folders")
        self.history_holder = QWidget()
        self.history_box = QVBoxLayout(self.history_holder)
        self.history_box.setContentsMargins(0, 10, 6, 0)
        self.history_box.setSpacing(8)
        self.tabs.addTab(scroll_wrap(self.history_holder), "History")
        self.root.addWidget(self.tabs, 1)

        self.empty = EmptyState("file-search", "Choose folders to scan",
                                "Pick folders such as Downloads or Pictures and press Scan. FilePilot only reads "
                                "them; it never scans automatically and never changes anything on its own.",
                                [("Add folder…", self.add_folder)])
        self.root.addWidget(self.empty, 1)

        self._poll = QTimer(self)
        self._poll.setInterval(150)
        self._poll.timeout.connect(self._update_progress)

    # -- settings / roots --------------------------------------------------------------
    def _set(self, key: str, value) -> None:
        if self.ctx.settings.get(key) != value:
            self.ctx.settings.set(key, value)

    def roots(self) -> list[str]:
        return list(self.ctx.settings.get("filepilot.roots"))

    def add_root(self, path: str) -> None:
        path = os.path.abspath(path)
        roots = self.roots()
        if path not in roots:
            roots.append(path)
            self.ctx.settings.set("filepilot.roots", roots[-30:])
        self._fill_roots()

    def remove_root(self, path: str) -> None:
        self.ctx.settings.set("filepilot.roots", [r for r in self.roots() if r != path])
        self._fill_roots()

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder or drive to scan")
        if folder:
            self.add_root(folder)

    def _fill_roots(self) -> None:
        clear_layout(self.roots_flow)
        roots = self.roots()
        if not roots:
            self.roots_flow.addWidget(label("No folders chosen yet.", "muted"))
        for root in roots:
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(2)
            h.addWidget(chip(root, "" if os.path.isdir(root) else "warning"))
            h.addWidget(tool_button("close", f"Stop scanning {root}", lambda r=root: self.remove_root(r), 14))
            self.roots_flow.addWidget(box)
        self.scan_btn.setEnabled(bool(roots) and not self.busy)

    def refresh(self) -> None:
        s = self.ctx.settings
        for w, value in ((self.large_mb, int(s.get("filepilot.large_mb"))), (self.old_days, int(s.get("filepilot.old_days")))):
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)
        self.include_hidden.blockSignals(True)
        self.include_hidden.setChecked(bool(s.get("filepilot.include_hidden")))
        self.include_hidden.blockSignals(False)
        self._fill_roots()
        self._fill_history()
        has = self.result is not None
        self.tabs.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            last = self.history.last_scan()
            if last:
                self.status.setText(f"Last scan {last['finished_at'][:16]}: {last['files']:,} files, "
                                    f"{human_size(last['bytes'])}. Results aren't kept between sessions; scan again "
                                    "to review them.")

    # -- scanning ------------------------------------------------------------------------
    def start_scan(self) -> None:
        roots = [r for r in self.roots() if os.path.isdir(r)]
        if not roots:
            show_info(self, "Nothing to scan", "Add a folder that exists first.")
            return
        if self.busy:
            return
        self.cancel_event = threading.Event()
        self.scan_progress = ScanProgress()
        cancel, progress = self.cancel_event, self.scan_progress
        include_hidden = self.include_hidden.isChecked()
        want_dups = self.find_dups.isChecked()
        min_dup = int(self.ctx.settings.get("filepilot.dup_min_kb")) * 1024
        started = now_stamp()

        def work():
            result = scanner.scan(roots, cancel, progress, include_hidden=include_hidden)
            dups = [] if (result.cancelled or not want_dups) else find_duplicates(result.files, cancel, progress,
                                                                                    min_dup)
            if cancel.is_set():
                result.cancelled = True
            return result, dups

        self._set_busy(True, "Scanning…")
        run_in_background(work, lambda r: self._scan_done(r, roots, started),
                          lambda e: self._job_failed(e, "The scan stopped"))

    def _scan_done(self, value, roots: list[str], started: str) -> None:
        result, dups = value
        self._set_busy(False)
        self.result = result
        self.duplicates = dups
        try:
            self.history.record_scan(roots, started, now_stamp(), len(result.files), result.total_bytes,
                                     result.errors, result.cancelled)
        except Exception:
            pass  # the summary is a convenience; results are still shown
        took = result.finished - result.started
        text = (f"{'Stopped early — partial results: ' if result.cancelled else ''}{len(result.files):,} files, "
                f"{human_size(result.total_bytes)} in {len(result.folder_sizes):,} folders ({took:.1f} s).")
        if result.errors:
            text += f" {result.errors} item(s) couldn't be read (usually permission); see Overview."
        if result.skipped:
            text += f" {result.skipped:,} system, hidden or linked items were left out."
        self.status.setText(text)
        self._fill_results()
        self.tabs.setVisible(True)
        self.empty.setVisible(False)

    def cancel(self) -> None:
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.busy:
            self.status.setText("Stopping…")

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        self.cancel_btn.setVisible(busy)
        self.scan_btn.setEnabled(not busy and bool(self.roots()))
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)
        if busy:
            self.status.setText(text)
            self._started_at = time.monotonic()
            self._poll.start()
        else:
            self._poll.stop()
            self.cancel_event = None

    def _update_progress(self) -> None:
        sp, op = self.scan_progress, self.op_progress
        if self.busy and op is not None and op.total:
            self.progress.setRange(0, op.total)
            self.progress.setValue(op.done)
            self.status.setText(f"Working… {op.done} of {op.total} · {op.current}")
        elif self.busy and sp is not None:
            if sp.phase == "hashing" and sp.to_hash:
                self.progress.setRange(0, sp.to_hash)
                self.progress.setValue(min(sp.hashed, sp.to_hash))
                self.status.setText(f"Comparing contents of same-size files: {sp.hashed:,} of {sp.to_hash:,} · "
                                    f"{sp.current}")
            else:
                self.status.setText(f"Scanning… {sp.files:,} files, {human_size(sp.bytes)} · {sp.current}")

    def _job_failed(self, exc: Exception, title: str) -> None:
        self._set_busy(False)
        self.op_progress = None
        show_error(self, title, str(exc), "Technical details were written to the DayOS log file.")

    # -- results ---------------------------------------------------------------------------
    def _fill_results(self) -> None:
        if self.result is None:
            return
        files = self.result.files
        large_bytes = int(self.ctx.settings.get("filepilot.large_mb")) * 1024 * 1024
        self.large.set_files(scanner.largest(files, large_bytes))
        self.old.set_files(scanner.old_downloads(files, int(self.ctx.settings.get("filepilot.old_days"))))
        self.dups.set_groups(self.duplicates)
        self._fill_types()
        self._fill_folders()
        self._fill_overview()

    def _fill_types(self) -> None:
        clear_layout(self.type_bar)
        cats = scanner.by_category(self.result.files) if self.result else []
        for cat, count, size in cats:
            self.type_bar.addWidget(button(f"{CATEGORY_LABELS.get(cat, cat)} · {count:,} · {human_size(size)}", "ghost",
                                           on_click=lambda c=cat: self.show_type(c)))
        self.type_bar.addStretch(1)

    def show_type(self, category: str) -> None:
        if self.result is None:
            return
        files = sorted((f for f in self.result.files if f.category == category), key=lambda f: -f.size)
        self.by_type.set_files(files, f"{CATEGORY_LABELS.get(category, category)}: {len(files):,} files, "
                                      "largest first.")
        self.tabs.setCurrentWidget(self.by_type_holder)

    def _fill_folders(self) -> None:
        self.folders.setSortingEnabled(False)
        rows = scanner.biggest_folders(self.result) if self.result else []
        self.folders.setRowCount(len(rows))
        for i, (folder, size) in enumerate(rows):
            a = SortItem(folder)
            a.setData(PATH_ROLE, folder)
            a.setData(SORT_ROLE, folder.lower())
            b = SortItem(human_size(size))
            b.setData(SORT_ROLE, size)
            b.setData(PATH_ROLE, folder)
            self.folders.setItem(i, 0, a)
            self.folders.setItem(i, 1, b)
        self.folders.setSortingEnabled(True)
        self.folders.sortItems(1, Qt.SortOrder.DescendingOrder)

    def _fill_overview(self) -> None:
        clear_layout(self.overview)
        r = self.result
        if r is None:
            return
        top = QHBoxLayout()
        for value, caption in ((f"{len(r.files):,}", "files"), (human_size(r.total_bytes), "in total"),
                               (f"{len(self.duplicates):,}", "duplicate groups"),
                               (human_size(sum(g.wasted for g in self.duplicates)), "taken by extra copies")):
            col = QVBoxLayout()
            col.addWidget(label(value, "metric"))
            col.addWidget(label(caption, "metricLabel"))
            top.addLayout(col)
        top.addStretch(1)
        self.overview.addLayout(top)
        suggestions = Card("Worth a look", "sparkle")
        found = False
        if self.duplicates:
            found = True
            suggestions.body.addWidget(self._suggestion(
                f"{len(self.duplicates)} groups of identical files; removing extra copies would free "
                f"{human_size(sum(g.wasted for g in self.duplicates))}.", "Review duplicates", self.dups))
        old = scanner.old_downloads(r.files, int(self.ctx.settings.get("filepilot.old_days")))
        if old:
            found = True
            suggestions.body.addWidget(self._suggestion(
                f"{len(old)} old downloads use {human_size(sum(f.size for f in old))}.", "Review old downloads",
                self.old))
        installers = [f for f in r.files if f.category == "installers"]
        if installers:
            found = True
            suggestions.body.addWidget(self._suggestion(
                f"{len(installers)} installers use {human_size(sum(f.size for f in installers))}; once a program "
                "is installed you rarely need its installer.", "Show installers", None, "installers"))
        if not found:
            suggestions.body.addWidget(label("Nothing stands out. Your folders look tidy.", "muted"))
        suggestions.body.addWidget(label("These are suggestions only. Nothing is changed unless you choose files, "
                                         "review the preview and confirm.", "caption", wrap=True))
        self.overview.addWidget(suggestions)
        cats = Card("Space by type", "chart")
        bars = HBarList()
        total = max(1, r.total_bytes)
        bars.set_rows([(CATEGORY_LABELS.get(c, c), b / total, f"{human_size(b)} · {n:,} files", "accent")
                       for c, n, b in scanner.by_category(r.files)[:12]])
        cats.body.addWidget(bars)
        self.overview.addWidget(cats)
        folders = Card("Biggest folders", "folder")
        rows = [(f, s) for f, s in scanner.biggest_folders(r, 40)
                if not any(scanner.normcase(f) == scanner.normcase(root) for root in r.roots)][:10]
        if rows:
            fb = HBarList()
            biggest = max(1, rows[0][1])
            fb.set_rows([(f, s / biggest, human_size(s), "blue") for f, s in rows])
            folders.body.addWidget(fb)
        else:
            folders.body.addWidget(label("No subfolders.", "muted"))
        self.overview.addWidget(folders)
        if r.errors:
            errs = Card("Couldn't read", "alert")
            errs.body.addWidget(label(f"{r.errors} item(s) couldn't be read, usually because Windows restricts "
                                      "them. FilePilot doesn't need administrator rights and skips them.", "muted",
                                      wrap=True))
            for path, why in r.error_samples[:8]:
                errs.body.addWidget(label(f"{path} — {why}", "caption", wrap=True))
            self.overview.addWidget(errs)
        self.overview.addStretch(1)

    def _suggestion(self, text: str, action: str, target: QWidget | None, category: str = "") -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(label(text, "", wrap=True), 1)
        h.addWidget(button(action, "link", "chev-right",
                           (lambda: self.show_type(category)) if category else (lambda: self.tabs.setCurrentWidget(target))))
        return w

    # -- operations ---------------------------------------------------------------------------
    def _protected_extra(self) -> list[str]:
        paths = self.ctx.paths
        return [str(paths.data_dir), str(paths.backups_dir), str(paths.exports_dir), str(paths.logs_dir),
                str(paths.cache_dir)]

    def move_files(self, files: list[FileInfo], reasons: dict[str, str], destination: str | None = None) -> None:
        if not files or self.busy:
            return
        if destination is None:
            destination = QFileDialog.getExistingDirectory(self, "Move the selected files to…")
            if not destination:
                return
        ops = plan_moves(files, destination, reasons, self._protected_extra())
        self._preview_and_run(ops, destination)

    def recycle_files(self, files: list[FileInfo], reasons: dict[str, str]) -> None:
        if not files or self.busy:
            return
        self._preview_and_run(plan_recycle(files, reasons, self._protected_extra()))

    def _preview_and_run(self, ops, destination: str = "") -> None:
        from src.modules.filepilot.ui.preview import PreviewDialog

        dlg = PreviewDialog(ops, self, destination)
        if not dlg.exec():
            return
        self.run_operations(ops, dlg.conflict_mode)

    def run_operations(self, ops, conflict_mode: str) -> None:
        self.cancel_event = threading.Event()
        self.op_progress = OpProgress()
        cancel, progress = self.cancel_event, self.op_progress
        db_path = self.ctx.paths.db_path
        self._set_busy(True, "Working…")
        run_in_background(lambda: execute(ops, db_path, conflict_mode, cancel, progress), self._ops_done,
                          lambda e: self._job_failed(e, "The operation stopped"))

    def _ops_done(self, batch) -> None:
        self._set_busy(False)
        self.op_progress = None
        if self.result is not None and batch.done:
            gone = set(batch.done)
            self.result.files = [f for f in self.result.files if f.path not in gone]
            for group in self.duplicates:
                group.files = [f for f in group.files if f.path not in gone]
            self.duplicates = [g for g in self.duplicates if len(g.files) > 1]
            self._fill_results()
        self._fill_history()
        from src.ui.bus import bus

        bus.notify("files")
        text = f"{len(batch.done)} done"
        if batch.skipped:
            text += f", {len(batch.skipped)} skipped"
        if batch.failed:
            text += f", {len(batch.failed)} failed"
        self.status.setText(f"Finished: {text}." + (" Cancelled before the end." if batch.cancelled else ""))
        if batch.skipped or batch.failed:
            detail = "\n".join(f"{p}: {why}" for p, why in (batch.failed + batch.skipped)[:40])
            show_info(self, "Finished with some files left alone", f"{text}. Nothing was overwritten.", detail)
        else:
            self.toast(f"Finished: {text}", "History", lambda: self.tabs.setCurrentWidget(
                self.tabs.widget(self.tabs.count() - 1)))

    def _fill_history(self) -> None:
        clear_layout(self.history_box)
        batches = self.history.batches()
        if not batches:
            self.history_box.addWidget(label("No file operations yet. Everything FilePilot does is listed here.",
                                             "muted", wrap=True))
        for b in batches:
            card = Card(f"{'Moved' if b.action == 'move' else 'Sent to Recycle Bin'} · {b.created_at[:16]}",
                        "upload" if b.action == "move" else "trash")
            parts = [f"{b.done} done"] + ([f"{b.undone} undone"] if b.undone else []) + \
                    ([f"{b.skipped} skipped"] if b.skipped else []) + ([f"{b.failed} failed"] if b.failed else [])
            card.body.addWidget(label(" · ".join(parts) + f" · {human_size(b.bytes)}", "", wrap=True))
            for op in self.history.operations(b.batch_id)[:6]:
                where = f" → {op['destination']}" if op["destination"] else ""
                card.body.addWidget(label(f"{op['status']}: {op['source']}{where}", "caption", wrap=True))
            row = QHBoxLayout()
            if b.can_undo:
                row.addWidget(button("Undo (move back)", "soft", "undo", lambda bid=b.batch_id: self.undo(bid)))
            elif b.action == "recycle" and b.done:
                row.addWidget(label("To undo, restore the files from the Windows Recycle Bin.", "caption"))
            row.addStretch(1)
            card.body.addLayout(row)
            self.history_box.addWidget(card)
        self.history_box.addStretch(1)

    def undo(self, batch_id: str) -> None:
        if not confirm(self, "Move the files back?", "Files from this batch will be moved back to where they were. "
                                                    "Nothing is overwritten.", "Move back", danger=False):
            return
        try:
            restored, problems = self.history.undo_batch(batch_id)
        except Exception as exc:
            show_error(self, "Undo stopped", str(exc))
            return
        self._fill_history()
        if problems:
            show_info(self, "Undo finished", f"{restored} file(s) moved back. Some were left alone.",
                      "\n".join(f"{p}: {why}" for p, why in problems[:40]))
        else:
            self.toast(f"Moved {restored} file{'s' if restored != 1 else ''} back")
        if self.result is not None and restored:
            self.status.setText("Some files moved back. Scan again to refresh the results.")

    # -- explorer -------------------------------------------------------------------------
    def show_in_folder(self, path: str | None) -> None:
        if path and os.path.exists(path):
            QProcess.startDetached("explorer.exe", [f"/select,{os.path.normpath(path)}"])

    def open_folder(self, path: str | None) -> None:
        if path and os.path.isdir(path):
            QProcess.startDetached("explorer.exe", [os.path.normpath(path)])

    def can_leave(self) -> bool:
        return True
