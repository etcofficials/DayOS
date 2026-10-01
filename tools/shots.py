r"""Render DayOS pages to PNG files for visual review (development tool).

    .venv\Scripts\python.exe tools\shots.py --themes paper,midnight --pages today,tasks --out .cache\shots

Runs off-screen against a throwaway data folder (``--home``, default ``.cache\shots-home``),
optionally filled with demo records (``--demo``) so layouts can be judged with content.
Never point ``--home`` at a real data folder.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--themes", default="paper,midnight,zen,aurora,espresso")
    parser.add_argument("--pages", default="today")
    parser.add_argument("--out", default=str(ROOT / ".cache" / "shots"))
    parser.add_argument("--home", default=str(ROOT / ".cache" / "shots-home"))
    parser.add_argument("--size", default="1360x860")
    parser.add_argument("--demo", action="store_true", help="fill the throwaway folder with demo records")
    parser.add_argument("--collapsed", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    os.environ["DAYOS_HOME"] = args.home

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from src.config import AppPaths, ensure_writable
    from src.context import AppContext
    from src.ui import anim
    from src.ui.main_window import MainWindow
    from src.ui.theme import theme
    from src.ui.theme_settings import apply_from_settings, watch_settings

    app = QApplication(sys.argv[:1])
    paths = AppPaths(Path(args.home))
    ensure_writable(paths)
    theme.set_asset_dir(paths.cache_dir)
    ctx = AppContext.open(paths)
    if args.demo:
        from tools.demo_data import fill

        fill(ctx)
    apply_from_settings(ctx.settings)
    watch_settings(ctx.settings)
    window = MainWindow(ctx)
    anim.set_motion_provider(lambda: False)
    w, h = (int(x) for x in args.size.split("x"))
    window.resize(w, h)
    window.show()
    if args.collapsed:
        window.set_sidebar_collapsed(True, animate=False)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def settle(ms: int = 60) -> None:
        loop_end = QTimer()
        loop_end.setSingleShot(True)
        from PySide6.QtCore import QEventLoop

        loop = QEventLoop()
        loop_end.timeout.connect(loop.quit)
        loop_end.start(ms)
        loop.exec()

    for theme_id in args.themes.split(","):
        ctx.settings.set("theme", theme_id)
        settle(120)
        for key in args.pages.split(","):
            window.navigate(key)
            settle(250)
            target = out / f"{key}-{theme_id}.png"
            window.grab().save(str(target))
            print(target)
    window.close()
    ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
