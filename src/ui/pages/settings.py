"""Settings: appearance (five themes), profile & layout, general preferences, data and more.

Sections are listed on the left and built the first time they are opened.
Feature modules add their own sections through :mod:`src.ui.settings_sections`.
Every change is saved instantly; nothing here ever modifies user records.
"""

from __future__ import annotations

import logging
import platform
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.modules import registry
from src.modules.profiles import PROFILES, WIDGETS, get_profile
from src.services import startup
from src.services.backup import BackupError, create_backup, inspect_backup, list_backups, restore_backup
from src.services.dates import DATE_FORMATS, WEEKDAY_NAMES
from src.services.transfer import TransferError, export_csv, export_json, import_json, load_export
from src.ui import settings_sections
from src.ui.bus import bus
from src.ui.main_window import SHORTCUTS, visible_module_keys
from src.ui.pages.base import Page
from src.ui.theme import FONT_SCALES, theme
from src.ui.theme_settings import accent_for, apply_from_settings, set_accent
from src.ui.themes import SYSTEM_PAIR, THEMES
from src.ui.widgets.common import (
    Card,
    PageHeader,
    SegmentBar,
    TimeEdit,
    button,
    clear_layout,
    confirm,
    label,
    scroll_wrap,
    show_error,
    show_info,
)
from src.ui.widgets.nav import NavItem, NavList
from src.ui.widgets.theme_preview import AccentSwatch, ThemePreviewCard
from src.ui.worker import run_in_background
from src.version import APP_NAME, APP_VERSION, ORGANIZATION

log = logging.getLogger(__name__)


