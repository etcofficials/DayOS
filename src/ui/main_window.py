"""The DayOS main window: sidebar navigation, page stack, shortcuts and toasts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from PySide6.QtCore import QByteArray, QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.context import AppContext
from src.ui.bus import bus
from src.ui.icons import bind_icon
from src.ui.pages.base import Page
from src.ui.theme import theme
from src.ui.widgets.common import Toast, label, show_info
from src.version import APP_NAME

log = logging.getLogger(__name__)

SIDEBAR_WIDE = 212
SIDEBAR_NARROW = 64

SHORTCUTS = [
    ("Ctrl+1 … Ctrl+9", "Go to Today, Tasks, Calendar, Study, Exams, Notes, Habits, Goals, Insights"),
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
    ("Study: Ctrl+Enter", "Start or pause the focus timer"),
]


def app_icon(paths) -> QIcon:
    svg = paths.assets_dir / "dayos.svg"
    ico = paths.assets_dir / "dayos.ico"
    if ico.exists():
        return QIcon(str(ico))
    return QIcon(str(svg)) if svg.exists() else QIcon()


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon(ctx.paths))
        self.setMinimumSize(QSize(920, 620))
        self._closing_confirmed = False

        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = self._build_sidebar()
        layout.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")
        layout.addWidget(self.stack, 1)

        self.toast = Toast(root, reduce_motion=self.motion_reduced)
        self.pages: dict[str, Page] = {}
        self._build_pages()
        self._install_shortcuts()
        self._restore_geometry()
        self.set_sidebar_collapsed(bool(ctx.settings.get("sidebar_collapsed")), animate=False)
        self._schedule_midnight()
        self.navigate("today")

    # -- sidebar -------------------------------------------------------------
    NAV = [
        ("today", "Today", "today"),
        ("tasks", "Tasks", "tasks"),
        ("calendar", "Calendar", "calendar"),
        ("study", "Study", "study"),
        ("exams", "Exams", "exams"),
        ("notes", "Notes", "notes"),
        ("habits", "Habits", "habits"),
        ("goals", "Goals", "goals"),
        ("insights", "Insights", "insights"),
    ]

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        side.setFixedWidth(SIDEBAR_WIDE)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 18, 12, 14)
        lay.setSpacing(2)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 0, 0)
        brand_row.setSpacing(10)
        self.logo = QLabel()
        self.logo.setPixmap(self.windowIcon().pixmap(28, 28))
        self.logo.setFixedSize(28, 28)
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
        lay.addSpacing(20)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QToolButton] = {}
        for i, (key, text, icon_name) in enumerate(self.NAV + [("settings", "Settings", "settings")]):
            if key == "settings":
                lay.addStretch(1)
                self.timer_hint = label("", "caption", wrap=True)
                self.timer_hint.setContentsMargins(10, 0, 6, 6)
                self.timer_hint.hide()
                lay.addWidget(self.timer_hint)
            btn = QToolButton()
            btn.setObjectName("NavButton")
            btn.setText(text)
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(38)
            btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            shortcut = "Ctrl+," if key == "settings" else f"Ctrl+{i + 1}"
            btn.setToolTip(f"{text}  ({shortcut})")
            btn.setAccessibleName(text)
            bind_icon(btn, icon_name, "text2", 18, active_key="accent")
            btn.clicked.connect(lambda _=False, k=key: self.navigate(k))
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
            lay.addWidget(btn)

        lay.addSpacing(6)
        self.collapse_btn = QToolButton()
        self.collapse_btn.setObjectName("CollapseButton")
        self.collapse_btn.setToolTip("Collapse sidebar (Ctrl+B)")
        self.collapse_btn.setAccessibleName("Collapse or expand sidebar")
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        bind_icon(self.collapse_btn, "sidebar", "text3", 18)
        self.collapse_btn.clicked.connect(lambda: self.set_sidebar_collapsed(not self._collapsed))
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 0, 0)
        row.addWidget(self.collapse_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._collapsed = False
        self._anim: QPropertyAnimation | None = None
        return side

    def set_sidebar_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        self._collapsed = collapsed
        for key, btn in self.nav_buttons.items():
            btn.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly if collapsed else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
        self.brand.setVisible(not collapsed)
        self.brand_sub.setVisible(not collapsed)
        self.timer_hint.setVisible(bool(self.timer_hint.text()) and not collapsed)
        target = SIDEBAR_NARROW if collapsed else SIDEBAR_WIDE
        self.collapse_btn.setToolTip(("Expand" if collapsed else "Collapse") + " sidebar (Ctrl+B)")
        if animate and not self.motion_reduced():
            for prop in (b"minimumWidth", b"maximumWidth"):
                anim = QPropertyAnimation(self.sidebar, prop, self)
                anim.setDuration(160)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.setStartValue(self.sidebar.width())
                anim.setEndValue(target)
                anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        else:
            self.sidebar.setFixedWidth(target)
        if self.ctx.settings.get("sidebar_collapsed") != collapsed:
            self.ctx.settings.set("sidebar_collapsed", collapsed)

    def motion_reduced(self) -> bool:
        return bool(self.ctx.settings.get("reduce_motion")) or theme.system_reduced_motion

    def set_timer_hint(self, text: str) -> None:
        self.timer_hint.setText(text)
        self.timer_hint.setVisible(bool(text) and not self._collapsed)
        study_btn = self.nav_buttons["study"]
        study_btn.setToolTip(f"Study  (Ctrl+4)\n{text}" if text else "Study  (Ctrl+4)")

    # -- pages -----------------------------------------------------------------
    def _build_pages(self) -> None:
        from src.ui.pages.calendar import CalendarPage
        from src.ui.pages.exams import ExamsPage
        from src.ui.pages.goals import GoalsPage
        from src.ui.pages.habits import HabitsPage
        from src.ui.pages.insights import InsightsPage
        from src.ui.pages.notes import NotesPage
        from src.ui.pages.settings import SettingsPage
        from src.ui.pages.study import StudyPage
        from src.ui.pages.tasks import TasksPage
        from src.ui.pages.today import TodayPage

        classes = {
            "today": TodayPage, "tasks": TasksPage, "calendar": CalendarPage, "study": StudyPage,
            "exams": ExamsPage, "notes": NotesPage, "habits": HabitsPage, "goals": GoalsPage,
            "insights": InsightsPage, "settings": SettingsPage,
        }
        for key, cls in classes.items():
            page = cls(self.ctx, self)
            page.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            self.pages[key] = page
            self.stack.addWidget(page)

    def current_key(self) -> str:
        widget = self.stack.currentWidget()
        for key, page in self.pages.items():
            if page is widget:
                return key
        return "today"

    def navigate(self, key: str) -> None:
        if key not in self.pages:
            return
        current = self.stack.currentWidget()
        if isinstance(current, Page) and current is not self.pages[key] and not current.can_leave():
            self.nav_buttons[self.current_key()].setChecked(True)
            return
        self.stack.setCurrentWidget(self.pages[key])
        self.nav_buttons[key].setChecked(True)
        if not self.pages[key].isAncestorOf(QApplication.focusWidget()):
            self.pages[key].setFocus(Qt.FocusReason.OtherFocusReason)

    def page(self, key: str) -> Page:
        return self.pages[key]

    # -- shortcuts ---------------------------------------------------------------
    def _install_shortcuts(self) -> None:
        def add(seq: str, fn) -> None:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(fn)

        for i, (key, _, _) in enumerate(self.NAV):
            add(f"Ctrl+{i + 1}", lambda k=key: self.navigate(k))
        add("Ctrl+,", lambda: self.navigate("settings"))
        add("Ctrl+N", lambda: self._current_page().new_item())
        add("Ctrl+F", lambda: self._current_page().focus_search())
        add("Ctrl+B", lambda: self.set_sidebar_collapsed(not self._collapsed))
        add("F5", lambda: self._current_page().refresh())
        add("F1", self.show_shortcuts)
        add("Ctrl+Shift+T", self.quick_task)
        add("Ctrl+Shift+N", self.quick_note)

    def _current_page(self) -> Page:
        return self.stack.currentWidget()  # type: ignore[return-value]

    def show_shortcuts(self) -> None:
        text = "\n".join(f"{keys}  —  {desc}" for keys, desc in SHORTCUTS)
        show_info(self, "Keyboard shortcuts", text)

    def quick_task(self) -> None:
        from src.ui.dialogs import TaskDialog
        from src.services.dates import today

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
            self.resize(1240, 800)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast._position()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        for page in self.pages.values():
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
        event.accept()
