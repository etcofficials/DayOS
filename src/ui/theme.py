"""DayOS design system: color tokens, typography and the generated Qt stylesheet.

Palette notes (WCAG contrast measured against the main surface):
* Dark: primary text 12.5:1, secondary 6.7:1, sage accent 7.0:1.
* Light: primary text 13.5:1, secondary 5.5:1, sage accent 5.2:1 (the
  suggested #617D60 was darkened to #58745A to keep button text above 4.5:1).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

FONT_FAMILY = "Segoe UI"

DARK: dict[str, str] = {
    "bg": "#171A18",
    "sidebar": "#1D211E",
    "surface": "#242925",
    "elevated": "#2B312C",
    "input": "#1F2320",
    "hover": "#2F3630",
    "pressed": "#353D36",
    "text": "#E9EDE7",
    "text2": "#A8B0A7",
    "text3": "#8A938A",
    "accent": "#A3B99C",
    "accent_hover": "#B6C9AF",
    "accent_pressed": "#92AA8B",
    "on_accent": "#16201A",
    "accent_soft": "#343F34",
    "divider": "#383F39",
    "border": "#434B44",
    "blue": "#94AFC8",
    "blue_soft": "#2C3640",
    "terracotta": "#D69A80",
    "terracotta_soft": "#3F312B",
    "amber": "#D8B872",
    "amber_soft": "#3B3528",
    "danger": "#E0907E",
    "danger_soft": "#43302B",
    "shadow": "#0C0E0D",
    "chart_grid": "#323933",
}

LIGHT: dict[str, str] = {
    "bg": "#F5F4EF",
    "sidebar": "#ECEDE5",
    "surface": "#FFFFFF",
    "elevated": "#F9F8F3",
    "input": "#FFFFFF",
    "hover": "#EEEFE7",
    "pressed": "#E4E6DC",
    "text": "#2B302B",
    "text2": "#626A61",
    "text3": "#737B71",
    "accent": "#58745A",
    "accent_hover": "#4C6750",
    "accent_pressed": "#425B45",
    "on_accent": "#FFFFFF",
    "accent_soft": "#E5ECE1",
    "divider": "#E2E4DA",
    "border": "#D3D6CA",
    "blue": "#4F6F8F",
    "blue_soft": "#E3EAF1",
    "terracotta": "#A85C43",
    "terracotta_soft": "#F5E6DF",
    "amber": "#8C6A1F",
    "amber_soft": "#F4ECD9",
    "danger": "#A9483A",
    "danger_soft": "#F6E2DD",
    "shadow": "#C9CBBF",
    "chart_grid": "#ECEDE5",
}

KIND_COLORS = {
    "event": "blue",
    "class": "accent",
    "exam": "terracotta",
    "deadline": "amber",
    "task": "text2",
}


class ThemeManager(QObject):
    """Holds the active tokens and re-styles the whole app on change."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.preference = "system"
        self.mode = "dark"
        self.tokens: dict[str, str] = dict(DARK)
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
            return "light" if scheme == Qt.ColorScheme.Light else "dark"
        except AttributeError:
            return "dark"

    def apply(self, preference: str | None = None) -> None:
        app = QApplication.instance()
        if app is None:
            return
        if preference is not None:
            self.preference = preference
        self.mode = self.resolve_mode(self.preference)
        self.tokens = dict(DARK if self.mode == "dark" else LIGHT)
        if not self._hints_connected:
            try:
                QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
                self._hints_connected = True
            except AttributeError:
                pass
        font = QFont(FONT_FAMILY, 10)
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
        pal.setColor(QPalette.ColorRole.Window, QColor(t["bg"]))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(t["text"]))
        pal.setColor(QPalette.ColorRole.Base, QColor(t["input"]))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t["elevated"]))
        pal.setColor(QPalette.ColorRole.Text, QColor(t["text"]))
        pal.setColor(QPalette.ColorRole.Button, QColor(t["elevated"]))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(t["text"]))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(t["accent"]))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t["on_accent"]))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t["elevated"]))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t["text"]))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["text3"]))
        pal.setColor(QPalette.ColorRole.Link, QColor(t["accent"]))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["text3"]))
        return pal

    def _write_indicator_assets(self) -> dict[str, str]:
        """Small SVGs for check marks and arrows, colored for the active theme."""
        t = self.tokens
        svgs = {
            "check": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="{t["on_accent"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            "down": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" fill="none" stroke="{t["text2"]}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            "up": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 10l4-4 4 4" fill="none" stroke="{t["text2"]}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            "left": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M10 4l-4 4 4 4" fill="none" stroke="{t["text"]}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            "right": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M6 4l4 4-4 4" fill="none" stroke="{t["text"]}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
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
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t['text']}; font-family: "{FONT_FAMILY}"; font-size: 10pt; }}
QMainWindow, QWidget#AppRoot, QWidget#PageStack, QWidget#Page {{ background: {t['bg']}; }}
QScrollArea, QScrollArea > QWidget > QWidget#ScrollContent {{ background: transparent; border: none; }}
QDialog {{ background: {t['surface']}; }}
QToolTip {{ background: {t['elevated']}; color: {t['text']}; border: 1px solid {t['border']};
    padding: 5px 8px; border-radius: 6px; }}

