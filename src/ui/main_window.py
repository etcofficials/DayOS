"""The DayOS main window: grouped sidebar navigation, lazily created pages, shortcuts and toasts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.context import AppContext
from src.modules import registry
from src.modules.profiles import get_profile
from src.ui import anim
from src.ui.anim import tween
from src.ui.bus import bus
from src.ui.icons import bind_icon
from src.ui.pages.base import Page
from src.ui.theme import theme
from src.ui.widgets.art import Art
from src.ui.widgets.common import Toast, label, separator, show_info
from src.ui.widgets.nav import NavItem, Sidebar
from src.version import APP_NAME

if TYPE_CHECKING:
    from src.modules.registry import ModuleSpec

log = logging.getLogger(__name__)

SIDEBAR_WIDE = 236
SIDEBAR_NARROW = 74

SHORTCUTS = [
    ("Ctrl+K", "Command palette: search everything and run any command"),
    ("Ctrl+Shift+Space", "Quick capture (a task, note, idea, link or snippet) from anywhere in DayOS"),
    ("Ctrl+1 … Ctrl+9", "Go to the first nine pages in the sidebar"),
    ("Ctrl+,", "Open Settings"),
    ("Ctrl+N", "New item on the current page"),
    ("Ctrl+F", "Search on the current page"),
    ("Ctrl+Shift+T", "Quick-add a task from anywhere"),
    ("Ctrl+Shift+N", "Quick note from anywhere"),
    ("Ctrl+S", "Save the current note"),
    ("Ctrl+B", "Collapse or expand the sidebar"),
    ("F5", "Refresh the current page"),
    ("F1", "Show keyboard shortcuts"),
    ("Tasks: Space / Enter / Delete", "Complete, edit or delete the selected task"),
    ("Focus: Ctrl+Enter", "Start or pause the focus timer"),
]


def app_icon(paths) -> QIcon:
    svg = paths.assets_dir / "art" / "mark.svg"
    ico = paths.assets_dir / "dayos.ico"
    if ico.exists():
        return QIcon(str(ico))
    return QIcon(str(svg)) if svg.exists() else QIcon()


def visible_module_keys(settings) -> list[str]:
    """Sidebar modules for the current profile / user choice, in registry order."""
    chosen = settings.get("nav.modules")
    if chosen is None:
        chosen = list(get_profile(settings.get("profile")).modules)
    wanted = set(chosen)
    return [m.key for m in registry.MODULES if m.core or m.key in wanted]


class _ArtBox(QWidget):
    def __init__(self, on_resize) -> None:
        super().__init__()
        self._on_resize = on_resize

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._on_resize()


class LazyPages(dict):
    """``pages[key]`` creates a page the first time it's needed; iteration covers created pages only."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self._window = window

    def __missing__(self, key: str) -> Page:
        page = self._window._create_page(key)
        if page is None:
            raise KeyError(key)
        return page


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon(ctx.paths))
        self.setMinimumSize(QSize(980, 640))
        self._closing_confirmed = False
        self._collapsed = False

        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        from src.modules import load_features

        load_features()
        self.nav_buttons: dict[str, NavItem] = {}
        self.sidebar = self._build_sidebar()
        layout.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")
        layout.addWidget(self.stack, 1)

        self.toast = Toast(root, reduce_motion=self.motion_reduced)
        anim.set_motion_provider(lambda: not self.motion_reduced())
        from src.ui.shell.commands import CommandRegistry, Openers
        from src.ui.shell.hotkeys import GlobalHotkeys
        from src.ui.shell.notifier import Notifier

        self.commands = CommandRegistry()
        self.openers = Openers()
        self.notifier = Notifier(self)
        self.notifier.changed.connect(self._update_bell)
        self.hotkeys = GlobalHotkeys()
        self.hotkeys.activated.connect(self._on_hotkey)
        self._capture = None
        # feature modules add system-wide shortcuts and clean-up work here (see add_global_hotkey)
        self.hotkey_sources: dict[str, tuple] = {}
        self._hotkey_setting_keys: set[str] = set()
        self.shutdown_hooks: list = []
        self.revision_providers: list = []  # StudyForge adds "topics due" to the Today revision widget
        theme.about_to_change.connect(self._theme_crossfade)
        self.pages: LazyPages = LazyPages(self)
        self._build_nav()
        for spec in registry.MODULES:
            if spec.eager:
                self.pages[spec.key]  # noqa: B018 - create eagerly
        self._install_shortcuts()
        self._restore_geometry()
        self.set_sidebar_collapsed(bool(ctx.settings.get("sidebar_collapsed")), animate=False)
        self._schedule_midnight()
        ctx.settings.subscribe(self._on_setting)
        from src.ui.shell.builtin import register_builtins

        register_builtins(self)
        from src.modules import install_ui

        install_ui(self)
        self._register_hotkeys()
        self.notifier.start()
        QTimer.singleShot(20000, self, self.run_auto_backup)  # after start-up settles; work runs off the UI thread
        self.navigate("today")

    # -- sidebar -------------------------------------------------------------
    def _build_sidebar(self) -> Sidebar:
        side = Sidebar()
        side.setFixedWidth(SIDEBAR_WIDE)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 18, 12, 14)
        lay.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 0, 0)
        brand_row.setSpacing(11)
        self.logo = Art("mark", 40, 40, Qt.AlignmentFlag.AlignCenter)
        self.logo.setFixedSize(40, 40)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        self.brand = QLabel(APP_NAME)
        self.brand.setObjectName("Brand")
        self.brand_sub = QLabel("your day, gently")
        self.brand_sub.setObjectName("BrandSub")
        brand_text.addWidget(self.brand)
        brand_text.addWidget(self.brand_sub)
        brand_row.addWidget(self.logo)
        brand_row.addLayout(brand_text, 1)
        lay.addLayout(brand_row)
        lay.addSpacing(10)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        lay.addWidget(side.scroll, 1)

        self.branch = Art("branch", 150, 250, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, 0.9)
        self.quote = QLabel("Better days\nbuild a better you.", self.branch)
        self.quote.setObjectName("SidebarQuote")
        self.quote.setContentsMargins(16, 0, 0, 14)
        art_box = _ArtBox(self._place_quote)
        art_lay = QVBoxLayout(art_box)
        art_lay.setContentsMargins(0, 0, 0, 0)
        self.branch.setParent(art_box)
        art_lay.addWidget(self.branch)
        self.quote.setParent(art_box)
        self.art_box = art_box
        side.set_art(art_box)

        self.timer_hint = label("", "caption", wrap=True)
        self.timer_hint.setContentsMargins(12, 4, 6, 4)
        self.timer_hint.hide()
        lay.addWidget(self.timer_hint)
        lay.addSpacing(2)
        lay.addWidget(separator())
        lay.addSpacing(4)
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        settings_item = self._make_item(registry.SETTINGS, "Ctrl+,")
        bottom.addWidget(settings_item, 1)
        self.bell_btn = QToolButton()
        self.bell_btn.setObjectName("BellButton")
        self.bell_btn.setToolTip("Notifications")
        self.bell_btn.setAccessibleName("Notifications")
        self.bell_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bell_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        bind_icon(self.bell_btn, "bell", "text2", 18)
        self.bell_btn.clicked.connect(lambda: self.show_notifications(self.bell_btn))
        bottom.addWidget(self.bell_btn)
        self.collapse_btn = QToolButton()
        self.collapse_btn.setObjectName("CollapseButton")
        self.collapse_btn.setToolTip("Collapse sidebar (Ctrl+B)")
        self.collapse_btn.setAccessibleName("Collapse or expand sidebar")
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        bind_icon(self.collapse_btn, "sidebar", "text3", 18)
        self.collapse_btn.clicked.connect(lambda: self.set_sidebar_collapsed(not self._collapsed))
        bottom.addWidget(self.collapse_btn)
        self.sidebar_bottom = bottom
        lay.addLayout(bottom)
        return side

    def _place_quote(self) -> None:
        self.quote.adjustSize()
        self.quote.move(0, max(0, self.art_box.height() - self.quote.height()))

    def _make_item(self, spec: "ModuleSpec", shortcut: str = "") -> NavItem:
        item = NavItem(spec.title, spec.icon)
        item.setToolTip(f"{spec.title}  ({shortcut})" if shortcut else spec.title)
        item.clicked.connect(lambda _=False, k=spec.key: self.navigate(k))
        self.nav_group.addButton(item)
        self.nav_buttons[spec.key] = item
        return item

    def _build_nav(self) -> None:
        """(Re)build the grouped nav list for the visible modules."""
        nav = self.sidebar.nav
        for key, item in list(self.nav_buttons.items()):
            if key != "settings":
                self.nav_group.removeButton(item)
                item.deleteLater()
                del self.nav_buttons[key]
        while nav.lay.count():
            it = nav.lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        nav._groups.clear()
        profile = get_profile(self.ctx.settings.get("profile"))
        self.visible_keys = visible_module_keys(self.ctx.settings)
        visible = set(self.visible_keys)
        index = 0
        for group_key, group_title in registry.GROUPS:
            specs = [m for m in registry.MODULES if m.group == group_key and m.key in visible]
            if not specs:
                continue
            nav.add_group(group_title)
            for spec in specs:
                index += 1
                title = profile.terms.get(spec.key, spec.title)
                item = self._make_item(spec, f"Ctrl+{index}" if index <= 9 else "")
                item.setText(title)
                item.setAccessibleName(title)
                item.collapsed = self._collapsed
                nav.add_item(item)
        nav.finish()
        nav.set_collapsed(self._collapsed)
        current = self.stack.currentWidget() if hasattr(self, "stack") else None
        if current is not None:
            key = self.current_key()
            if key in self.nav_buttons:
                self.nav_buttons[key].setChecked(True)
                QTimer.singleShot(0, lambda: self.sidebar.select(self.nav_buttons[key], animate=False))
            else:
                self.sidebar.nav.select(None)
        QTimer.singleShot(0, self.sidebar.resync)

    def set_sidebar_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        self._collapsed = collapsed
        self.sidebar.collapsed = collapsed
        for btn in self.nav_buttons.values():
            btn.collapsed = collapsed
            btn.update()
        self.sidebar.nav.set_collapsed(collapsed)
        for w in (self.brand, self.brand_sub):
            w.setVisible(not collapsed)
        self.timer_hint.setVisible(bool(self.timer_hint.text()) and not collapsed)
        self.sidebar_bottom.setDirection(
            QBoxLayout.Direction.TopToBottom if collapsed else QBoxLayout.Direction.LeftToRight)
        target = SIDEBAR_NARROW if collapsed else SIDEBAR_WIDE
        self.collapse_btn.setToolTip(("Expand" if collapsed else "Collapse") + " sidebar (Ctrl+B)")
        start = self.sidebar.width()

        def step(v: float) -> None:
            self.sidebar.setFixedWidth(int(v))
            self.sidebar.resync()

        if animate and self.isVisible():
            tween(self, start, target, anim.MEDIUM, step, self.sidebar.resync, key="_sidebar_anim")
        else:
            step(target)
        QTimer.singleShot(0, self.sidebar.resync)
        if self.ctx.settings.get("sidebar_collapsed") != collapsed:
            self.ctx.settings.set("sidebar_collapsed", collapsed)

    def _theme_crossfade(self) -> None:
        if self.isVisible():
            anim.snapshot_fade(self.centralWidget(), 300)

    def _on_setting(self, key: str, _value) -> None:
        if key in ("profile", "nav.modules"):
            self._build_nav()
        elif key in ("capture.global", "capture.hotkey") or key in self._hotkey_setting_keys:
            self._register_hotkeys()

    # -- shell: palette, capture, notifications, hotkeys -----------------------------
    def run_auto_backup(self) -> None:
        """Take an automatic backup in the background if one is due (see Settings → Data & backups)."""
        from src.services import autobackup
        from src.ui.worker import run_in_background

        interval = str(self.ctx.settings.get("backup.auto"))
        keep = int(self.ctx.settings.get("backup.keep"))
        paths = self.ctx.paths
        if not autobackup.is_due(paths.backups_dir, interval):
            return
        run_in_background(lambda: autobackup.run(paths.db_path, paths.backups_dir, interval, keep),
                          lambda p: log.info("Automatic backup %s", "written" if p else "not needed"),
                          lambda e: log.warning("Automatic backup failed: %s", e))

    def add_global_hotkey(self, name: str, sequence, handler, setting_keys: tuple[str, ...] = ()) -> None:
        """Let a feature claim a system-wide shortcut.

        ``sequence()`` returns the key combination to register, or None while the feature
        doesn't want one; it is re-evaluated whenever one of ``setting_keys`` changes.
        """
        self.hotkey_sources[name] = (sequence, handler)
        self._hotkey_setting_keys.update(setting_keys)

    def _register_hotkeys(self) -> None:
        self.hotkeys.unregister_all()
        if self.ctx.settings.get("capture.global"):
            self.hotkeys.register("capture", str(self.ctx.settings.get("capture.hotkey")))
        for name, (sequence, _handler) in self.hotkey_sources.items():
            try:
                combo = sequence()
            except Exception:
                log.warning("Hotkey source %s failed", name, exc_info=True)
                continue
            if combo:
                self.hotkeys.register(name, str(combo))

    def _on_hotkey(self, name: str) -> None:
        if name == "capture":
            self.quick_capture(standalone=not self.isActiveWindow())
        elif name in self.hotkey_sources:
            self.hotkey_sources[name][1]()

    def open_palette(self) -> None:
        from src.ui.shell.palette import CommandPalette

        CommandPalette(self).exec()

    def quick_capture(self, standalone: bool = False) -> None:
        from src.ui.shell.capture import CaptureWindow

        if self._capture is not None and self._capture.isVisible():
            self._capture.raise_()
            self._capture.activateWindow()
            return
        self._capture = CaptureWindow(self, standalone=standalone or self.isMinimized() or not self.isVisible())
        self._capture.finished.connect(lambda _r: setattr(self, "_capture", None))
        self._capture.show()

    def show_notifications(self, anchor=None) -> None:
        from src.ui.shell.notifier import NotificationCenter

        self.show_and_raise()
        center = NotificationCenter(self)
        center.popup(anchor or self.bell_btn)

    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _update_bell(self, count: int) -> None:
        bind_icon(self.bell_btn, "bell", "terracotta_text" if count else "text2", 18)
        self.bell_btn.setToolTip(f"Notifications: {count} due" if count else "Notifications")
        self.bell_btn.setAccessibleName(f"Notifications, {count} due" if count else "Notifications")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self.sidebar.resync)

    def motion_reduced(self) -> bool:
        return bool(self.ctx.settings.get("reduce_motion")) or theme.system_reduced_motion

    def set_timer_hint(self, text: str) -> None:
        self.timer_hint.setText(text)
        self.timer_hint.setVisible(bool(text) and not self._collapsed)
        study_btn = self.nav_buttons.get("study")
        if study_btn is not None:
            study_btn.setToolTip(f"{study_btn.text()}\n{text}" if text else study_btn.text())

    def set_badge(self, key: str, text: str) -> None:
        item = self.nav_buttons.get(key)
        if item is not None:
            item.set_badge(text)

    # -- pages -----------------------------------------------------------------
    def _create_page(self, key: str) -> Page | None:
        spec = registry.get(key)
        if spec is None:
            return None
        cls = registry.load_class(spec)
        page = cls(self.ctx, self)
        page.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        dict.__setitem__(self.pages, key, page)
        self.stack.addWidget(page)
        log.debug("Created page %s", key)
        return page

    def page_keys(self) -> list[str]:
        """Every registered page (visible in the sidebar or not)."""
        return registry.all_keys()

    def current_key(self) -> str:
        widget = self.stack.currentWidget()
        for key, page in self.pages.items():
            if page is widget:
                return key
        return "today"

    def navigate(self, key: str) -> None:
        if registry.get(key) is None:
            return
        current = self.stack.currentWidget()
        target = self.pages[key]
        if isinstance(current, Page) and current is not target and not current.can_leave():
            current_key = self.current_key()
            if current_key in self.nav_buttons:
                self.nav_buttons[current_key].setChecked(True)
                self.sidebar.select(self.nav_buttons[current_key])
            return
        if current is not target and self.isVisible():
            anim.snapshot_fade(self.stack, anim.PAGE, drift=10)
        self.stack.setCurrentWidget(target)
        item = self.nav_buttons.get(key)
        if item is not None:
            item.setChecked(True)
            if key == "settings":
                self.sidebar.nav.select(None)
            else:
                self.sidebar.select(item, animate=self.isVisible())
        else:
            checked = self.nav_group.checkedButton()
            if checked is not None:
                self.nav_group.setExclusive(False)
                checked.setChecked(False)
                self.nav_group.setExclusive(True)
            self.sidebar.nav.select(None)
        if not target.isAncestorOf(QApplication.focusWidget()):
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    def page(self, key: str) -> Page:
        return self.pages[key]

    # -- shortcuts ---------------------------------------------------------------
    def _install_shortcuts(self) -> None:
        def add(seq: str, fn) -> None:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(fn)

        for i in range(9):
            add(f"Ctrl+{i + 1}", lambda n=i: self._goto_index(n))
        add("Ctrl+,", lambda: self.navigate("settings"))
        add("Ctrl+N", lambda: self._current_page().new_item())
        add("Ctrl+F", lambda: self._current_page().focus_search())
        add("Ctrl+B", lambda: self.set_sidebar_collapsed(not self._collapsed))
        add("F5", lambda: self._current_page().refresh())
        add("F1", self.show_shortcuts)
        add("Ctrl+Shift+T", self.quick_task)
        add("Ctrl+Shift+N", self.quick_note)
        add("Ctrl+K", self.open_palette)
        add("Ctrl+Shift+Space", self.quick_capture)

    def _goto_index(self, n: int) -> None:
        keys = [k for k in self.visible_keys if k != "settings"]
        if n < len(keys):
            self.navigate(keys[n])

    def _current_page(self) -> Page:
        return self.stack.currentWidget()  # type: ignore[return-value]

    def show_shortcuts(self) -> None:
        text = "\n".join(f"{keys}  —  {desc}" for keys, desc in SHORTCUTS)
        show_info(self, "Keyboard shortcuts", text)

    def quick_task(self) -> None:
        from src.services.dates import today
        from src.ui.dialogs import TaskDialog

        TaskDialog(self.ctx, self, default_due=today()).exec()

    def quick_note(self) -> None:
        from src.ui.dialogs import QuickNoteDialog

        if QuickNoteDialog(self.ctx, self).exec():
            self.toast.show_message("Note saved")

    # -- day rollover ----------------------------------------------------------
    def _schedule_midnight(self) -> None:
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=1, microsecond=0)
        self._midnight = QTimer(self)
        self._midnight.setSingleShot(True)
        self._midnight.timeout.connect(self._on_midnight)
        self._midnight.start(int((tomorrow - now).total_seconds() * 1000))

    def _on_midnight(self) -> None:
        log.info("Day changed; refreshing pages")
        bus.notify("all")
        self._schedule_midnight()

    # -- window state ------------------------------------------------------------
    def _restore_geometry(self) -> None:
        geo = self.ctx.settings.get("state.window_geometry")
        restored = False
        if isinstance(geo, str):
            try:
                restored = self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
            except (ValueError, UnicodeError):
                restored = False
        if not restored:
            self.resize(1260, 820)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast._position()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        for page in list(self.pages.values()):
            if not page.can_leave():
                event.ignore()
                return
        study = self.pages.get("study")
        if study is not None and hasattr(study, "confirm_close") and not study.confirm_close():
            event.ignore()
            return
        try:
            self.ctx.settings.set(
                "state.window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii")
            )
        except Exception:
            log.warning("Could not save window geometry", exc_info=True)
        self.hotkeys.unregister_all()
        self.notifier.stop()
        for hook in list(self.shutdown_hooks):
            try:
                hook()
            except Exception:
                log.warning("Shutdown hook failed", exc_info=True)
        event.accept()
