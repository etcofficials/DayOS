"""DayOS design system runtime: the active theme, fonts, scale and the generated Qt stylesheet.

Themes themselves are defined in :mod:`src.ui.themes`. This module applies one:
it resolves fonts (falling back safely when a family is missing), applies the
user's text-size scale and accent choice, builds the application palette and
stylesheet, and notifies painted widgets through :attr:`ThemeManager.changed`.

Only semantic tokens are used here and by widgets (see ``themes.py``), so all
five themes share one component system.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from src.ui.themes import (
    DEFAULT_THEME,
    LEGACY_ALIASES,
    SYSTEM_PAIR,
    THEMES,
    FontSpec,
    Theme,
    get_theme,
)

log = logging.getLogger(__name__)

FONT_FAMILY = "Segoe UI"
FONT_SERIF = "Georgia"
FONT_SCALES = (0.9, 1.0, 1.1, 1.25)

# Kept for compatibility with v1 code and tests: the two original palettes.
LIGHT: dict[str, str] = THEMES["paper"].palette()
DARK: dict[str, str] = THEMES["midnight"].palette()

KIND_COLORS = {
    "event": "blue",
    "class": "accent",
    "exam": "terracotta",
    "deadline": "amber",
    "task": "text3",
    "study": "accent",
    "revision": "terracotta",
    "reminder": "amber",
}

_family_cache: dict[tuple[str, ...], str] = {}


def resolve_family(spec: FontSpec) -> str:
    """The first installed family among ``spec.family`` and its fallbacks."""
    candidates = (spec.family, *spec.fallbacks)
    if candidates in _family_cache:
        return _family_cache[candidates]
    chosen = spec.family
    try:
        installed = set(QFontDatabase.families())
        if installed:  # an empty list means fonts aren't queryable yet (e.g. offscreen tests)
            chosen = next((f for f in candidates if f in installed), spec.fallbacks[-1] if spec.fallbacks else spec.family)
    except Exception:  # font database unavailable: keep the preferred family; Qt substitutes
        log.debug("Font database unavailable", exc_info=True)
    _family_cache[candidates] = chosen
    return chosen


def _qt_weight(css_weight: int) -> QFont.Weight:
    return QFont.Weight(max(100, min(900, int(css_weight))))


def _font(spec: FontSpec, point_size: float, weight: QFont.Weight | int | None = None) -> QFont:
    font = QFont(resolve_family(spec))
    font.setPointSizeF(point_size * theme.scale)
    if weight is None:
        font.setWeight(_qt_weight(spec.weight))
    else:
        font.setWeight(QFont.Weight(int(weight)))
    return font


def serif(point_size: float, weight: QFont.Weight | None = None) -> QFont:
    """The active theme's display face (an editorial serif in Paper & Sage and Espresso)."""
    return _font(theme.theme.fonts.display, point_size, weight)


def heading_font(point_size: float, weight: QFont.Weight | None = None) -> QFont:
    return _font(theme.theme.fonts.heading, point_size, weight)


def nav_font() -> QFont:
    spec = theme.theme.fonts.heading
    weight = 400 if spec.weight >= 600 else spec.weight
    return _font(FontSpec(spec.family, weight, spec.fallbacks), theme.theme.fonts.nav_size)


def numeric_font(point_size: float, weight: QFont.Weight | None = None) -> QFont:
    return _font(theme.theme.fonts.numeric, point_size, weight)


