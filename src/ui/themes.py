"""The DayOS theme registry: five themes built on one shared set of semantic tokens.

Every widget and the generated stylesheet read *semantic* tokens only (``bg``,
``surface``, ``text2``, ``accent_text``, ``track`` …), never raw colours, so a
theme can be refined here without touching any page.

Each :class:`Theme` defines

* ``tokens``: the colour palette. Core colours are written out by hand; the
  rest (hover/pressed states, chart grid, progress track …) are derived by
  :func:`complete_tokens` unless a theme overrides them.
* ``fonts``: display (page titles), heading (sections, navigation), body and
  numeric families with weights. Only fonts that ship with Windows 10/11 are
  used, each with a safe fallback (see :func:`resolve_family`).
* ``shape``: corner radii and shadow strength.
* ``art``: how the bundled botanical artwork is recoloured, plus optional
  per-theme replacements for individual illustrations (``art_variants``).
* ``accents``: optional accent colour sets the user may choose. Each one has
  been contrast-checked (see tests/test_themes.py) so readability holds.

Contrast targets (WCAG 2.1, checked by the tests against ``surface`` and
``bg``): ``text``, ``text2``, ``text3``, ``accent_text`` and every ``*_text``
token ≥ 4.5:1; ``on_primary`` on ``primary`` ≥ 4.5:1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_THEME = "paper"
LEGACY_ALIASES = {"light": "paper", "dark": "midnight"}
SYSTEM_PAIR = ("paper", "midnight")  # "Match Windows" uses these for light / dark


@dataclass(frozen=True)
class FontSpec:
    family: str
    weight: int = 400  # CSS-style weight (300 light … 700 bold)
    fallbacks: tuple[str, ...] = ("Segoe UI",)


@dataclass(frozen=True)
class Fonts:
    display: FontSpec
    heading: FontSpec
    body: FontSpec = FontSpec("Segoe UI", 400, ("Arial",))
    numeric: FontSpec = FontSpec("Cambria", 400, ("Georgia", "Segoe UI"))
    mono: FontSpec = FontSpec("Consolas", 400, ("Courier New",))
    nav_size: float = 11.0  # sidebar label size (pt)
    eyebrow_spacing: float = 2.5


@dataclass(frozen=True)
class Shape:
    card_radius: float = 16.0
    control_radius: float = 10.0
    pill_radius: float = 12.0
    shadow: float = 1.0  # multiplier for the painted card shadow
    hover_lift: float = 1.0  # how much cards lift on hover (0 disables)


@dataclass(frozen=True)
class Accent:
    key: str
    name: str
    overrides: dict[str, str]


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    description: str
    mode: str  # "light" or "dark": the overall brightness (title bar, art defaults)
    tokens: dict[str, str]
    fonts: Fonts
    shape: Shape = Shape()
    art: dict[str, str] = field(default_factory=dict)
    art_variants: dict[str, str] = field(default_factory=dict)
    accents: tuple[Accent, ...] = ()
    counterpart: str = ""  # the theme the quick light/dark toggle switches to

    def palette(self, accent: str | None = None) -> dict[str, str]:
        tokens = dict(self.tokens)
        for option in self.accents:
            if option.key == accent:
                tokens.update(option.overrides)
                break
        return complete_tokens(tokens, self.mode)

    @property
    def swatches(self) -> list[str]:
        t = self.palette()
        return [t["bg"], t["surface"], t["accent"], t["primary"], t["terracotta"], t["blue"]]


# -- colour maths -------------------------------------------------------------------

def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix_hex(a: str, b: str, t: float) -> str:
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "#{:02X}{:02X}{:02X}".format(
        round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t))


def luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def complete_tokens(t: dict[str, str], mode: str) -> dict[str, str]:
    """Fill in derived tokens a theme didn't set explicitly."""
    light = mode == "light"
    toward = "#000000" if light else "#FFFFFF"
    t = dict(t)
    t.setdefault("input", t["surface"])
    t.setdefault("hover", mix_hex(t["elevated"], t["accent_soft"], 0.35))
    t.setdefault("pressed", mix_hex(t["elevated"], t["accent_soft"], 0.8))
    t.setdefault("accent_hover", mix_hex(t["accent"], toward, 0.1))
    t.setdefault("accent_pressed", mix_hex(t["accent"], toward, 0.2))
    t.setdefault("primary_hover", mix_hex(t["primary"], toward, 0.12))
    t.setdefault("primary_pressed", mix_hex(t["primary"], toward, 0.24))
    t.setdefault("on_accent", t["surface"] if light else t["bg"])
    t.setdefault("chart_grid", mix_hex(t["surface"], t["divider"], 0.6))
    t.setdefault("banner", mix_hex(t["bg"], t["accent_soft"], 0.55))
    t.setdefault("banner2", t["banner"])
    t.setdefault("track", t["elevated"] if light else t["hover"])
    t.setdefault("progress", t["accent_dark"] if light else t["accent"])
    t.setdefault("nav_active", t["accent_dark"] if light else t["text"])
    t.setdefault("nav_pill", t["accent_soft"])
    t.setdefault("segment_active", t["accent_dark"] if light else t["primary"])
    t.setdefault("on_segment_active", t["on_primary"])
    t.setdefault("focus", t["accent"])
    t.setdefault("success", t["accent_text"])
    t.setdefault("success_soft", t["accent_soft"])
    t.setdefault("shadow", "#000000")
    t.setdefault("selection", t["accent_soft"])
    t.setdefault("scrim", "#000000")
    return t


