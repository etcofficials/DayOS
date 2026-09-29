"""DayOS design system: colour tokens, typography and the generated Qt stylesheet.

Two coordinated palettes — a warm cream/sage light theme (the default) and a
warm dark theme. Measured contrast (WCAG, against the card surface):

* Light: text 14.1:1, secondary text 5.3:1, sage link text 5.4:1, dark-sage
  primary buttons 7.6:1. The specified mid-sage (#71896C), terracotta and dusty
  blue are used for fills, dots and icons; darker ``*_text`` variants carry text.
* Dark: text 11.8:1, secondary 6.7:1, sage 6.9:1.

Headings use an editorial serif (Georgia, bundled with Windows) and everything
else Segoe UI, so no fonts need downloading.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

FONT_FAMILY = "Segoe UI"
FONT_SERIF = "Georgia"

LIGHT: dict[str, str] = {
    "bg": "#F5F2E9",
    "sidebar": "#E9EDE3",
    "surface": "#FFFDF7",
    "elevated": "#F0F1E8",
    "input": "#FFFDF7",
    "hover": "#EDEFE5",
    "pressed": "#E2E7DA",
    "text": "#252C26",
    "text2": "#666D62",
    "text3": "#737A6F",
    "accent": "#71896C",
    "accent_hover": "#647C5F",
    "accent_pressed": "#57704F",
    "accent_text": "#56704F",
    "accent_dark": "#425845",
    "on_accent": "#FFFDF7",
    "accent_soft": "#DCE4D5",
    "primary": "#425845",
    "primary_hover": "#384C3B",
    "primary_pressed": "#2F4132",
    "on_primary": "#FFFDF7",
    "divider": "#E1E2D8",
    "border": "#D5D8CB",
    "blue": "#7793AE",
    "blue_text": "#566F89",
    "blue_soft": "#E2E9EF",
    "terracotta": "#C77D59",
    "terracotta_text": "#A8603D",
    "terracotta_soft": "#F4E4D9",
    "amber": "#C49A4A",
    "amber_text": "#8A6620",
    "amber_soft": "#F3EBD7",
    "danger": "#B5543F",
    "danger_soft": "#F6E2DC",
    "shadow": "#3C4A36",
    "chart_grid": "#ECECE3",
    "banner": "#E8ECDF",
}

DARK: dict[str, str] = {
    "bg": "#191D1A",
    "sidebar": "#202621",
    "surface": "#272E28",
    "elevated": "#303830",
    "input": "#222823",
    "hover": "#313A31",
    "pressed": "#3A453A",
    "text": "#EAEDE5",
    "text2": "#ADB6A9",
    "text3": "#8F998B",
    "accent": "#A6BE9B",
    "accent_hover": "#B5CBAA",
    "accent_pressed": "#95AE8A",
    "accent_text": "#A6BE9B",
    "accent_dark": "#829A79",
    "on_accent": "#172019",
    "accent_soft": "#39483A",
    "primary": "#A6BE9B",
    "primary_hover": "#B5CBAA",
    "primary_pressed": "#95AE8A",
    "on_primary": "#172019",
    "divider": "#3A443B",
    "border": "#475247",
    "blue": "#91AFC7",
    "blue_text": "#91AFC7",
    "blue_soft": "#2D3A44",
    "terracotta": "#D99A77",
    "terracotta_text": "#D99A77",
    "terracotta_soft": "#46352C",
    "amber": "#D8B872",
    "amber_text": "#D8B872",
    "amber_soft": "#3E3828",
    "danger": "#E0907E",
    "danger_soft": "#46302B",
    "shadow": "#000000",
    "chart_grid": "#343D35",
    "banner": "#2B342C",
}

KIND_COLORS = {
    "event": "blue",
    "class": "accent",
    "exam": "terracotta",
    "deadline": "amber",
    "task": "text3",
}


def serif(point_size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(FONT_SERIF)
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    return font


def sans(point_size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    return font


class ThemeManager(QObject):
    """Holds the active tokens and re-styles the whole app on change."""

    about_to_change = Signal()  # emitted before a visible theme switch (for the crossfade)
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.preference = "light"
        self.mode = "light"
        self.tokens: dict[str, str] = dict(LIGHT)
        self._asset_dir: Path | None = None
        self._hints_connected = False
        self.system_reduced_motion = False

    def color(self, key: str) -> QColor:
        return QColor(self.tokens.get(key, key))

    def set_asset_dir(self, path: Path) -> None:
        self._asset_dir = path

    def resolve_mode(self, preference: str) -> str:
        if preference in ("light", "dark"):
            return preference
        try:
            scheme = QGuiApplication.styleHints().colorScheme()
            return "dark" if scheme == Qt.ColorScheme.Dark else "light"
        except AttributeError:
            return "light"

    def apply(self, preference: str | None = None) -> None:
        app = QApplication.instance()
        if app is None:
            return
        if preference is not None:
            self.preference = preference
        hints = QGuiApplication.styleHints()
        try:
            # Title bar colour follows the app theme; "system" hands control back to Windows.
            if self.preference == "system":
                hints.unsetColorScheme()
            else:
                hints.setColorScheme(Qt.ColorScheme.Dark if self.preference == "dark" else Qt.ColorScheme.Light)
        except AttributeError:
            pass
        new_mode = self.resolve_mode(self.preference)
        if new_mode != self.mode and app.activeWindow() is not None:
            self.about_to_change.emit()
        self.mode = new_mode
        self.tokens = dict(DARK if self.mode == "dark" else LIGHT)
        if not self._hints_connected:
            try:
                hints.colorSchemeChanged.connect(self._on_system_scheme)
                self._hints_connected = True
            except AttributeError:
                pass
        font = QFont(FONT_FAMILY, 10)
        font.setPointSizeF(10.5)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        app.setFont(font)
        app.setPalette(self._palette())
        app.setStyleSheet(build_stylesheet(self.tokens, self._write_indicator_assets()))
        self.changed.emit()

    def _on_system_scheme(self, *_: object) -> None:
        if self.preference == "system":
            self.apply()

    def _palette(self) -> QPalette:
        t = self.tokens
        pal = QPalette()
        roles = {
            QPalette.ColorRole.Window: t["bg"], QPalette.ColorRole.WindowText: t["text"],
            QPalette.ColorRole.Base: t["input"], QPalette.ColorRole.AlternateBase: t["elevated"],
            QPalette.ColorRole.Text: t["text"], QPalette.ColorRole.Button: t["surface"],
            QPalette.ColorRole.ButtonText: t["text"], QPalette.ColorRole.Highlight: t["accent"],
            QPalette.ColorRole.HighlightedText: t["on_accent"], QPalette.ColorRole.ToolTipBase: t["surface"],
            QPalette.ColorRole.ToolTipText: t["text"], QPalette.ColorRole.PlaceholderText: t["text3"],
            QPalette.ColorRole.Link: t["accent_text"],
        }
        for role, value in roles.items():
            pal.setColor(role, QColor(value))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["text3"]))
        return pal

    def _write_indicator_assets(self) -> dict[str, str]:
        """Small SVGs for check marks and arrows, coloured for the active theme."""
        t = self.tokens
        stroke = 'fill="none" stroke-linecap="round" stroke-linejoin="round"'
        svgs = {
            "check": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" {stroke} stroke="{t["on_accent"]}" stroke-width="2"/></svg>',
            "down": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" {stroke} stroke="{t["text2"]}" stroke-width="1.6"/></svg>',
            "up": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 10l4-4 4 4" {stroke} stroke="{t["text2"]}" stroke-width="1.6"/></svg>',
            "left": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M10 4l-4 4 4 4" {stroke} stroke="{t["text"]}" stroke-width="1.6"/></svg>',
            "right": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M6 4l4 4-4 4" {stroke} stroke="{t["text"]}" stroke-width="1.6"/></svg>',
        }
        paths: dict[str, str] = {}
        if self._asset_dir is None:
            return paths
        folder = self._asset_dir / f"theme-{self.mode}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for name, svg in svgs.items():
                target = folder / f"{name}.svg"
                if not target.exists() or target.read_text(encoding="utf-8") != svg:
                    target.write_text(svg, encoding="utf-8")
                paths[name] = target.as_posix()
        except OSError:
            log.warning("Could not write theme indicator images", exc_info=True)
        return paths


theme = ThemeManager()


def build_stylesheet(t: dict[str, str], img: dict[str, str]) -> str:
    check = f"image: url({img['check']});" if "check" in img else ""
    down = f"image: url({img['down']});" if "down" in img else ""
    up = f"image: url({img['up']});" if "up" in img else ""
    left = f"qproperty-icon: url({img['left']});" if "left" in img else ""
    right = f"qproperty-icon: url({img['right']});" if "right" in img else ""
    serif = f'"{FONT_SERIF}"'
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t['text']}; font-family: "{FONT_FAMILY}"; font-size: 10.5pt; }}
QMainWindow, QWidget#AppRoot, QWidget#PageStack, QWidget#Page {{ background: {t['bg']}; }}
QScrollArea, QScrollArea > QWidget > QWidget#ScrollContent {{ background: transparent; border: none; }}
QDialog {{ background: {t['surface']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
    padding: 6px 9px; border-radius: 8px; }}

/* ---------- sidebar ---------- */
QWidget#Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['divider']}; }}
QLabel#Brand {{ font-family: {serif}; font-size: 21pt; color: {t['text']}; }}
QLabel#BrandSub {{ font-family: {serif}; font-size: 10pt; color: {t['text2']}; }}
QLabel#SidebarQuote {{ font-family: {serif}; font-size: 10.5pt; color: {t['text2']}; }}

/* ---------- typography ---------- */
QLabel[role="display"] {{ font-family: {serif}; font-size: 27pt; color: {t['text']}; }}
QLabel[role="title"] {{ font-family: {serif}; font-size: 22pt; color: {t['text']}; }}
QLabel[role="greeting"] {{ font-family: {serif}; font-size: 27pt; color: {t['text']}; }}
QLabel[role="eyebrow"] {{ font-size: 8.5pt; color: {t['text2']}; letter-spacing: 2.5px; }}
QLabel[role="subtitle"] {{ font-family: {serif}; font-size: 12.5pt; color: {t['text2']}; }}
QLabel[role="section"] {{ font-family: {serif}; font-size: 15pt; color: {t['text']}; }}
QLabel[role="heading"] {{ font-size: 11pt; font-weight: 600; color: {t['text']}; }}
QLabel[role="muted"] {{ color: {t['text2']}; }}
QLabel[role="caption"] {{ font-size: 9pt; color: {t['text3']}; }}
QLabel[role="metric"] {{ font-family: "Cambria"; font-size: 21pt; color: {t['text']}; }}
QLabel[role="metricLabel"] {{ font-size: 9pt; color: {t['text2']}; }}
QLabel[role="clock"] {{ font-family: {serif}; font-size: 13pt; color: {t['text2']}; }}
QLabel[role="timer"] {{ font-family: "Cambria"; font-size: 44pt; color: {t['text']}; }}
QLabel[role="intention"] {{ font-family: {serif}; font-size: 13pt; color: {t['text']}; }}
QLabel[role="quote"] {{ font-family: {serif}; font-style: italic; font-size: 12pt; color: {t['text2']}; }}
QLabel[role="rowtitle"] {{ font-family: {serif}; font-size: 12pt; color: {t['text']}; }}
QLabel[role="rowtitle"][past="true"] {{ color: {t['text2']}; }}
QLabel[role="rowtitle"][strike="true"] {{ color: {t['text3']}; text-decoration: line-through; }}
QLabel[role="nooktime"] {{ font-family: "Cambria"; font-size: 27pt; color: {t['text']}; }}
QLabel[role="danger"] {{ color: {t['danger']}; }}
QLabel[role="warning"] {{ color: {t['amber_text']}; }}
QLabel[role="success"] {{ color: {t['accent_text']}; }}
QLabel[role="chip"] {{ background: {t['elevated']}; color: {t['text2']}; border-radius: 8px; padding: 2px 9px; font-size: 8.5pt; }}
QLabel[role="chip"][tone="accent"] {{ background: {t['accent_soft']}; color: {t['accent_text']}; }}
QLabel[role="chip"][tone="blue"] {{ background: {t['blue_soft']}; color: {t['blue_text']}; }}
QLabel[role="chip"][tone="terracotta"] {{ background: {t['terracotta_soft']}; color: {t['terracotta_text']}; }}
QLabel[role="chip"][tone="amber"] {{ background: {t['amber_soft']}; color: {t['amber_text']}; }}
QLabel[role="chip"][tone="danger"] {{ background: {t['danger_soft']}; color: {t['danger']}; }}
QLabel[strike="true"] {{ color: {t['text3']}; text-decoration: line-through; }}

/* ---------- surfaces ---------- */
QFrame[card="true"], QFrame[panel="true"] {{ background: {t['surface']}; border: 1px solid {t['divider']}; border-radius: 16px; }}
QFrame[card="true"] QLabel, QFrame[panel="true"] QLabel {{ background: transparent; }}
QFrame[inset="true"] {{ background: {t['elevated']}; border: none; border-radius: 12px; }}
QFrame[separator="true"] {{ background: {t['divider']}; border: none; max-height: 1px; min-height: 1px; }}
QWidget#Row {{ background: transparent; border-radius: 10px; }}
QWidget#Row:hover {{ background: {t['hover']}; }}
QWidget#Row[selected="true"] {{ background: {t['accent_soft']}; }}

/* ---------- buttons (animated buttons paint themselves; these cover the rest) ---------- */
QPushButton {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
    border-radius: 10px; padding: 7px 15px; min-height: 20px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:focus {{ border: 1px solid {t['accent']}; }}
QPushButton:disabled {{ color: {t['text3']}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 5px; color: {t['text2']}; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:pressed {{ background: {t['pressed']}; }}
QToolButton:focus {{ border: 1px solid {t['accent']}; }}
QToolButton:checked {{ background: {t['accent_soft']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QComboBox {{
    background: {t['input']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 10px;
    padding: 6px 10px; selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; }}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QDateEdit:hover, QTimeEdit:hover, QComboBox:hover {{ border-color: {t['accent']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QComboBox:focus {{ border: 1px solid {t['accent_dark']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled, QComboBox:disabled,
QDoubleSpinBox:disabled {{ color: {t['text3']}; background: {t['elevated']}; border-color: {t['divider']}; }}
QLineEdit[flat="true"] {{ background: transparent; border: 1px solid transparent; padding: 4px 2px; }}
QLineEdit[flat="true"]:hover {{ border-bottom: 1px solid {t['border']}; }}
QLineEdit[flat="true"]:focus {{ border-bottom: 1px solid {t['accent']}; }}
QLineEdit[titleEdit="true"] {{ font-family: {serif}; font-size: 19pt; }}
QLineEdit[intention="true"] {{ font-family: {serif}; font-size: 13pt; background: transparent; border: none;
    border-bottom: 1px solid {t['accent']}; border-radius: 0; padding: 2px 0; }}
QLineEdit[quickadd="true"] {{ background: transparent; border: none; padding: 4px 2px; font-size: 11pt; }}
QPlainTextEdit[editor="true"] {{ background: transparent; border: none; font-size: 11.5pt; padding: 4px 2px; }}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] {{ border: 1px solid {t['danger']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ {down} width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px;
    padding: 4px; selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{ border: none; width: 18px; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow {{ {up} width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow {{ {down} width: 10px; height: 10px; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 6px; border: 1.5px solid {t['text3']}; background: {t['input']}; }}
QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; {check} }}
QCheckBox::indicator:disabled {{ border-color: {t['divider']}; }}
QCheckBox:focus {{ color: {t['accent_text']}; }}

/* ---------- lists & tables ---------- */
QListWidget, QTreeWidget, QTableWidget, QListView, QTreeView, QTableView {{
    background: transparent; border: none; outline: none; }}
QListWidget::item, QTreeWidget::item {{ padding: 6px 8px; border-radius: 10px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {t['hover']}; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
    background: {t['accent_soft']}; color: {t['text']}; }}
QHeaderView::section {{ background: transparent; color: {t['text2']}; border: none;
    border-bottom: 1px solid {t['divider']}; padding: 6px 8px; font-weight: 600; font-size: 9pt; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: none; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {t['text2']}; padding: 8px 16px; margin-right: 4px;
    border-bottom: 2px solid transparent; font-family: {serif}; font-size: 11.5pt; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; }}
QTabBar::tab:focus {{ color: {t['accent_text']}; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {t['accent']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 3px; min-width: 30px; margin: 2px 0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- menus & dialogs ---------- */
QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 7px 24px 7px 12px; border-radius: 8px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; }}
QMenu::item:disabled {{ color: {t['text3']}; }}
QMenu::separator {{ height: 1px; background: {t['divider']}; margin: 4px 6px; }}
QMessageBox, QInputDialog, QProgressDialog {{ background: {t['surface']}; }}
QMessageBox QLabel {{ color: {t['text']}; }}

/* ---------- calendar popup ---------- */
QCalendarWidget QWidget {{ alternate-background-color: {t['elevated']}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {t['elevated']}; padding: 4px; }}
QCalendarWidget QToolButton {{ color: {t['text']}; font-weight: 600; padding: 4px 8px; }}
QCalendarWidget QToolButton#qt_calendar_prevmonth {{ {left} }}
QCalendarWidget QToolButton#qt_calendar_nextmonth {{ {right} }}
QCalendarWidget QAbstractItemView:enabled {{ background: {t['surface']}; color: {t['text']};
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {t['text3']}; }}

/* ---------- toast & banners ---------- */
QFrame#Toast {{ background: {t['primary']}; border-radius: 12px; }}
QFrame#Toast QLabel {{ color: {t['on_primary']}; background: transparent; }}
QFrame#Banner {{ background: {t['banner']}; border-radius: 14px; }}
QFrame#Banner[tone="warning"] {{ background: {t['amber_soft']}; }}
QFrame#Banner QLabel {{ background: transparent; }}
"""