def sans(point_size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return _font(theme.theme.fonts.body, point_size, weight)


def mono(point_size: float = 10.0) -> QFont:
    font = _font(theme.theme.fonts.mono, point_size, QFont.Weight.Normal)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


class ThemeManager(QObject):
    """Holds the active theme and re-styles the whole app on change."""

    about_to_change = Signal()  # emitted before a visible theme switch (for the crossfade)
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.preference = DEFAULT_THEME
        self.theme: Theme = THEMES[DEFAULT_THEME]
        self.accent: str | None = None
        self.scale = 1.0
        self.tokens: dict[str, str] = self.theme.palette()
        self._asset_dir: Path | None = None
        self._hints_connected = False
        self.system_reduced_motion = False

    # -- read access ------------------------------------------------------------
    @property
    def id(self) -> str:
        return self.theme.id

    @property
    def mode(self) -> str:
        return self.theme.mode

    @property
    def shape(self):
        return self.theme.shape

    def color(self, key: str) -> QColor:
        return QColor(self.tokens.get(key, key))

    def art_name(self, slot: str) -> str:
        return self.theme.art_variants.get(slot, slot)

    def set_asset_dir(self, path: Path) -> None:
        self._asset_dir = path

    # -- resolution ---------------------------------------------------------------
    def resolve(self, preference: str | None) -> Theme:
        pref = LEGACY_ALIASES.get(preference or "", preference or DEFAULT_THEME)
        if pref == "system":
            try:
                dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
            except AttributeError:
                dark = False
            return THEMES[SYSTEM_PAIR[1] if dark else SYSTEM_PAIR[0]]
        return get_theme(pref)

    def resolve_mode(self, preference: str) -> str:
        return self.resolve(preference).mode

    # -- applying -------------------------------------------------------------------
    def configure(self, *, accent: str | None = None, scale: float | None = None) -> None:
        """Set accent / text scale without re-applying (call :meth:`apply` afterwards)."""
        self.accent = accent or None
        if scale is not None:
            self.scale = scale if scale in FONT_SCALES else 1.0

    def apply(self, preference: str | None = None, *, accent: str | None | bool = False,
              scale: float | None = None) -> None:
        app = QApplication.instance()
        if app is None:
            return
        if preference is not None:
            self.preference = preference
        if accent is not False:
            self.accent = accent or None  # type: ignore[assignment]
        if scale is not None:
            self.scale = scale if scale in FONT_SCALES else 1.0
        new_theme = self.resolve(self.preference)
        hints = QGuiApplication.styleHints()
        try:
            # Title bar colour follows the app theme; "system" hands control back to Windows.
            if self.preference == "system":
                hints.unsetColorScheme()
            else:
                hints.setColorScheme(Qt.ColorScheme.Dark if new_theme.mode == "dark" else Qt.ColorScheme.Light)
        except AttributeError:
            pass
        new_tokens = new_theme.palette(self.accent)
        if (new_theme.id != self.theme.id or new_tokens != self.tokens) and app.activeWindow() is not None:
            self.about_to_change.emit()
        self.theme = new_theme
        self.tokens = new_tokens
        if not self._hints_connected:
            try:
                hints.colorSchemeChanged.connect(self._on_system_scheme)
                self._hints_connected = True
            except AttributeError:
                pass
        body = new_theme.fonts.body
        font = QFont(resolve_family(body))
        font.setPointSizeF(10.5 * self.scale)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        app.setFont(font)
        app.setPalette(self._palette())
        app.setStyleSheet(build_stylesheet(self.tokens, self._write_indicator_assets(), new_theme, self.scale))
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
            QPalette.ColorRole.ButtonText: t["text"], QPalette.ColorRole.Highlight: t["selection"],
            QPalette.ColorRole.HighlightedText: t["text"], QPalette.ColorRole.ToolTipBase: t["surface"],
            QPalette.ColorRole.ToolTipText: t["text"], QPalette.ColorRole.PlaceholderText: t["text3"],
            QPalette.ColorRole.Link: t["accent_text"], QPalette.ColorRole.BrightText: t["on_primary"],
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
            "radio": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3.2" fill="{t["on_accent"]}"/></svg>',
        }
        paths: dict[str, str] = {}
        if self._asset_dir is None:
            return paths
        tag = f"{self.theme.id}-{self.accent or 'default'}"
        folder = self._asset_dir / f"theme-{tag}"
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


def _css_font(spec: FontSpec) -> str:
    fallbacks = ", ".join(f'"{f}"' for f in spec.fallbacks)
    return f'"{resolve_family(spec)}", {fallbacks}' if fallbacks else f'"{resolve_family(spec)}"'


