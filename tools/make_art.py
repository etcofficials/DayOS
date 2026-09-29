r"""Generate DayOS's original botanical SVG artwork into assets/art/.

    .venv\Scripts\python.exe tools\make_art.py

All shapes are simple procedural vectors (leaves along bezier stems, layered
hills, pots and a window frame), so the art is tiny, scales cleanly on high-DPI
screens and is recolored for the dark theme at runtime (see src/ui/widgets/art.py,
which maps each colour below to a dark-theme equivalent).
"""

from __future__ import annotations

import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "art"

# Palette (light theme). Keep in sync with ART_DARK in src/ui/widgets/art.py.
LEAF1 = "#71896C"
LEAF2 = "#8FA77F"
LEAF3 = "#AFC2A2"
STEM = "#5E7458"
POT = "#C77D59"
POT2 = "#B06C4B"
SUN = "#E3A47E"
FRAME = "#E8E2D3"
FRAME2 = "#DCD3C1"
GLASS = "#EFF1E7"
HILL1 = "#E1E7DA"
HILL2 = "#CFDAC9"
HILL3 = "#B9C8B2"
MIST = "#F3F4EC"


def leaf(x: float, y: float, length: float, width: float, angle: float, color: str, vein: bool = True,
         opacity: float = 1.0) -> str:
    L, W = length, width
    d = (f"M0,0 C{L * .28:.1f},{-W:.1f} {L * .78:.1f},{-W * .78:.1f} {L:.1f},0 "
         f"C{L * .78:.1f},{W * .78:.1f} {L * .28:.1f},{W:.1f} 0,0 Z")
    out = f'<g transform="translate({x:.1f},{y:.1f}) rotate({angle:.1f})" opacity="{opacity}">'
    out += f'<path d="{d}" fill="{color}"/>'
    if vein:
        out += f'<path d="M{L * .06:.1f},0 L{L * .82:.1f},0" stroke="{STEM}" stroke-width="{max(.6, W * .08):.1f}" stroke-linecap="round" opacity=".35"/>'
    return out + "</g>"


def bezier(p0, p1, p2, p3, t):
    u = 1 - t
    x = u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
    y = u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
    dx = 3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0])
    dy = 3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1])
    return x, y, math.degrees(math.atan2(dy, dx))


def branch(p0, p1, p2, p3, leaves: int, size: float, colors=(LEAF1, LEAF2), stem_w: float = 1.6,
           seed: int = 1, spread: float = 48, start: float = 0.12) -> str:
    rnd = random.Random(seed)
    out = (f'<path d="M{p0[0]},{p0[1]} C{p1[0]},{p1[1]} {p2[0]},{p2[1]} {p3[0]},{p3[1]}" fill="none" '
           f'stroke="{STEM}" stroke-width="{stem_w}" stroke-linecap="round"/>')
    for i in range(leaves):
        t = start + (1 - start) * i / max(1, leaves - 1)
        x, y, ang = bezier(p0, p1, p2, p3, min(t, .98))
        side = 1 if i % 2 else -1
        scale = 1 - 0.45 * t
        L = size * scale * rnd.uniform(.88, 1.1)
        out += leaf(x, y, L, L * .34, ang + side * (spread + rnd.uniform(-8, 8)), colors[i % len(colors)])
    x, y, ang = bezier(p0, p1, p2, p3, 1)
    out += leaf(x, y, size * .5, size * .17, ang, colors[0])
    return out