# -- shared artwork palette (see tools/make_art.py) ----------------------------------

ART_BASE = ("#71896C", "#8FA77F", "#AFC2A2", "#5E7458", "#C77D59", "#B06C4B", "#E3A47E",
            "#E8E2D3", "#DCD3C1", "#EFF1E7", "#E1E7DA", "#CFDAC9", "#B9C8B2", "#F3F4EC")
# leaf1 leaf2 leaf3 stem pot pot2 sun frame frame2 glass hill1 hill2 hill3 mist


def _art(*colors: str) -> dict[str, str]:
    return dict(zip(ART_BASE, colors))


# -- the five themes -------------------------------------------------------------------

PAPER = Theme(
    id="paper",
    name="Paper & Sage",
    description="Warm ivory paper, muted sage and soft botanical art. Calm for studying, reading and journaling.",
    mode="light",
    tokens={
        "bg": "#F5F2E9", "sidebar": "#E9EDE3", "surface": "#FFFDF7", "elevated": "#F0F1E8",
        "input": "#FFFDF7", "hover": "#EDEFE5", "pressed": "#E2E7DA",
        "text": "#252C26", "text2": "#5F665B", "text3": "#666D62",
        "accent": "#71896C", "accent_hover": "#647C5F", "accent_pressed": "#57704F",
        "accent_text": "#4E6847", "accent_dark": "#425845", "on_accent": "#FFFDF7", "accent_soft": "#DCE4D5",
        "primary": "#425845", "primary_hover": "#384C3B", "primary_pressed": "#2F4132", "on_primary": "#FFFDF7",
        "divider": "#E1E2D8", "border": "#D5D8CB",
        "blue": "#7793AE", "blue_text": "#4E6781", "blue_soft": "#E2E9EF",
        "terracotta": "#C77D59", "terracotta_text": "#93502F", "terracotta_soft": "#F4E4D9",
        "amber": "#C49A4A", "amber_text": "#7E5D1B", "amber_soft": "#F3EBD7",
        "danger": "#A94A36", "danger_soft": "#F6E2DC",
        "shadow": "#3C4A36", "chart_grid": "#ECECE3", "banner": "#E8ECDF",
    },
    fonts=Fonts(display=FontSpec("Georgia", 400, ("Cambria", "Times New Roman")),
                heading=FontSpec("Georgia", 400, ("Cambria", "Times New Roman")), nav_size=12.5),
    shape=Shape(card_radius=16, control_radius=10, pill_radius=12, shadow=1.0),
    art={},
    accents=(
        Accent("sage", "Sage", {}),
        Accent("blue", "Dusty blue", {
            "accent": "#7793AE", "accent_text": "#4F6985", "accent_dark": "#3F5670", "accent_soft": "#DFE7EE",
            "primary": "#3F5670", "on_primary": "#FFFDF7"}),
        Accent("clay", "Terracotta", {
            "accent": "#C77D59", "accent_text": "#8F4D2D", "accent_dark": "#7E4429", "accent_soft": "#F2E1D5",
            "primary": "#7E4429", "on_primary": "#FFFDF7"}),
    ),
    counterpart="midnight",
)

