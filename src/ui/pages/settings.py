from __future__ import annotations

import logging
import platform
from datetime import datetime
from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.services import startup
from src.services.backup import BackupError, create_backup, inspect_backup, list_backups, restore_backup
from src.services.dates import DATE_FORMATS, WEEKDAY_NAMES
from src.services.transfer import TransferError, export_csv, export_json, import_json, load_export
from src.ui.bus import bus
from src.ui.main_window import SHORTCUTS
from src.ui.pages.base import Page
from src.ui.theme import theme
from src.ui.widgets.common import (
    Card,
    PageHeader,
    ResponsiveGrid,
    SegmentBar,
    button,
    clear_layout,
    confirm,
    label,
    scroll_wrap,
    show_error,
    show_info,
)
from src.ui.worker import run_in_background
from src.version import APP_NAME, APP_VERSION, ORGANIZATION

log = logging.getLogger(__name__)


def _size(num: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "bytes" else f"{num:.1f} {unit}"
        num /= 1024
    return str(num)


class SettingsPage(Page):
    domains = ("settings",)
    title = "Settings"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self._loading = False
        self.root.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(34, 28, 34, 28)
        outer.setSpacing(16)
        outer.addWidget(PageHeader("Settings", "Preferences are saved instantly. Your data stays on this computer.", eyebrow="Make it yours"))
        grid = ResponsiveGrid((820, 1700))
        outer.addWidget(grid)
        outer.addStretch(1)
        self.root.addWidget(scroll_wrap(content))
        s = ctx.settings

        # appearance
        card = Card("Appearance", "sun")
        form = self._form(card)
        self.theme_seg = SegmentBar([("system", "System"), ("light", "Light"), ("dark", "Dark")], s.get("theme"))
        self.theme_seg.changed.connect(lambda v: self._set("theme", v))
        form.addRow("Theme", self.theme_seg)
        self.name = QLineEdit(s.get("user_name"))
        self.name.setPlaceholderText("Optional — used in the greeting")
        self.name.setMaxLength(40)
        self.name.editingFinished.connect(lambda: self._set("user_name", self.name.text().strip()))
        form.addRow("Your name", self.name)
        self.show_clock = QCheckBox("Show a clock on the Today page")
        self.show_clock.toggled.connect(lambda v: self._set("show_clock", v))
        form.addRow("", self.show_clock)
        self.reduce_motion = QCheckBox("Reduce motion (no fades or sliding)")
        self.reduce_motion.toggled.connect(lambda v: self._set("reduce_motion", v))
        form.addRow("", self.reduce_motion)
        if theme.system_reduced_motion:
            form.addRow("", label("Windows animations are off, so DayOS already keeps motion to a minimum.", "caption", wrap=True))
        grid.add(card)

        # date & time
        card = Card("Date & time", "calendar")
        form = self._form(card)
        self.week_start_box = QComboBox()
        self.week_start_box.addItems(WEEKDAY_NAMES)
        self.week_start_box.currentIndexChanged.connect(lambda i: self._set("week_start", i))
        form.addRow("Week starts on", self.week_start_box)
        self.clock_seg = SegmentBar([("24", "24-hour"), ("12", "12-hour")], "24" if s.get("clock_24h") else "12")
        self.clock_seg.changed.connect(lambda v: self._set("clock_24h", v == "24"))
        form.addRow("Clock", self.clock_seg)
        self.date_fmt = QComboBox()
        for key, example in DATE_FORMATS.items():
            self.date_fmt.addItem(example, key)
        self.date_fmt.currentIndexChanged.connect(lambda _: self._set("date_format", self.date_fmt.currentData()))
        form.addRow("Date format", self.date_fmt)
        grid.add(card)

        # study
        card = Card("Focus timer", "study")
        form = self._form(card)
        self.spins: dict[str, QSpinBox] = {}
        for key, text, hi in (("study.focus_minutes", "Focus length", 240), ("study.short_break", "Short break", 60),
                              ("study.long_break", "Long break", 120)):
            spin = QSpinBox()
            spin.setRange(1, hi)
            spin.setSuffix(" min")
            spin.valueChanged.connect(lambda v, k=key: self._set(k, v))
            self.spins[key] = spin
            form.addRow(text, spin)
        self.notify = QCheckBox("Show a Windows notification when a timer finishes")
        self.notify.toggled.connect(lambda v: self._set("notify_desktop", v))
        form.addRow("", self.notify)
        form.addRow("", label("DayOS never plays sounds. The taskbar button flashes briefly when a timer ends.", "caption", wrap=True))
        grid.add(card)

        # startup
        card = Card("Startup", "today")
        form = self._form(card)
        self.launch = QCheckBox("Open DayOS when I sign in to Windows")
        self.launch.setEnabled(startup.is_supported())
        self.launch.toggled.connect(self._toggle_launch)
        form.addRow("", self.launch)
        form.addRow("", label("Off by default. This adds or removes a single entry for your Windows account only "
                              "(no administrator rights).", "caption", wrap=True))
        grid.add(card)

        # backups
        self.backup_card = Card("Backups", "database")
        body = self.backup_card.body
        body.addWidget(label(f"Database: {ctx.paths.db_path}", "caption", wrap=True, selectable=True))
        body.addWidget(label(f"Backups folder: {ctx.paths.backups_dir}", "caption", wrap=True, selectable=True))
        row = QHBoxLayout()
        self.backup_btn = button("Back up now", "primary", "download", self._backup_now)
        row.addWidget(self.backup_btn)
        row.addWidget(button("Restore…", "", "upload", self._restore_pick))
        row.addWidget(button("Open folder", "ghost", "folder", lambda: self._open(ctx.paths.backups_dir)))
        row.addStretch(1)
        body.addLayout(row)
        self.backup_list = QVBoxLayout()
        body.addLayout(self.backup_list)
        row = QHBoxLayout()
        row.addWidget(button("Check database health", "ghost", "check", self._integrity))
        row.addStretch(1)
        body.addLayout(row)
        body.addWidget(label("Backups are never deleted automatically. Restoring first saves a copy of your current data.",
                             "caption", wrap=True))
        grid.add(self.backup_card)

        # export / import
        card = Card("Export & import", "folder")
        body = card.body
        body.addWidget(label("Take your data anywhere. JSON exports contain everything and can be imported back; "
                             "CSV files open in any spreadsheet app.", "muted", wrap=True))
        row = QHBoxLayout()
        self.json_btn = button("Export JSON…", "", "download", self._export_json)
        self.csv_btn = button("Export CSV…", "", "download", self._export_csv)
        row.addWidget(self.json_btn)
        row.addWidget(self.csv_btn)
        row.addStretch(1)
        body.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("Import JSON export…", "ghost", "upload", self._import_json))
        row.addStretch(1)
        body.addLayout(row)
        body.addWidget(label("Importing replaces all current data with the file's contents (a backup is made first).",
                             "caption", wrap=True))
        grid.add(card)

        # shortcuts
        card = Card("Keyboard shortcuts", "keyboard")
        form = self._form(card)
        for keys, desc in SHORTCUTS:
            k = label(keys, "muted")
            form.addRow(k, label(desc, "", wrap=True))
        grid.add(card)

        # about
        card = Card("About", "info")
        body = card.body
        body.addWidget(label(f"{APP_NAME} {APP_VERSION}", "section"))
        body.addWidget(label(f"Made by {ORGANIZATION}. Local-first: no accounts, no cloud, no telemetry.", "muted", wrap=True))
        body.addWidget(label(f"Python {platform.python_version()} · Qt for Python {PYSIDE_VERSION} · "
                             f"SQLite schema v{ctx.db.user_version}", "caption", wrap=True))
        body.addWidget(label(f"Data folder: {ctx.paths.home}", "caption", wrap=True, selectable=True))
        row = QHBoxLayout()
        row.addWidget(button("Open logs folder", "ghost", "folder", lambda: self._open(ctx.paths.logs_dir)))
        row.addWidget(button("Reset settings…", "ghost", "reset", self._reset_settings))
        row.addStretch(1)
        body.addLayout(row)
        body.addWidget(label("Resetting settings restores default preferences only. Your tasks, notes and other "
                             "data are not touched.", "caption", wrap=True))
        grid.add(card)

    @staticmethod
    def _form(card: Card) -> QFormLayout:
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        card.body.addLayout(form)
        return form

    # -- load/save ------------------------------------------------------------------
    def refresh(self) -> None:
        s = self.ctx.settings
        self._loading = True
        try:
            self.theme_seg.set_current(s.get("theme"))
            self.name.setText(s.get("user_name"))
            self.show_clock.setChecked(bool(s.get("show_clock")))
            self.reduce_motion.setChecked(bool(s.get("reduce_motion")))
            self.week_start_box.setCurrentIndex(int(s.get("week_start")))
            self.clock_seg.set_current("24" if s.get("clock_24h") else "12")
            self.date_fmt.setCurrentIndex(max(0, self.date_fmt.findData(s.get("date_format"))))
            for key, spin in self.spins.items():
                spin.setValue(int(s.get(key)))
            self.notify.setChecked(bool(s.get("notify_desktop")))
            self.launch.setChecked(startup.is_enabled())
        finally:
            self._loading = False
        self._fill_backups()

    def _set(self, key: str, value) -> None:
        if self._loading or self.ctx.settings.get(key) == value:
            return
        try:
            self.ctx.settings.set(key, value)
        except (ValueError, KeyError) as exc:
            show_error(self, "Invalid setting", str(exc))
            return
        if key != "theme":
            self._own_change = True
            bus.notify("settings")

    def _on_data_changed(self, domain: str) -> None:
        if getattr(self, "_own_change", False) and domain == "settings":
            self._own_change = False
            return
        super()._on_data_changed(domain)

    def _toggle_launch(self, on: bool) -> None:
        if self._loading:
            return
        try:
            startup.set_enabled(on)
            self.ctx.settings.set("launch_at_login", on)
        except OSError as exc:
            log.exception("Could not change launch at login")
            show_error(self, "Couldn't change startup setting", str(exc))
            self._loading = True
            self.launch.setChecked(startup.is_enabled())
            self._loading = False
            return
        self.toast("DayOS will open when you sign in" if on else "DayOS won't open at sign-in")

    # -- backups ------------------------------------------------------------------------
    def _fill_backups(self) -> None:
        clear_layout(self.backup_list)
        backups = list_backups(self.ctx.paths.backups_dir)
        if not backups:
            self.backup_list.addWidget(label("No backups yet.", "muted"))
            return
        self.backup_list.addWidget(label(f"{len(backups)} backup(s) · most recent:", "caption"))
        for path in backups[:5]:
            row = QHBoxLayout()
            stat = path.stat()
            when = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            row.addWidget(label(f"{when}  ·  {_size(stat.st_size)}  ·  {path.name}", "caption"), 1)
            row.addWidget(button("Restore", "link", on_click=lambda p=path: self._restore(p)))
            self.backup_list.addLayout(row)

    def _backup_now(self) -> None:
        self.backup_btn.setEnabled(False)
        self.backup_btn.setText("Backing up…")
        db_path, folder = self.ctx.paths.db_path, self.ctx.paths.backups_dir

        def done(path: Path) -> None:
            self.backup_btn.setEnabled(True)
            self.backup_btn.setText("Back up now")
            self._fill_backups()
            self.toast(f"Backup saved: {path.name}", "Open folder", lambda: self._open(folder))

        def failed(exc: Exception) -> None:
            self.backup_btn.setEnabled(True)
            self.backup_btn.setText("Back up now")
            show_error(self, "Backup failed", str(exc))

        run_in_background(lambda: create_backup(db_path, folder, label="manual"), done, failed)

    def _restore_pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a DayOS backup", str(self.ctx.paths.backups_dir),
                                              "DayOS backups (*.db);;All files (*)")
        if path:
            self._restore(Path(path))

    def _restore(self, path: Path) -> None:
        try:
            info = inspect_backup(path)
        except BackupError as exc:
            show_error(self, "Can't restore this file", str(exc))
            return
        counts = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in info.counts.items() if v) or "no records"
        if not confirm(self, "Replace your data with this backup?",
                       f"{path.name}\nSaved {info.modified:%Y-%m-%d %H:%M} · contains {counts}.\n\n"
                       "Everything in DayOS will be replaced by this backup. Your current data is backed up first.",
                       "Restore backup"):
            return
        if not self._flush_pages():
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            safety = restore_backup(self.ctx.db, path, self.ctx.paths.backups_dir)
        except BackupError as exc:
            QGuiApplication.restoreOverrideCursor()
            show_error(self, "Restore failed", str(exc))
            return
        QGuiApplication.restoreOverrideCursor()
        self._after_data_replaced()
        show_info(self, "Backup restored", f"Your data was restored from {path.name}.",
                  f"Your previous data was saved as {safety.name}.")

    def _flush_pages(self) -> bool:
        return all(page.can_leave() for page in self.main.pages.values() if page is not self)

    def _after_data_replaced(self) -> None:
        self.ctx.settings.reload()
        theme.apply(self.ctx.settings.get("theme"))
        notes = self.main.pages.get("notes")
        if notes is not None and hasattr(notes, "_open"):
            notes.current = None  # type: ignore[attr-defined]
            notes._dirty_edit = False  # type: ignore[attr-defined]
            notes._open(None)  # type: ignore[attr-defined]
        bus.notify("all")

    def _integrity(self) -> None:
        problems = self.ctx.db.integrity_check()
        if problems:
            show_error(self, "Problems found", "The database reported:\n" + "\n".join(problems[:10]),
                       "Restore a recent backup from this page if data looks wrong.")
        else:
            show_info(self, "Database is healthy", "SQLite's integrity and foreign-key checks found no problems.")

    # -- export/import --------------------------------------------------------------------
    def _export_json(self) -> None:
        default = self.ctx.paths.exports_dir / f"dayos-export-{datetime.now():%Y%m%d-%H%M%S}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export DayOS data", str(default), "JSON (*.json)")
        if not path:
            return
        self.json_btn.setEnabled(False)
        db_path = self.ctx.paths.db_path

        def done(p: Path) -> None:
            self.json_btn.setEnabled(True)
            self.toast(f"Exported to {p.name}", "Open folder", lambda: self._open(p.parent))

        def failed(exc: Exception) -> None:
            self.json_btn.setEnabled(True)
            show_error(self, "Export failed", str(exc))

        run_in_background(lambda: export_json(db_path, Path(path)), done, failed)

    def _export_csv(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the CSV files", str(self.ctx.paths.exports_dir))
        if not folder:
            return
        self.csv_btn.setEnabled(False)
        db_path = self.ctx.paths.db_path

        def done(p: Path) -> None:
            self.csv_btn.setEnabled(True)
            self.toast(f"CSV files saved in {p.name}", "Open folder", lambda: self._open(p))

        def failed(exc: Exception) -> None:
            self.csv_btn.setEnabled(True)
            show_error(self, "Export failed", str(exc))

        run_in_background(lambda: export_csv(db_path, Path(folder)), done, failed)

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a DayOS JSON export", str(self.ctx.paths.exports_dir),
                                              "JSON (*.json);;All files (*)")
        if not path:
            return
        try:
            payload = load_export(Path(path))
        except TransferError as exc:
            show_error(self, "Can't import this file", str(exc))
            return
        counts = {k: len(v) for k, v in payload["tables"].items() if v and k != "settings"}
        summary = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in list(counts.items())[:8]) or "no records"
        if not confirm(self, "Replace your data with this export?",
                       f"{Path(path).name}\nExported {payload.get('exported_at', 'unknown')} · contains {summary}.\n\n"
                       "All current data will be replaced. A backup of your current data is made first.",
                       "Import and replace"):
            return
        if not self._flush_pages():
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            import_json(self.ctx.db, Path(path), self.ctx.paths.backups_dir)
        except (TransferError, BackupError) as exc:
            QGuiApplication.restoreOverrideCursor()
            show_error(self, "Import failed", str(exc), "Your data was not changed.")
            return
        QGuiApplication.restoreOverrideCursor()
        self._after_data_replaced()
        self.toast("Import complete")

    # -- misc ------------------------------------------------------------------------------
    def _reset_settings(self) -> None:
        if confirm(self, "Reset settings?", "All preferences go back to their defaults. Your data is not affected.",
                   "Reset settings", danger=False):
            self.ctx.settings.reset_preferences()
            theme.apply(self.ctx.settings.get("theme"))
            self.main.set_sidebar_collapsed(False, animate=False)
            bus.notify("settings")
            self.refresh()
            self.toast("Settings reset")

    def _open(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