def _size(num: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "bytes" else f"{num:.1f} {unit}"
        num /= 1024
    return str(num)


def form_layout(parent_layout) -> QFormLayout:
    form = QFormLayout()
    form.setSpacing(10)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    parent_layout.addLayout(form)
    return form


class SettingsPage(Page):
    domains = ("settings",)
    title = "Settings"

    BUILT_IN = [
        ("appearance", "Appearance", "sparkle"),
        ("profile", "Profile & layout", "grid"),
        ("general", "General", "settings"),
        ("focus", "Focus, reminders & capture", "bell"),
        ("data", "Data & backups", "database"),
        ("shortcuts", "Keyboard shortcuts", "keyboard"),
        ("about", "About", "info"),
    ]

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self._loading = False
        self._refreshers: list[Callable[[], None]] = []
        self.root.setContentsMargins(34, 28, 34, 0)
        self.root.setSpacing(14)
        self.root.addWidget(PageHeader("Settings", "Preferences are saved instantly. Your data stays on this computer.",
                                       eyebrow="Make it yours"))
        body = QHBoxLayout()
        body.setSpacing(22)
        self.root.addLayout(body, 1)

        self.section_nav = NavList()
        self.section_nav.setFixedWidth(220)
        self.section_buttons: dict[str, NavItem] = {}
        self.section_group = QButtonGroup(self)
        self.section_group.setExclusive(True)
        self.stack = QStackedWidget()
        self._builders: dict[str, Callable[[], QWidget]] = {}
        self._built: dict[str, QWidget] = {}
        sections = [(k, t, i, getattr(self, f"_build_{k}")) for k, t, i in self.BUILT_IN]
        extra = [(s.key, s.title, s.icon, (lambda spec=s: spec.builder(self))) for s in settings_sections.SECTIONS]
        # registered sections slot in before "Data & backups"
        ordered = sections[:4] + extra + sections[4:]
        for key, title, icon, builder in ordered:
            item = NavItem(title, icon)
            item.clicked.connect(lambda _=False, k=key: self.show_section(k))
            self.section_group.addButton(item)
            self.section_buttons[key] = item
            self.section_nav.add_item(item)
            self._builders[key] = builder
        self.section_nav.finish()
        nav_col = QVBoxLayout()
        nav_col.addWidget(self.section_nav)
        nav_col.addStretch(1)
        body.addLayout(nav_col)
        body.addWidget(self.stack, 1)
        self.show_section("appearance", animate=False)

    # -- section plumbing ------------------------------------------------------
    def show_section(self, key: str, animate: bool = True) -> None:
        if key not in self._builders:
            return
        if key not in self._built:
            content = QWidget()
            lay = QVBoxLayout(content)
            lay.setContentsMargins(0, 0, 8, 28)
            lay.setSpacing(16)
            lay.addWidget(self._builders[key]())
            lay.addStretch(1)
            area = scroll_wrap(content)
            self._built[key] = area
            self.stack.addWidget(area)
            self._loading = True
            try:
                for fn in list(self._refreshers):
                    fn()
            finally:
                self._loading = False
        if animate and self.isVisible() and self.stack.currentWidget() is not self._built[key]:
            from src.ui import anim

            anim.snapshot_fade(self.stack, anim.MEDIUM, drift=6)
        self.stack.setCurrentWidget(self._built[key])
        btn = self.section_buttons[key]
        btn.setChecked(True)
        QTimer.singleShot(0, lambda: self.section_nav.select(btn, animate=animate and self.isVisible()))

    def on_refresh(self, fn: Callable[[], None]) -> None:
        self._refreshers.append(fn)

    def refresh(self) -> None:
        self._loading = True
        try:
            for fn in list(self._refreshers):
                fn()
        finally:
            self._loading = False
        btn = self.section_group.checkedButton()
        if btn is not None:
            QTimer.singleShot(0, lambda: self.section_nav.select(btn, animate=False))

    def set_pref(self, key: str, value) -> bool:
        """Save one preference (ignored while the page is loading values)."""
        if self._loading or self.ctx.settings.get(key) == value:
            return False
        try:
            self.ctx.settings.set(key, value)
        except (ValueError, KeyError) as exc:
            show_error(self, "Invalid setting", str(exc))
            return False
        self._own_change = True
        bus.notify("settings")
        return True

    _set = set_pref  # v1 name

    def _on_data_changed(self, domain: str) -> None:
        if getattr(self, "_own_change", False) and domain == "settings":
            self._own_change = False
            self.refresh()
            return
        super()._on_data_changed(domain)

    @staticmethod
    def _card(title: str, icon: str) -> Card:
        card = Card(title, icon)
        return card

    # -- appearance ---------------------------------------------------------------
    def _build_appearance(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        card = Card("Theme", "sparkle")
        card.body.addWidget(label("Five complete themes share one design system. Pick the one that feels right "
                                  "for the time of day; switching is instant and never touches your data.",
                                  "muted", wrap=True))
        grid = QGridLayout()
        grid.setSpacing(14)
        self.theme_cards: dict[str, ThemePreviewCard] = {}
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        for i, t in enumerate(THEMES.values()):
            c = ThemePreviewCard(t)
            c.clicked.connect(lambda _=False, tid=t.id: self._pick_theme(tid))
            self.theme_group.addButton(c)
            self.theme_cards[t.id] = c
            grid.addWidget(c, i // 3, i % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        card.body.addLayout(grid)
        light_name, dark_name = (THEMES[k].name.replace("&", "&&") for k in SYSTEM_PAIR)
        self.follow_windows = QCheckBox(f"Match Windows: use {light_name} in light mode and {dark_name} in dark mode")
        self.follow_windows.toggled.connect(self._toggle_follow)
        card.body.addWidget(self.follow_windows)
        lay.addWidget(card)

        card = Card("Accent & text", "edit")
        form = form_layout(card.body)
        self.accent_row = QHBoxLayout()
        self.accent_row.setSpacing(4)
        accent_box = QWidget()
        accent_box.setLayout(self.accent_row)
        form.addRow("Accent colour", accent_box)
        self.accent_note = label("", "caption", wrap=True)
        form.addRow("", self.accent_note)
        self.scale_seg = SegmentBar([(str(s), f"{round(s * 100)}%") for s in FONT_SCALES], "1.0")
        self.scale_seg.changed.connect(lambda v: self.set_pref("font_scale", float(v)))
        form.addRow("Text size", self.scale_seg)
        self.reduce_motion = QCheckBox("Reduce motion (no fades or sliding)")
        self.reduce_motion.toggled.connect(lambda v: self.set_pref("reduce_motion", v))
        form.addRow("Motion", self.reduce_motion)
        if theme.system_reduced_motion:
            form.addRow("", label("Windows animations are off, so DayOS already keeps motion to a minimum.",
                                  "caption", wrap=True))
        lay.addWidget(card)

        def load() -> None:
            pref = self.ctx.settings.get("theme")
            active = theme.resolve(pref).id
            for tid, c in self.theme_cards.items():
                c.setChecked(tid == active)
            self.follow_windows.setChecked(pref == "system")
            self._fill_accents(active)
            scale = float(self.ctx.settings.get("font_scale"))
            self.scale_seg.set_current(str(scale))
            self.reduce_motion.setChecked(bool(self.ctx.settings.get("reduce_motion")))

        self.on_refresh(load)
        theme.changed.connect(self._appearance_changed)
        return box

    def _appearance_changed(self) -> None:
        if self._loading:
            return
        self._loading = True
        try:
            pref = self.ctx.settings.get("theme")
            active = theme.resolve(pref).id
            for tid, c in self.theme_cards.items():
                c.setChecked(tid == active)
            self.follow_windows.setChecked(pref == "system")
            self._fill_accents(active)
        finally:
            self._loading = False

    def _fill_accents(self, theme_id: str) -> None:
        clear_layout(self.accent_row)
        t = THEMES[theme_id]
        current = accent_for(self.ctx.settings, theme_id) or (t.accents[0].key if t.accents else "")
        for option in t.accents:
            color = t.palette(option.key)["accent"]
            sw = AccentSwatch(option.key, option.name, color)
            sw.setChecked(option.key == current)
            sw.picked.connect(lambda key, tid=theme_id: self._pick_accent(tid, key))
            self.accent_row.addWidget(sw)
        self.accent_row.addStretch(1)
        names = ", ".join(a.name for a in t.accents)
        self.accent_note.setText(f"{t.name} offers {names}. Each option is contrast-checked for readability.")

    def _pick_theme(self, theme_id: str) -> None:
        self.follow_windows.blockSignals(True)
        self.follow_windows.setChecked(False)
        self.follow_windows.blockSignals(False)
        self.set_pref("theme", theme_id)

    def _toggle_follow(self, on: bool) -> None:
        if on:
            self.set_pref("theme", "system")
        else:
            self.set_pref("theme", theme.theme.id)

    def _pick_accent(self, theme_id: str, key: str) -> None:
        if self._loading:
            return
        t = THEMES[theme_id]
        set_accent(self.ctx.settings, theme_id, None if t.accents and key == t.accents[0].key else key)
        self._own_change = True
        bus.notify("settings")

    # -- profile & layout -------------------------------------------------------------
    def _build_profile(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        card = Card("Profile", "subject")
        card.body.addWidget(label("A profile is a starting point for your sidebar, dashboard and quick actions. "
                                  "It never changes or hides your data, and you can fine-tune it below.",
                                  "muted", wrap=True))
        self.profile_group = QButtonGroup(self)
        self.profile_buttons: dict[str, QRadioButton] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        for i, prof in enumerate(PROFILES.values()):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            rb = QRadioButton(prof.name)
            rb.toggled.connect(lambda on, pid=prof.id: on and self._pick_profile(pid))
            self.profile_group.addButton(rb)
            self.profile_buttons[prof.id] = rb
            cell.addWidget(rb)
            desc = label(prof.description, "caption", wrap=True)
            desc.setContentsMargins(26, 0, 0, 0)
            cell.addWidget(desc)
            grid.addLayout(cell, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)
        lay.addWidget(card)

        card = Card("Sidebar modules", "sidebar")
        card.body.addWidget(label("Choose which modules appear in the sidebar. Hidden modules keep their data and "
                                  "stay reachable from the command palette (Ctrl+K).", "muted", wrap=True))
        mgrid = QGridLayout()
        mgrid.setHorizontalSpacing(18)
        mgrid.setVerticalSpacing(8)
        self.module_checks: dict[str, QCheckBox] = {}
        optional = [m for m in registry.MODULES if not m.core]
        for i, spec in enumerate(optional):
            cell = QVBoxLayout()
            cell.setSpacing(1)
            cb = QCheckBox(spec.title)
            cb.toggled.connect(lambda _on: self._save_modules())
            self.module_checks[spec.key] = cb
            cell.addWidget(cb)
            d = label(spec.description, "caption", wrap=True)
            d.setContentsMargins(26, 0, 0, 0)
            cell.addWidget(d)
            mgrid.addLayout(cell, i // 2, i % 2)
        mgrid.setColumnStretch(0, 1)
        mgrid.setColumnStretch(1, 1)
        card.body.addLayout(mgrid)
        lay.addWidget(card)

        card = Card("Today dashboard", "today")
        card.body.addWidget(label("Tick the widgets you want on Today and use the arrows to order them. Only "
                                  "widgets backed by your own records are offered.", "muted", wrap=True))
        row = QHBoxLayout()
        self.widget_list = QListWidget()
        self.widget_list.setMinimumHeight(250)
        self.widget_list.setAccessibleName("Dashboard widgets")
        self.widget_list.itemChanged.connect(lambda _i: self._save_widgets())
        row.addWidget(self.widget_list, 1)
        col = QVBoxLayout()
        col.addWidget(button("Move up", "", "chev-up", lambda: self._move_widget(-1), "Move the selected widget up"))
        col.addWidget(button("Move down", "", "chev-down", lambda: self._move_widget(1),
                             "Move the selected widget down"))
        col.addWidget(button("Profile defaults", "ghost", "reset", self._reset_widgets))
        col.addStretch(1)
        row.addLayout(col)
        card.body.addLayout(row)
        lay.addWidget(card)

        def load() -> None:
            s = self.ctx.settings
            pid = s.get("profile")
            if pid in self.profile_buttons:
                self.profile_buttons[pid].setChecked(True)
            visible = set(visible_module_keys(s))
            for key, cb in self.module_checks.items():
                cb.setChecked(key in visible)
            self._fill_widget_list()

        self.on_refresh(load)
        return box

    def _available_widgets(self) -> list[str]:
        today_page = self.main.pages.get("today")
        cards = getattr(today_page, "cards", {}) if today_page is not None else {}
        return [k for k in WIDGETS if k in cards]

    def _fill_widget_list(self) -> None:
        self.widget_list.blockSignals(True)
        self.widget_list.clear()
        today_page = self.main.pages.get("today")
        current = today_page.widget_keys() if today_page is not None and hasattr(today_page, "widget_keys") else []
        available = self._available_widgets()
        ordered = current + [k for k in available if k not in current]
        for key in ordered:
            item = QListWidgetItem(WIDGETS.get(key, key))
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in current else Qt.CheckState.Unchecked)
            self.widget_list.addItem(item)
        self.widget_list.blockSignals(False)

    def _save_widgets(self) -> None:
        if self._loading:
            return
        keys = []
        for i in range(self.widget_list.count()):
            item = self.widget_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                keys.append(item.data(Qt.ItemDataRole.UserRole))
        self.set_pref("dashboard.widgets", keys)

    def _move_widget(self, delta: int) -> None:
        row = self.widget_list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.widget_list.count():
            return
        self.widget_list.blockSignals(True)
        item = self.widget_list.takeItem(row)
        self.widget_list.insertItem(target, item)
        self.widget_list.setCurrentRow(target)
        self.widget_list.blockSignals(False)
        self._save_widgets()

    def _reset_widgets(self) -> None:
        self.set_pref("dashboard.widgets", None)
        self._fill_widget_list()

    def _pick_profile(self, profile_id: str) -> None:
        if self._loading or profile_id == self.ctx.settings.get("profile"):
            return
        s = self.ctx.settings
        customised = s.get("nav.modules") is not None or s.get("dashboard.widgets") is not None
        if customised and not confirm(
                self, f"Switch to “{get_profile(profile_id).name}”?",
                "Your sidebar and dashboard will use this profile's suggestions. Your data is not changed, and "
                "you can adjust modules and widgets again afterwards.", "Switch profile", danger=False):
            self.refresh()
            return
        s.set("nav.modules", None)
        s.set("dashboard.widgets", None)
        self.set_pref("profile", profile_id)
        self.toast(f"Profile: {get_profile(profile_id).name}")

    def _save_modules(self) -> None:
        if self._loading:
            return
        keys = [m.key for m in registry.MODULES if m.core or (m.key in self.module_checks
                                                              and self.module_checks[m.key].isChecked())]
        self.set_pref("nav.modules", keys)

    # -- general --------------------------------------------------------------------------
    def _build_general(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        card = Card("You", "leaf")
        form = form_layout(card.body)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Optional — used in the greeting")
        self.name.setMaxLength(40)
        self.name.editingFinished.connect(lambda: self.set_pref("user_name", self.name.text().strip()))
        form.addRow("Your name", self.name)
        self.show_clock = QCheckBox("Show a clock on the Today page")
        self.show_clock.toggled.connect(lambda v: self.set_pref("show_clock", v))
        form.addRow("", self.show_clock)
        lay.addWidget(card)

        card = Card("Date & time", "calendar")
        form = form_layout(card.body)
        self.week_start_box = QComboBox()
        self.week_start_box.addItems(WEEKDAY_NAMES)
        self.week_start_box.currentIndexChanged.connect(lambda i: self.set_pref("week_start", i))
        form.addRow("Week starts on", self.week_start_box)
        self.clock_seg = SegmentBar([("24", "24-hour"), ("12", "12-hour")], "24")
        self.clock_seg.changed.connect(lambda v: self.set_pref("clock_24h", v == "24"))
        form.addRow("Clock", self.clock_seg)
        self.date_fmt = QComboBox()
        for key, example in DATE_FORMATS.items():
            self.date_fmt.addItem(example, key)
        self.date_fmt.currentIndexChanged.connect(lambda _: self.set_pref("date_format", self.date_fmt.currentData()))
        form.addRow("Date format", self.date_fmt)
        lay.addWidget(card)

        card = Card("Startup", "today")
        form = form_layout(card.body)
        self.launch = QCheckBox("Open DayOS when I sign in to Windows")
        self.launch.setEnabled(startup.is_supported())
        self.launch.toggled.connect(self._toggle_launch)
        form.addRow("", self.launch)
        form.addRow("", label("Off by default. This adds or removes a single entry for your Windows account only "
                              "(no administrator rights).", "caption", wrap=True))
        lay.addWidget(card)

        def load() -> None:
            s = self.ctx.settings
            self.name.setText(s.get("user_name"))
            self.show_clock.setChecked(bool(s.get("show_clock")))
            self.week_start_box.setCurrentIndex(int(s.get("week_start")))
            self.clock_seg.set_current("24" if s.get("clock_24h") else "12")
            self.date_fmt.setCurrentIndex(max(0, self.date_fmt.findData(s.get("date_format"))))
            self.launch.setChecked(startup.is_enabled())

        self.on_refresh(load)
        return box

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

    # -- focus & notifications ------------------------------------------------------------
    def _build_focus(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        card = Card("Focus timer", "study")
        form = form_layout(card.body)
        self.spins: dict[str, QSpinBox] = {}
        for key, text, hi in (("study.focus_minutes", "Focus length", 240), ("study.short_break", "Short break", 60),
                              ("study.long_break", "Long break", 120), ("focus.cycles", "Long break after", 8)):
            spin = QSpinBox()
            spin.setRange(2 if key == "focus.cycles" else 1, hi)
            spin.setSuffix(" focus sessions" if key == "focus.cycles" else " min")
            spin.valueChanged.connect(lambda v, k=key: self.set_pref(k, v))
            self.spins[key] = spin
            form.addRow(text, spin)
        self.break_reminder = QSpinBox()
        self.break_reminder.setRange(0, 240)
        self.break_reminder.setSingleStep(15)
        self.break_reminder.setSpecialValueText("Off")
        self.break_reminder.setSuffix(" min of continuous focus")
        self.break_reminder.valueChanged.connect(lambda v: self.set_pref("focus.break_reminder", v))
        form.addRow("Suggest a break after", self.break_reminder)
        form.addRow("", label("DayOS never plays sounds and never blocks other apps. The taskbar button flashes "
                              "briefly when a timer ends.", "caption", wrap=True))
        lay.addWidget(card)

        card = Card("Notifications & reminders", "bell")
        form = form_layout(card.body)
        self.notify = QCheckBox("Show Windows notifications (pop-ups) for reminders and timers")
        self.notify.toggled.connect(lambda v: self.set_pref("notify_desktop", v))
        form.addRow("", self.notify)
        self.notify_checks: dict[str, QCheckBox] = {}
        for key, text in (("notify.reminder", "Reminders you set"), ("notify.event", "Event reminders"),
                          ("notify.habit", "Habit reminders"), ("notify.bill", "Bill and subscription renewals"),
                          ("notify.bedtime", "A gentle bedtime reminder")):
            cb = QCheckBox(text)
            cb.toggled.connect(lambda v, k=key: self.set_pref(k, v))
            self.notify_checks[key] = cb
            form.addRow("", cb)
        self.bedtime = TimeEdit(clock24=bool(self.ctx.settings.get("clock_24h")))
        self.bedtime.timeChanged.connect(lambda _t: self.set_pref("bedtime.time", self.bedtime.value()))
        form.addRow("Bedtime", self.bedtime)
        quiet_row = QHBoxLayout()
        self.quiet = QCheckBox("Quiet hours from")
        self.quiet.toggled.connect(lambda v: self.set_pref("quiet.enabled", v))
        self.quiet_start = TimeEdit(clock24=bool(self.ctx.settings.get("clock_24h")))
        self.quiet_start.timeChanged.connect(lambda _t: self.set_pref("quiet.start", self.quiet_start.value()))
        self.quiet_end = TimeEdit(clock24=bool(self.ctx.settings.get("clock_24h")))
        self.quiet_end.timeChanged.connect(lambda _t: self.set_pref("quiet.end", self.quiet_end.value()))
        quiet_row.addWidget(self.quiet)
        quiet_row.addWidget(self.quiet_start)
        quiet_row.addWidget(label("to", "muted"))
        quiet_row.addWidget(self.quiet_end)
        quiet_row.addStretch(1)
        form.addRow("Quiet hours", quiet_row)
        form.addRow("", label("During quiet hours nothing pops up; reminders wait in the notification centre "
                              "(the bell at the bottom of the sidebar).", "caption", wrap=True))
        lay.addWidget(card)

        card = Card("Workload check", "clock")
        form = form_layout(card.body)
        self.work_hours = QDoubleSpinBox()
        self.work_hours.setRange(0, 18)
        self.work_hours.setSingleStep(0.5)
        self.work_hours.setDecimals(1)
        self.work_hours.setSpecialValueText("Not set")
        self.work_hours.setSuffix(" h on weekdays")
        self.work_hours.valueChanged.connect(lambda v: self.set_pref("workload.hours", float(v) if v else None))
        form.addRow("Time I usually have", self.work_hours)
        self.weekend_hours = QDoubleSpinBox()
        self.weekend_hours.setRange(0, 18)
        self.weekend_hours.setSingleStep(0.5)
        self.weekend_hours.setDecimals(1)
        self.weekend_hours.setSpecialValueText("Same as weekdays")
        self.weekend_hours.setSuffix(" h at weekends")
        self.weekend_hours.valueChanged.connect(lambda v: self.set_pref("workload.weekend_hours", float(v) if v else None))
        form.addRow("", self.weekend_hours)
        form.addRow("", label("Include classes and appointments. DayOS compares this with timed calendar items and "
                              "your task estimates, and only suggests what could move; it never reschedules anything.",
                              "caption", wrap=True))
        lay.addWidget(card)

        card = Card("Quick capture", "inbox")
        form = form_layout(card.body)
        self.capture_global = QCheckBox("Allow a system-wide shortcut for quick capture")
        self.capture_global.toggled.connect(lambda v: self.set_pref("capture.global", v))
        form.addRow("", self.capture_global)
        self.capture_key = QKeySequenceEdit()
        self.capture_key.setMaximumSequenceLength(1)
        self.capture_key.editingFinished.connect(self._capture_key_changed)
        form.addRow("Shortcut", self.capture_key)
        self.capture_status = label("", "caption", wrap=True)
        form.addRow("", self.capture_status)
        form.addRow("", label("Inside DayOS, Ctrl+Shift+Space always opens quick capture. The system-wide "
                              "shortcut only claims the exact keys you choose; DayOS never records other typing.",
                              "caption", wrap=True))
        lay.addWidget(card)

        def load() -> None:
            s = self.ctx.settings
            for key, spin in self.spins.items():
                spin.setValue(int(s.get(key)))
            self.break_reminder.setValue(int(s.get("focus.break_reminder")))
            self.notify.setChecked(bool(s.get("notify_desktop")))
            for key, cb in self.notify_checks.items():
                cb.setChecked(bool(s.get(key)))
            self.bedtime.set_value(s.get("bedtime.time"))
            self.quiet.setChecked(bool(s.get("quiet.enabled")))
            self.quiet_start.set_value(s.get("quiet.start"))
            self.quiet_end.set_value(s.get("quiet.end"))
            self.work_hours.setValue(float(s.get("workload.hours") or 0))
            self.weekend_hours.setValue(float(s.get("workload.weekend_hours") or 0))
            self.capture_global.setChecked(bool(s.get("capture.global")))
            self.capture_key.setKeySequence(QKeySequence(str(s.get("capture.hotkey"))))
            self._capture_status()

        self.on_refresh(load)
        return box

    def _capture_key_changed(self) -> None:
        text = self.capture_key.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if text:
            self.set_pref("capture.hotkey", text)
        QTimer.singleShot(50, self._capture_status)

    def _capture_status(self) -> None:
        hk = self.main.hotkeys
        if not self.ctx.settings.get("capture.global"):
            self.capture_status.setText("System-wide shortcut is off.")
            self.capture_status.setProperty("role", "caption")
        elif hk.is_registered("capture"):
            self.capture_status.setText(f"Active: press {self.ctx.settings.get('capture.hotkey')} anywhere in Windows.")
            self.capture_status.setProperty("role", "success")
        else:
            self.capture_status.setText(hk.errors.get("capture", "Not registered."))
            self.capture_status.setProperty("role", "warning")
        self.capture_status.style().unpolish(self.capture_status)
        self.capture_status.style().polish(self.capture_status)

    # -- data & backups ----------------------------------------------------------------------
    def _build_data(self) -> QWidget:
        ctx = self.ctx
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
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
        auto_row = QHBoxLayout()
        auto_row.addWidget(label("Automatic backup", "muted"))
        self.auto_backup = QComboBox()
        self.auto_backup.setAccessibleName("Automatic backup")
        for key, text in (("off", "Off"), ("daily", "Once a day"), ("weekly", "Once a week")):
            self.auto_backup.addItem(text, key)
        self.auto_backup.activated.connect(lambda _i: self.set_pref("backup.auto", self.auto_backup.currentData()))
        auto_row.addWidget(self.auto_backup)
        auto_row.addWidget(label("keep the newest", "muted"))
        self.auto_keep = QSpinBox()
        self.auto_keep.setRange(2, 100)
        self.auto_keep.setSuffix(" automatic backups")
        self.auto_keep.setAccessibleName("Automatic backups to keep")
        self.auto_keep.valueChanged.connect(lambda v: self.set_pref("backup.keep", int(v)))
        auto_row.addWidget(self.auto_keep)
        auto_row.addStretch(1)
        body.addLayout(auto_row)
        body.addWidget(label("Only older automatic backups are removed, keeping the number you choose. Backups you "
                             "make yourself, and the safety copies DayOS takes before every upgrade, import and "
                             "restore, are never deleted automatically. Restoring first saves a copy of your current "
                             "data.", "caption", wrap=True))
        lay.addWidget(self.backup_card)

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
        lay.addWidget(card)
        self.on_refresh(self._fill_backups)
        return box

    def _fill_backups(self) -> None:
        if not hasattr(self, "backup_list"):
            return
        self.auto_backup.setCurrentIndex(max(0, self.auto_backup.findData(self.ctx.settings.get("backup.auto"))))
        self.auto_keep.setValue(int(self.ctx.settings.get("backup.keep")))
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
        return all(page.can_leave() for page in list(self.main.pages.values()) if page is not self)

    def _after_data_replaced(self) -> None:
        self.ctx.settings.reload()
        apply_from_settings(self.ctx.settings)
        notes = self.main.pages.get("notes")
        if notes is not None and hasattr(notes, "_open"):
            notes.current = None  # type: ignore[attr-defined]
            notes._dirty_edit = False  # type: ignore[attr-defined]
            notes._open(None)  # type: ignore[attr-defined]
        self.main._build_nav()
        bus.notify("all")

    def _integrity(self) -> None:
        problems = self.ctx.db.integrity_check()
        if problems:
            show_error(self, "Problems found", "The database reported:\n" + "\n".join(problems[:10]),
                       "Restore a recent backup from this page if data looks wrong.")
        else:
            show_info(self, "Database is healthy", "SQLite's integrity and foreign-key checks found no problems.")

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
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the CSV files",
                                                  str(self.ctx.paths.exports_dir))
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

    # -- shortcuts & about ------------------------------------------------------------------
    def _build_shortcuts(self) -> QWidget:
        card = Card("Keyboard shortcuts", "keyboard")
        form = form_layout(card.body)
        for keys, desc in SHORTCUTS:
            form.addRow(label(keys, "muted"), label(desc, "", wrap=True))
        return card

    def _build_about(self) -> QWidget:
        card = Card("About", "info")
        body = card.body
        body.addWidget(label(f"{APP_NAME} {APP_VERSION}", "section"))
        body.addWidget(label(f"Made by {ORGANIZATION}. Local-first: no accounts, no cloud, no telemetry. Optional "
                             "online features (weather, news, AI) only connect when you turn them on.",
                             "muted", wrap=True))
        body.addWidget(label(f"Python {platform.python_version()} · Qt for Python {PYSIDE_VERSION} · "
                             f"SQLite schema v{self.ctx.db.user_version}", "caption", wrap=True))
        body.addWidget(label(f"Data folder: {self.ctx.paths.home}", "caption", wrap=True, selectable=True))
        row = QHBoxLayout()
        row.addWidget(button("Open data folder", "ghost", "folder", lambda: self._open(self.ctx.paths.home)))
        row.addWidget(button("Open logs folder", "ghost", "folder", lambda: self._open(self.ctx.paths.logs_dir)))
        row.addWidget(button("Reset settings…", "ghost", "reset", self._reset_settings))
        row.addStretch(1)
        body.addLayout(row)
        body.addWidget(label("Resetting settings restores default preferences only. Your tasks, notes and other "
                             "data are not touched.", "caption", wrap=True))
        return card

    def _reset_settings(self) -> None:
        if confirm(self, "Reset settings?", "All preferences go back to their defaults. Your data is not affected.",
                   "Reset settings", danger=False):
            self.ctx.settings.reset_preferences()
            apply_from_settings(self.ctx.settings)
            self.main.set_sidebar_collapsed(False, animate=False)
            self.main._build_nav()
            bus.notify("settings")
            self.refresh()
            self.toast("Settings reset")

    def _open(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