MIDNIGHT = Theme(
    id="midnight",
    name="Midnight Focus",
    description="Deep charcoal with muted sage. A quiet dark workspace for evening study, code and writing.",
    mode="dark",
    tokens={
        "bg": "#191D1A", "sidebar": "#202621", "surface": "#272E28", "elevated": "#303830",
        "input": "#222823", "hover": "#313A31", "pressed": "#3A453A",
        "text": "#EAEDE5", "text2": "#ADB6A9", "text3": "#97A193",
        "accent": "#A6BE9B", "accent_hover": "#B5CBAA", "accent_pressed": "#95AE8A",
        "accent_text": "#A6BE9B", "accent_dark": "#829A79", "on_accent": "#172019", "accent_soft": "#39483A",
        "primary": "#A6BE9B", "primary_hover": "#B5CBAA", "primary_pressed": "#95AE8A", "on_primary": "#172019",
        "divider": "#3A443B", "border": "#475247",
        "blue": "#91AFC7", "blue_text": "#9CB8CE", "blue_soft": "#2D3A44",
        "terracotta": "#D99A77", "terracotta_text": "#DFA584", "terracotta_soft": "#46352C",
        "amber": "#D8B872", "amber_text": "#D8B872", "amber_soft": "#3E3828",
        "danger": "#E0907E", "danger_soft": "#46302B",
        "shadow": "#000000", "chart_grid": "#343D35", "banner": "#2B342C",
    },
    fonts=Fonts(display=FontSpec("Segoe UI", 300, ("Arial",)),
                heading=FontSpec("Segoe UI", 600, ("Arial",)),
                numeric=FontSpec("Segoe UI", 300, ("Arial",)), nav_size=11.0, eyebrow_spacing=2.0),
    shape=Shape(card_radius=12, control_radius=9, pill_radius=10, shadow=1.6, hover_lift=0.7),
    art=_art("#7E9775", "#6A8262", "#586C53", "#8CA383", "#A86C4E", "#8C5A41", "#CC8F6B",
             "#343D35", "#3F4A40", "#2A322B", "#2C352D", "#334034", "#3C4B3D", "#242B25"),
    accents=(
        Accent("sage", "Sage", {}),
        Accent("teal", "Muted teal", {
            "accent": "#8FC1B5", "accent_text": "#99C8BC", "accent_dark": "#6FA092", "accent_soft": "#2E4542",
            "primary": "#8FC1B5", "on_primary": "#13201D"}),
        Accent("blue", "Slate blue", {
            "accent": "#9DB6D3", "accent_text": "#A6BDD8", "accent_dark": "#7B97B8", "accent_soft": "#2F3B4A",
            "primary": "#9DB6D3", "on_primary": "#151B23"}),
    ),
    counterpart="paper",
)