def build_stylesheet(t: dict[str, str], img: dict[str, str], th: Theme | None = None, scale: float = 1.0) -> str:
    th = th or THEMES[DEFAULT_THEME]
    f = th.fonts
    r = th.shape

    def pt(size: float) -> str:
        return f"{size * scale:.2f}pt"

    check = f"image: url({img['check']});" if "check" in img else ""
    radio = f"image: url({img['radio']});" if "radio" in img else ""
    down = f"image: url({img['down']});" if "down" in img else ""
    up = f"image: url({img['up']});" if "up" in img else ""
    left = f"qproperty-icon: url({img['left']});" if "left" in img else ""
    right = f"qproperty-icon: url({img['right']});" if "right" in img else ""
    display = _css_font(f.display)
    dw = f.display.weight
    heading = _css_font(f.heading)
    hw = f.heading.weight
    body = _css_font(f.body)
    numeric = _css_font(f.numeric)
    nw = f.numeric.weight
    mono_family = _css_font(f.mono)
    cr = int(r.control_radius)
    card = int(r.card_radius)
    small = max(4, cr - 2)
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t['text']}; font-family: {body}; font-size: {pt(10.5)}; }}
QMainWindow, QWidget#AppRoot, QWidget#PageStack, QWidget#Page {{ background: {t['bg']}; }}
QScrollArea, QScrollArea > QWidget > QWidget#ScrollContent {{ background: transparent; border: none; }}
QDialog {{ background: {t['surface']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
    padding: 6px 9px; border-radius: {small}px; }}

/* ---------- sidebar ---------- */
QWidget#Sidebar {{ background: {t['sidebar']}; }}
QLabel#Brand {{ font-family: {display}; font-weight: {dw}; font-size: {pt(20)}; color: {t['text']}; }}
QLabel#BrandSub {{ font-family: {heading}; font-size: {pt(9.5)}; color: {t['text2']}; }}
QLabel#SidebarQuote {{ font-family: {display}; font-size: {pt(10.5)}; color: {t['text2']}; }}
QLabel#NavGroup {{ font-size: {pt(8)}; color: {t['text3']}; letter-spacing: {f.eyebrow_spacing}px; padding-left: 14px; }}

/* ---------- typography ---------- */
QLabel[role="display"] {{ font-family: {display}; font-weight: {dw}; font-size: {pt(27)}; color: {t['text']}; }}
QLabel[role="title"] {{ font-family: {display}; font-weight: {dw}; font-size: {pt(22)}; color: {t['text']}; }}
QLabel[role="greeting"] {{ font-family: {display}; font-weight: {dw}; font-size: {pt(27)}; color: {t['text']}; }}
QLabel[role="eyebrow"] {{ font-size: {pt(8.5)}; color: {t['text2']}; letter-spacing: {f.eyebrow_spacing}px; }}
QLabel[role="subtitle"] {{ font-family: {display}; font-size: {pt(12)}; color: {t['text2']}; }}
QLabel[role="section"] {{ font-family: {heading}; font-weight: {hw}; font-size: {pt(14.5 if hw < 600 else 12.5)}; color: {t['text']}; }}
QLabel[role="heading"] {{ font-size: {pt(11)}; font-weight: 600; color: {t['text']}; }}
QLabel[role="muted"] {{ color: {t['text2']}; }}
QLabel[role="caption"] {{ font-size: {pt(9)}; color: {t['text3']}; }}
QLabel[role="metric"] {{ font-family: {numeric}; font-weight: {nw}; font-size: {pt(21)}; color: {t['text']}; }}
QLabel[role="metricLabel"] {{ font-size: {pt(9)}; color: {t['text2']}; }}
QLabel[role="clock"] {{ font-family: {display}; font-size: {pt(13)}; color: {t['text2']}; }}
QLabel[role="timer"] {{ font-family: {numeric}; font-weight: {nw}; font-size: {pt(44)}; color: {t['text']}; }}
QLabel[role="intention"] {{ font-family: {display}; font-size: {pt(13)}; color: {t['text']}; }}
QLabel[role="quote"] {{ font-family: {display}; font-style: italic; font-size: {pt(12)}; color: {t['text2']}; }}
QLabel[role="rowtitle"] {{ font-family: {heading}; font-size: {pt(12 if hw < 600 else 10.5)}; color: {t['text']}; }}
QLabel[role="rowtitle"][past="true"] {{ color: {t['text2']}; }}
QLabel[role="rowtitle"][strike="true"] {{ color: {t['text3']}; text-decoration: line-through; }}
QLabel[role="nooktime"] {{ font-family: {numeric}; font-weight: {nw}; font-size: {pt(27)}; color: {t['text']}; }}
QLabel[role="mono"] {{ font-family: {mono_family}; font-size: {pt(9.5)}; color: {t['text']}; }}
QLabel[role="danger"] {{ color: {t['danger']}; }}
QLabel[role="warning"] {{ color: {t['amber_text']}; }}
QLabel[role="success"] {{ color: {t['success']}; }}
QLabel[role="link"] {{ color: {t['accent_text']}; }}
QLabel[role="chip"] {{ background: {t['elevated']}; color: {t['text2']}; border-radius: {small}px; padding: 2px 9px; font-size: {pt(8.5)}; }}
QLabel[role="chip"][tone="accent"] {{ background: {t['accent_soft']}; color: {t['accent_text']}; }}
QLabel[role="chip"][tone="blue"] {{ background: {t['blue_soft']}; color: {t['blue_text']}; }}
QLabel[role="chip"][tone="terracotta"] {{ background: {t['terracotta_soft']}; color: {t['terracotta_text']}; }}
QLabel[role="chip"][tone="amber"] {{ background: {t['amber_soft']}; color: {t['amber_text']}; }}
QLabel[role="chip"][tone="danger"] {{ background: {t['danger_soft']}; color: {t['danger']}; }}
QLabel[strike="true"] {{ color: {t['text3']}; text-decoration: line-through; }}

/* ---------- surfaces ---------- */
QFrame[card="true"], QFrame[panel="true"] {{ background: {t['surface']}; border: 1px solid {t['divider']}; border-radius: {card}px; }}
QFrame[card="true"] QLabel, QFrame[panel="true"] QLabel {{ background: transparent; }}
QFrame[inset="true"] {{ background: {t['elevated']}; border: none; border-radius: {max(6, card - 4)}px; }}
QFrame[separator="true"] {{ background: {t['divider']}; border: none; max-height: 1px; min-height: 1px; }}
QWidget#Row {{ background: transparent; border-radius: {cr}px; }}
QWidget#Row:hover {{ background: {t['hover']}; }}
QWidget#Row[selected="true"] {{ background: {t['accent_soft']}; }}

/* ---------- buttons (animated buttons paint themselves; these cover the rest) ---------- */
QPushButton {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
    border-radius: {cr}px; padding: 7px 15px; min-height: 20px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:focus {{ border: 1px solid {t['focus']}; }}
QPushButton:disabled {{ color: {t['text3']}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {max(6, cr - 1)}px; padding: 5px; color: {t['text2']}; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:pressed {{ background: {t['pressed']}; }}
QToolButton:focus {{ border: 1px solid {t['focus']}; }}
QToolButton:checked {{ background: {t['accent_soft']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit, QComboBox {{
    background: {t['input']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: {cr}px;
    padding: 6px 10px; selection-background-color: {t['selection']}; selection-color: {t['text']}; }}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QDateEdit:hover, QTimeEdit:hover, QDateTimeEdit:hover, QComboBox:hover {{ border-color: {t['accent']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus, QComboBox:focus {{ border: 1px solid {t['accent_dark']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled, QComboBox:disabled,
QDoubleSpinBox:disabled, QDateTimeEdit:disabled {{ color: {t['text3']}; background: {t['elevated']}; border-color: {t['divider']}; }}
QLineEdit[flat="true"] {{ background: transparent; border: 1px solid transparent; padding: 4px 2px; }}
QLineEdit[flat="true"]:hover {{ border-bottom: 1px solid {t['border']}; }}
QLineEdit[flat="true"]:focus {{ border-bottom: 1px solid {t['accent']}; }}
QLineEdit[titleEdit="true"] {{ font-family: {display}; font-weight: {dw}; font-size: {pt(19)}; }}
QLineEdit[intention="true"] {{ font-family: {display}; font-size: {pt(13)}; background: transparent; border: none;
    border-bottom: 1px solid {t['accent']}; border-radius: 0; padding: 2px 0; }}
QLineEdit[quickadd="true"] {{ background: transparent; border: none; padding: 4px 2px; font-size: {pt(11)}; }}
QLineEdit[palette="true"] {{ background: transparent; border: none; padding: 8px 4px; font-size: {pt(13)}; }}
QPlainTextEdit[editor="true"], QTextEdit[editor="true"] {{ background: transparent; border: none; font-size: {pt(11.5)}; padding: 4px 2px; }}
QPlainTextEdit[code="true"], QTextEdit[code="true"] {{ font-family: {mono_family}; font-size: {pt(10)}; }}
QTextBrowser {{ background: transparent; border: none; padding: 2px; }}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] {{ border: 1px solid {t['danger']}; }}
QComboBox::drop-down, QDateEdit::drop-down, QDateTimeEdit::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow, QDateEdit::down-arrow, QDateTimeEdit::down-arrow {{ {down} width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {cr}px;
    padding: 4px; selection-background-color: {t['selection']}; selection-color: {t['text']}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{ border: none; width: 18px; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow {{ {up} width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow {{ {down} width: 10px; height: 10px; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: {max(3, small - 2)}px; border: 1.5px solid {t['text3']}; background: {t['input']}; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; {check} }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: {t['divider']}; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 8px; border: 1.5px solid {t['text3']}; background: {t['input']}; }}
QRadioButton::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; {radio} }}
QCheckBox:focus, QRadioButton:focus {{ color: {t['accent_text']}; }}

QSlider::groove:horizontal {{ height: 4px; background: {t['track']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['progress']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; background: {t['surface']}; border: 2px solid {t['accent']}; }}
QProgressBar {{ background: {t['track']}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t['progress']}; border-radius: 4px; }}

/* ---------- lists & tables ---------- */
QListWidget, QTreeWidget, QTableWidget, QListView, QTreeView, QTableView {{
    background: transparent; border: none; outline: none; alternate-background-color: {t['elevated']}; }}
QListWidget::item, QTreeWidget::item {{ padding: 6px 8px; border-radius: {cr}px; }}
QTableWidget::item, QTableView::item {{ padding: 4px 8px; }}
QListWidget::item:hover, QTreeWidget::item:hover, QTableWidget::item:hover {{ background: {t['hover']}; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected, QTableView::item:selected {{
    background: {t['selection']}; color: {t['text']}; }}
QTreeView::branch {{ background: transparent; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {t['text2']}; border: none;
    border-bottom: 1px solid {t['divider']}; padding: 6px 8px; font-weight: 600; font-size: {pt(9)}; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: none; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {t['text2']}; padding: 8px 16px; margin-right: 4px;
    border-bottom: 2px solid transparent; font-family: {heading}; font-size: {pt(11.5 if hw < 600 else 10.5)}; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; }}
QTabBar::tab:focus {{ color: {t['accent_text']}; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {t['accent']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 3px; min-width: 30px; margin: 2px 0; }}
QScrollBar::handle:horizontal:hover {{ background: {t['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- menus & dialogs ---------- */
QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {cr + 2}px; padding: 6px; }}
QMenu::item {{ padding: 7px 24px 7px 12px; border-radius: {max(4, cr - 2)}px; }}
QMenu::item:selected {{ background: {t['selection']}; }}
QMenu::item:disabled {{ color: {t['text3']}; }}
QMenu::separator {{ height: 1px; background: {t['divider']}; margin: 4px 6px; }}
QMenu::indicator {{ width: 14px; height: 14px; }}
QMessageBox, QInputDialog, QProgressDialog, QFileDialog {{ background: {t['surface']}; }}
QMessageBox QLabel {{ color: {t['text']}; }}

/* ---------- calendar popup ---------- */
QCalendarWidget QWidget {{ alternate-background-color: {t['elevated']}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {t['elevated']}; padding: 4px; }}
QCalendarWidget QToolButton {{ color: {t['text']}; font-weight: 600; padding: 4px 8px; }}
QCalendarWidget QToolButton#qt_calendar_prevmonth {{ {left} }}
QCalendarWidget QToolButton#qt_calendar_nextmonth {{ {right} }}
QCalendarWidget QAbstractItemView:enabled {{ background: {t['surface']}; color: {t['text']};
    selection-background-color: {t['primary']}; selection-color: {t['on_primary']}; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {t['text3']}; }}

/* ---------- toast & banners ---------- */
QFrame#Toast {{ background: {t['primary']}; border-radius: {cr + 2}px; }}
QFrame#Toast QLabel {{ color: {t['on_primary']}; background: transparent; }}
QFrame#Banner {{ background: {t['banner']}; border-radius: {max(8, card - 2)}px; }}
QFrame#Banner[tone="warning"] {{ background: {t['amber_soft']}; }}
QFrame#Banner[tone="danger"] {{ background: {t['danger_soft']}; }}
QFrame#Banner[tone="info"] {{ background: {t['blue_soft']}; }}
QFrame#Banner QLabel {{ background: transparent; }}
"""


__all__ = [
    "DARK", "FONT_FAMILY", "FONT_SCALES", "FONT_SERIF", "KIND_COLORS", "LIGHT", "ThemeManager", "build_stylesheet",
    "heading_font", "mono", "nav_font", "numeric_font", "resolve_family", "sans", "serif", "theme",
]