def svg(w: int, h: int, body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{body}</svg>\n'


def mark() -> str:
    body = f'<circle cx="32" cy="23" r="8.5" fill="{SUN}"/>'
    for a in (-150, -120, -90, -60, -30):
        r = math.radians(a)
        body += (f'<line x1="{32 + 12 * math.cos(r):.1f}" y1="{23 + 12 * math.sin(r):.1f}" '
                 f'x2="{32 + 16.5 * math.cos(r):.1f}" y2="{23 + 16.5 * math.sin(r):.1f}" '
                 f'stroke="{SUN}" stroke-width="2.4" stroke-linecap="round"/>')
    body += f'<path d="M32 60 C32 52 32 44 32 36" stroke="{STEM}" stroke-width="2.6" stroke-linecap="round" fill="none"/>'
    body += f'<path d="M32 52 C20 53 11 45 9 32 C22 31 31 39 32 52 Z" fill="{LEAF1}"/>'
    body += f'<path d="M32 47 C44 48 54 39 56 26 C42 26 33 34 32 47 Z" fill="{LEAF2}"/>'
    body += f'<path d="M31 50 C24 45 18 40 13 34" stroke="{STEM}" stroke-width="1.1" fill="none" opacity=".45"/>'
    body += f'<path d="M33 45 C40 40 46 35 52 29" stroke="{STEM}" stroke-width="1.1" fill="none" opacity=".45"/>'
    return svg(64, 64, body)


def sidebar_branch() -> str:
    body = branch((150, 300), (120, 220), (70, 150), (40, 20), 15, 44, (LEAF1, LEAF2, LEAF3), 2.0, seed=4, spread=44)
    body += branch((112, 206), (96, 186), (94, 162), (112, 118), 6, 28, (LEAF2, LEAF3), 1.4, seed=9, spread=42)
    return svg(160, 300, body)


def sprig() -> str:
    body = f'<path d="M24 44 C24 34 23 26 20 18" stroke="{STEM}" stroke-width="1.8" fill="none" stroke-linecap="round"/>'
    body += leaf(23, 32, 17, 6, -150, LEAF1)
    body += leaf(23.5, 28, 18, 6, -30, LEAF2)
    body += leaf(21, 20, 13, 4.5, -118, LEAF1)
    return svg(48, 48, body)


def window_scene() -> str:
    b = ""
    # soft light patch and window
    b += f'<path d="M212 0 L318 0 L360 190 L250 190 Z" fill="{MIST}" opacity=".9"/>'
    b += f'<rect x="196" y="-6" width="118" height="128" rx="4" fill="{GLASS}" stroke="{FRAME2}" stroke-width="5"/>'
    b += f'<line x1="255" y1="-6" x2="255" y2="122" stroke="{FRAME2}" stroke-width="4"/>'
    b += f'<line x1="196" y1="56" x2="314" y2="56" stroke="{FRAME2}" stroke-width="4"/>'
    b += f'<rect x="150" y="122" width="210" height="9" rx="3" fill="{FRAME2}"/>'
    b += f'<rect x="156" y="131" width="198" height="5" rx="2" fill="{FRAME}"/>'
    # small pot with a leafy fan
    b += f'<path d="M160 100 L196 100 L191 122 L165 122 Z" fill="{POT}"/><rect x="157" y="96" width="42" height="7" rx="2" fill="{POT2}"/>'
    for i, ang in enumerate((-160, -135, -112, -90, -68, -45, -22)):
        b += leaf(178, 97, 24 + (6 if i in (2, 3, 4) else 0), 7, ang, (LEAF1, LEAF2, LEAF3)[i % 3])
    # tall plant on the right
    b += f'<path d="M262 104 L302 104 L298 131 L266 131 Z" fill="{POT}"/><rect x="259" y="100" width="46" height="7" rx="2" fill="{POT2}"/>'
    b += branch((282, 101), (280, 70), (286, 40), (276, 4), 12, 26, (LEAF1, LEAF2), 1.7, seed=3, spread=55)
    b += branch((281, 100), (270, 82), (262, 64), (266, 40), 6, 20, (LEAF2, LEAF3), 1.2, seed=7, spread=50, start=.25)
    # trailing stem over the sill edge
    b += branch((350, 122), (362, 150), (346, 170), (330, 190), 6, 16, (LEAF1, LEAF2), 1.2, seed=11, spread=50)
    return svg(360, 190, b)


def corner_leaves() -> str:
    b = branch((0, 120), (20, 100), (40, 80), (70, 60), 5, 26, (LEAF2, LEAF3), 1.4, seed=5, spread=45)
    b += branch((0, 120), (10, 90), (12, 60), (8, 30), 4, 22, (LEAF3, LEAF2), 1.2, seed=8, spread=50)
    b += leaf(18, 118, 34, 11, -35, LEAF1)
    return svg(140, 120, b)


def landscape() -> str:
    b = (f'<defs><linearGradient id="mist" x1="0" y1="0" x2="0" y2="1">'
         f'<stop offset="0" stop-color="{MIST}" stop-opacity="0"/><stop offset=".5" stop-color="{MIST}"/>'
         f'</linearGradient></defs><rect width="400" height="170" fill="url(#mist)"/>')
    b += f'<path d="M0 88 C60 62 110 70 160 80 C220 92 260 58 320 60 C360 62 385 72 400 78 L400 170 L0 170 Z" fill="{HILL1}"/>'
    b += f'<path d="M0 116 C50 96 100 98 150 108 C210 120 250 94 300 96 C350 98 380 108 400 112 L400 170 L0 170 Z" fill="{HILL2}"/>'
    b += f'<path d="M0 142 C60 128 120 132 180 140 C240 148 300 128 400 136 L400 170 L0 170 Z" fill="{HILL3}"/>'
    rnd = random.Random(21)
    for x in (18, 44, 70, 330, 356, 382):
        h = rnd.uniform(62, 92)
        b += branch((x, 172), (x - 2, 150), (x + 3, 135), (x + rnd.uniform(-6, 6), 172 - h), 7, 19,
                    (LEAF1, LEAF2), 1.1, seed=int(x), spread=52, start=.2)
    return svg(400, 170, b)


def pot() -> str:
    b = f'<ellipse cx="60" cy="104" rx="38" ry="4" fill="{FRAME2}" opacity=".7"/>'
    b += f'<path d="M38 70 L82 70 L76 102 L44 102 Z" fill="{POT}"/><rect x="34" y="64" width="52" height="9" rx="3" fill="{POT2}"/>'
    b += branch((60, 66), (58, 48), (62, 30), (56, 8), 7, 20, (LEAF1, LEAF2), 1.6, seed=2, spread=55)
    b += leaf(60, 64, 28, 9, -155, LEAF3)
    b += leaf(60, 64, 28, 9, -25, LEAF2)
    return svg(120, 110, b)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "mark.svg": mark(), "branch.svg": sidebar_branch(), "sprig.svg": sprig(), "window.svg": window_scene(),
        "corner.svg": corner_leaves(), "landscape.svg": landscape(), "pot.svg": pot(),
    }
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8")
        print(f"{name}: {len(text)} bytes")


if __name__ == "__main__":
    main()