ZEN = Theme(
    id="zen",
    name="Zen Minimal",
    description="Warm white, stone grey and a soft ink blue. Quiet, spacious and typographic.",
    mode="light",
    tokens={
        "bg": "#F7F6F2", "sidebar": "#F0EEE9", "surface": "#FDFCFA", "elevated": "#F2F0EB",
        "hover": "#EEECE6", "pressed": "#E4E1DA",
        "text": "#26282B", "text2": "#5F6166", "text3": "#6A6C70",
        "accent": "#6F8AA5", "accent_text": "#4A6580", "accent_dark": "#3C5268", "accent_soft": "#E4EAF0",
        "primary": "#33383E", "primary_hover": "#41474E", "primary_pressed": "#23272B", "on_primary": "#FDFCFA",
        "divider": "#E7E4DD", "border": "#D8D4CB",
        "blue": "#7F95A8", "blue_text": "#536A7F", "blue_soft": "#E6ECF1",
        "terracotta": "#B08968", "terracotta_text": "#85603F", "terracotta_soft": "#F1E9E1",
        "amber": "#B8995A", "amber_text": "#775D20", "amber_soft": "#F2ECDD",
        "danger": "#A54C3B", "danger_soft": "#F5E4DF",
        "shadow": "#26282B", "banner": "#F0EFEA",
        "nav_pill": "#E7E5DF", "nav_active": "#26282B", "progress": "#4A6580", "segment_active": "#33383E",
    },
    fonts=Fonts(display=FontSpec("Yu Gothic UI", 300, ("Segoe UI",)),
                heading=FontSpec("Yu Gothic UI", 600, ("Segoe UI",)),
                body=FontSpec("Segoe UI", 400, ("Arial",)),
                numeric=FontSpec("Yu Gothic UI", 300, ("Segoe UI",)), nav_size=11.0, eyebrow_spacing=3.0),
    shape=Shape(card_radius=8, control_radius=6, pill_radius=7, shadow=0.45, hover_lift=0.5),
    art=_art("#8C9A93", "#A7B1AA", "#C5CBC6", "#6E7A74", "#B08968", "#977055", "#D9B9A0",
             "#E9E6DF", "#DEDAD1", "#F3F2EE", "#E7E8E6", "#D8DBDA", "#C4C9CA", "#F5F5F2"),
    art_variants={"branch": "zen-branch", "pot": "zen-stones"},
    accents=(
        Accent("ink", "Ink blue", {}),
        Accent("stone", "Stone", {
            "accent": "#8A8F8C", "accent_text": "#5B605D", "accent_dark": "#454946", "accent_soft": "#E9EAE7",
            "progress": "#5B605D"}),
        Accent("moss", "Moss", {
            "accent": "#7D9178", "accent_text": "#526650", "accent_dark": "#40523E", "accent_soft": "#E5EBE2",
            "progress": "#526650"}),
    ),
    counterpart="aurora",
)

AURORA = Theme(
    id="aurora",
    name="Aurora",
    description="Deep blue-black with restrained violet and blue. Crisp, modern and calm.",
    mode="dark",
    tokens={
        "bg": "#0F1320", "sidebar": "#131929", "surface": "#192032", "elevated": "#20283D",
        "input": "#151B2B", "hover": "#252E46", "pressed": "#2D3753",
        "text": "#E8EBF4", "text2": "#AEB6CB", "text3": "#949DB6",
        "accent": "#A497EC", "accent_text": "#B3A8F1", "accent_dark": "#8072D3", "accent_soft": "#2B2A4C",
        "on_accent": "#12152A",
        "primary": "#ABA0F0", "on_primary": "#151733",
        "divider": "#262F47", "border": "#34405E",
        "blue": "#7FA7E8", "blue_text": "#9BBCF0", "blue_soft": "#1E2B48",
        "terracotta": "#E59C8E", "terracotta_text": "#EBAA9D", "terracotta_soft": "#3B2733",
        "amber": "#E1C27C", "amber_text": "#E4C784", "amber_soft": "#363223",
        "danger": "#F0928A", "danger_soft": "#43262D",
        "shadow": "#000000", "banner": "#1D2240", "banner2": "#16233D",
        "nav_pill": "#262B4A",
    },
    fonts=Fonts(display=FontSpec("Segoe UI", 600, ("Arial",)),
                heading=FontSpec("Segoe UI", 600, ("Arial",)),
                numeric=FontSpec("Bahnschrift", 300, ("Segoe UI",)), nav_size=11.0, eyebrow_spacing=2.2),
    shape=Shape(card_radius=14, control_radius=10, pill_radius=11, shadow=1.8, hover_lift=0.8),
    art=_art("#6F7FC4", "#5867A8", "#3E4A80", "#8C9BE0", "#9D8FE8", "#7C6FD0", "#C8B8FF",
             "#232B42", "#2B3550", "#1A2135", "#1E2640", "#27325A", "#33407A", "#161C2D"),
    art_variants={"branch": "aurora-branch", "pot": "aurora-orbit"},
    accents=(
        Accent("violet", "Violet", {}),
        Accent("blue", "Night blue", {
            "accent": "#86AEEE", "accent_text": "#9DBDF2", "accent_dark": "#5F8AD4", "accent_soft": "#1F2D4E",
            "primary": "#8DB3EF", "on_primary": "#0F1A30", "nav_pill": "#1F2D4E"}),
        Accent("teal", "Polar teal", {
            "accent": "#7CC6C0", "accent_text": "#8FD0CA", "accent_dark": "#57A49E", "accent_soft": "#1B3540",
            "primary": "#85CBC5", "on_primary": "#0D2024", "nav_pill": "#1B3540"}),
    ),
    counterpart="zen",
)