/* ---------- sidebar ---------- */
QWidget#Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['divider']}; }}
QLabel#Brand {{ font-size: 15pt; font-weight: 600; color: {t['text']}; }}
QLabel#BrandSub {{ font-size: 8.5pt; color: {t['text3']}; }}
QToolButton#NavButton {{ background: transparent; border: none; border-radius: 8px; color: {t['text2']};
    padding: 8px 10px; text-align: left; font-size: 10pt; }}
QToolButton#NavButton:hover {{ background: {t['hover']}; color: {t['text']}; }}
QToolButton#NavButton:checked {{ background: {t['accent_soft']}; color: {t['text']}; font-weight: 600; }}
QToolButton#NavButton:focus {{ border: 1px solid {t['accent']}; }}
QToolButton#CollapseButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px; }}
QToolButton#CollapseButton:hover {{ background: {t['hover']}; }}
QToolButton#CollapseButton:focus {{ border: 1px solid {t['accent']}; }}

/* ---------- typography ---------- */
QLabel[role="title"] {{ font-size: 19pt; font-weight: 600; color: {t['text']}; }}
QLabel[role="greeting"] {{ font-size: 21pt; font-weight: 600; color: {t['text']}; }}
QLabel[role="subtitle"] {{ font-size: 10.5pt; color: {t['text2']}; }}
QLabel[role="section"] {{ font-size: 11pt; font-weight: 600; color: {t['text']}; }}
QLabel[role="muted"] {{ color: {t['text2']}; }}
QLabel[role="caption"] {{ font-size: 9pt; color: {t['text3']}; }}
QLabel[role="metric"] {{ font-size: 20pt; font-weight: 600; color: {t['text']}; }}
QLabel[role="metricLabel"] {{ font-size: 9pt; color: {t['text2']}; }}
QLabel[role="clock"] {{ font-size: 13pt; color: {t['text2']}; }}
QLabel[role="timer"] {{ font-size: 54pt; font-weight: 300; color: {t['text']}; }}
QLabel[role="danger"] {{ color: {t['danger']}; }}
QLabel[role="warning"] {{ color: {t['amber']}; }}
QLabel[role="success"] {{ color: {t['accent']}; }}
QLabel[role="chip"] {{ background: {t['elevated']}; color: {t['text2']}; border-radius: 6px; padding: 1px 7px; font-size: 8.5pt; }}
QLabel[role="chip"][tone="accent"] {{ background: {t['accent_soft']}; color: {t['accent']}; }}
QLabel[role="chip"][tone="blue"] {{ background: {t['blue_soft']}; color: {t['blue']}; }}
QLabel[role="chip"][tone="terracotta"] {{ background: {t['terracotta_soft']}; color: {t['terracotta']}; }}
QLabel[role="chip"][tone="amber"] {{ background: {t['amber_soft']}; color: {t['amber']}; }}
QLabel[role="chip"][tone="danger"] {{ background: {t['danger_soft']}; color: {t['danger']}; }}
QLabel[strike="true"] {{ color: {t['text3']}; text-decoration: line-through; }}