ESPRESSO = Theme(
    id="espresso",
    name="Espresso",
    description="Warm cocoa and wood tones, cream type and muted amber. Cosy for late evenings.",
    mode="dark",
    tokens={
        "bg": "#1E1714", "sidebar": "#241C18", "surface": "#2C221D", "elevated": "#352923",
        "input": "#261E1A", "hover": "#3A2D26", "pressed": "#45362D",
        "text": "#F2E8DB", "text2": "#CDBCA8", "text3": "#B19E88",
        "accent": "#D4A373", "accent_text": "#DEB58C", "accent_dark": "#B5844F", "accent_soft": "#4A3628",
        "on_accent": "#231A15",
        "primary": "#DDB287", "on_primary": "#241A14",
        "divider": "#3E3029", "border": "#4E3D33",
        "blue": "#9DB4B8", "blue_text": "#AFC5C8", "blue_soft": "#2C3333",
        "terracotta": "#D08560", "terracotta_text": "#E39F7D", "terracotta_soft": "#4A2E24",
        "amber": "#D9B66A", "amber_text": "#E2C07A", "amber_soft": "#443822",
        "danger": "#EC9584", "danger_soft": "#4B2A26",
        "shadow": "#000000", "banner": "#33271F",
        "nav_pill": "#3D2E25", "nav_active": "#F2E8DB",
    },
    fonts=Fonts(display=FontSpec("Constantia", 400, ("Georgia", "Cambria")),
                heading=FontSpec("Constantia", 400, ("Georgia", "Cambria")),
                numeric=FontSpec("Cambria", 400, ("Georgia",)), nav_size=12.0),
    shape=Shape(card_radius=14, control_radius=10, pill_radius=12, shadow=1.7, hover_lift=0.8),
    art=_art("#8A7A5A", "#6E6248", "#5A4F3B", "#A08C68", "#C98B5E", "#A9704A", "#E2B57A",
             "#3A2D26", "#45362D", "#2F2420", "#33271F", "#3D2F26", "#4A392D", "#2A201B"),
    art_variants={"branch": "espresso-branch", "pot": "espresso-cup"},
    accents=(
        Accent("caramel", "Caramel", {}),
        Accent("clay", "Terracotta", {
            "accent": "#D48D69", "accent_text": "#E3A383", "accent_dark": "#B26D4B", "accent_soft": "#4A2F25",
            "primary": "#DE9F80", "on_primary": "#24160F"}),
        Accent("olive", "Olive", {
            "accent": "#B3B07A", "accent_text": "#C4C18C", "accent_dark": "#908D58", "accent_soft": "#3B3A27",
            "primary": "#BFBC86", "on_primary": "#1E1D12"}),
    ),
    counterpart="paper",
)

THEMES: dict[str, Theme] = {t.id: t for t in (PAPER, MIDNIGHT, ZEN, AURORA, ESPRESSO)}
THEME_IDS = tuple(THEMES)


def get_theme(theme_id: str | None) -> Theme:
    theme_id = LEGACY_ALIASES.get(theme_id or "", theme_id or "")
    return THEMES.get(theme_id, THEMES[DEFAULT_THEME])