/* ---------- surfaces ---------- */
QFrame[card="true"] {{ background: {t['surface']}; border: 1px solid {t['divider']}; border-radius: 12px; }}
QFrame[card="true"] QLabel {{ background: transparent; }}
QFrame[panel="true"] {{ background: {t['surface']}; border: 1px solid {t['divider']}; border-radius: 12px; }}
QFrame[inset="true"] {{ background: {t['elevated']}; border: none; border-radius: 10px; }}
QFrame[separator="true"] {{ background: {t['divider']}; border: none; max-height: 1px; min-height: 1px; }}
QWidget#Row {{ background: transparent; border-radius: 8px; }}
QWidget#Row:hover {{ background: {t['hover']}; }}
QWidget#Row[selected="true"] {{ background: {t['accent_soft']}; }}

/* ---------- buttons ---------- */
QPushButton {{ background: {t['elevated']}; color: {t['text']}; border: 1px solid {t['border']};
    border-radius: 8px; padding: 6px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:focus {{ border: 1px solid {t['accent']}; }}
QPushButton:disabled {{ color: {t['text3']}; background: {t['elevated']}; border-color: {t['divider']}; }}
QPushButton[variant="primary"] {{ background: {t['accent']}; color: {t['on_accent']}; border: 1px solid {t['accent']}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
QPushButton[variant="primary"]:pressed {{ background: {t['accent_pressed']}; }}
QPushButton[variant="primary"]:focus {{ border: 2px solid {t['text']}; }}
QPushButton[variant="primary"]:disabled {{ background: {t['accent_soft']}; color: {t['text3']}; border-color: {t['accent_soft']}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {t['text2']}; }}
QPushButton[variant="ghost"]:hover {{ background: {t['hover']}; color: {t['text']}; }}
QPushButton[variant="ghost"]:focus {{ border: 1px solid {t['accent']}; }}
QPushButton[variant="danger"] {{ background: {t['danger_soft']}; color: {t['danger']}; border: 1px solid {t['danger_soft']}; }}
QPushButton[variant="danger"]:hover {{ border-color: {t['danger']}; }}
QPushButton[variant="link"] {{ background: transparent; border: none; color: {t['accent']}; padding: 2px 4px; }}
QPushButton[variant="link"]:hover {{ text-decoration: underline; }}
QPushButton[variant="link"]:focus {{ border: 1px solid {t['accent']}; }}
QPushButton[segment="true"] {{ background: transparent; border: 1px solid transparent; color: {t['text2']}; padding: 5px 12px; }}
QPushButton[segment="true"]:hover {{ background: {t['hover']}; color: {t['text']}; }}
QPushButton[segment="true"]:checked {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; font-weight: 600; }}
QPushButton[segment="true"]:focus {{ border: 1px solid {t['accent']}; }}
QFrame#SegmentBar {{ background: {t['elevated']}; border: 1px solid {t['divider']}; border-radius: 9px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 4px; color: {t['text2']}; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:pressed {{ background: {t['pressed']}; }}
QToolButton:focus {{ border: 1px solid {t['accent']}; }}
QToolButton:checked {{ background: {t['accent_soft']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QComboBox {{
    background: {t['input']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 8px;
    padding: 5px 9px; selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QDateEdit:hover, QTimeEdit:hover, QComboBox:hover {{ border-color: {t['text3']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled, QComboBox:disabled,
QDoubleSpinBox:disabled {{ color: {t['text3']}; background: {t['elevated']}; border-color: {t['divider']}; }}
QLineEdit[flat="true"] {{ background: transparent; border: 1px solid transparent; padding: 4px 2px; }}
QLineEdit[flat="true"]:hover {{ border-bottom: 1px solid {t['border']}; }}
QLineEdit[flat="true"]:focus {{ border-bottom: 1px solid {t['accent']}; }}
QLineEdit[titleEdit="true"] {{ font-size: 16pt; font-weight: 600; }}
QPlainTextEdit[editor="true"] {{ background: transparent; border: none; font-size: 11pt; padding: 4px 2px; }}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] {{ border: 1px solid {t['danger']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ {down} width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t['elevated']}; border: 1px solid {t['border']}; border-radius: 8px;
    padding: 4px; selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{ border: none; width: 18px; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow {{ {up} width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow {{ {down} width: 10px; height: 10px; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1.5px solid {t['text3']}; background: {t['input']}; }}
QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; {check} }}
QCheckBox::indicator:disabled {{ border-color: {t['divider']}; }}
QCheckBox:focus {{ color: {t['accent']}; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1.5px solid {t['text3']}; background: {t['input']}; }}
QRadioButton::indicator:checked {{ background: {t['accent']}; border: 4px solid {t['input']}; outline: 1px solid {t['accent']}; }}

/* ---------- lists & tables ---------- */
QListWidget, QTreeWidget, QTableWidget, QListView, QTreeView, QTableView {{
    background: transparent; border: none; outline: none; }}
QListWidget::item, QTreeWidget::item {{ padding: 6px 8px; border-radius: 7px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {t['hover']}; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
    background: {t['accent_soft']}; color: {t['text']}; }}
QTableWidget {{ gridline-color: {t['divider']}; }}
QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {t['divider']}; }}
QHeaderView::section {{ background: transparent; color: {t['text2']}; border: none;
    border-bottom: 1px solid {t['divider']}; padding: 6px 8px; font-weight: 600; font-size: 9pt; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: none; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {t['text2']}; padding: 8px 14px; margin-right: 4px;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; font-weight: 600; }}
QTabBar::tab:focus {{ color: {t['accent']}; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {t['text3']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 3px; min-width: 30px; margin: 2px 0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- menus & dialogs ---------- */
QMenu {{ background: {t['elevated']}; border: 1px solid {t['border']}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; }}
QMenu::item:disabled {{ color: {t['text3']}; }}
QMenu::separator {{ height: 1px; background: {t['divider']}; margin: 4px 6px; }}
QMessageBox {{ background: {t['surface']}; }}
QMessageBox QLabel {{ color: {t['text']}; }}
QProgressDialog {{ background: {t['surface']}; }}

/* ---------- calendar popup ---------- */
QCalendarWidget QWidget {{ alternate-background-color: {t['elevated']}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {t['elevated']}; padding: 4px; }}
QCalendarWidget QToolButton {{ color: {t['text']}; font-weight: 600; padding: 4px 8px; }}
QCalendarWidget QToolButton#qt_calendar_prevmonth {{ {left} }}
QCalendarWidget QToolButton#qt_calendar_nextmonth {{ {right} }}
QCalendarWidget QAbstractItemView:enabled {{ background: {t['surface']}; color: {t['text']};
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {t['text3']}; }}
QCalendarWidget QSpinBox {{ padding: 2px 4px; }}

/* ---------- toast ---------- */
QFrame#Toast {{ background: {t['text']}; border-radius: 10px; }}
QFrame#Toast QLabel {{ color: {t['bg']}; background: transparent; }}
QFrame#Toast QPushButton {{ background: transparent; color: {t['bg']}; border: 1px solid transparent;
    font-weight: 600; padding: 3px 10px; }}
QFrame#Toast QPushButton:hover {{ border-color: {t['bg']}; }}
QFrame#Banner {{ background: {t['accent_soft']}; border-radius: 10px; }}
QFrame#Banner[tone="warning"] {{ background: {t['amber_soft']}; }}
QFrame#Banner QLabel {{ background: transparent; }}
"""
