"""Measure DayOS start-up time and memory with a throwaway data folder (developer tool).

    .venv\\Scripts\\python.exe tools\\measure_startup.py

Prints import time, time until the main window is shown, time to visit every page once,
and the process's peak working set. Uses a temporary folder, never your real data.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

T0 = time.perf_counter()
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def memory_mb() -> tuple[float, float]:
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                                 wintypes.DWORD]
    kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.WorkingSetSize / 1048576, counters.PeakWorkingSetSize / 1048576


def main() -> None:
    from PySide6.QtWidgets import QApplication

    from src.config import AppPaths, ensure_writable
    from src.context import AppContext
    from src.ui.theme import theme

    t_import = time.perf_counter() - T0
    home = Path(tempfile.mkdtemp(prefix="dayos-measure-"))
    try:
        app = QApplication(sys.argv)
        paths = AppPaths(home)
        ensure_writable(paths)
        t1 = time.perf_counter()
        ctx = AppContext.open(paths)
        theme.set_asset_dir(paths.cache_dir)
        theme.apply("paper")
        from src.ui.main_window import MainWindow

        ctx.settings.set("capture.global", False)
        window = MainWindow(ctx)
        window.show()
        app.processEvents()
        t_window = time.perf_counter() - t1
        from src.modules import registry

        keys = [m.key for m in registry.MODULES]
        timings = {}
        for key in keys:
            t = time.perf_counter()
            window.navigate(key)
            app.processEvents()
            timings[key] = (time.perf_counter() - t) * 1000
        current, peak = memory_mb()
        print(f"platform: {app.platformName()}  python {sys.version.split()[0]}")
        print(f"imports before Qt app: {t_import * 1000:.0f} ms")
        print(f"database open + main window shown: {t_window * 1000:.0f} ms")
        slowest = sorted(timings.items(), key=lambda x: -x[1])[:5]
        print("first visit to each page (slowest five): " + ", ".join(f"{k} {v:.0f} ms" for k, v in slowest))
        print(f"all {len(keys)} pages visited: {sum(timings.values()):.0f} ms total")
        print(f"memory: {current:.0f} MB now, {peak:.0f} MB peak working set")
        window.close()
        ctx.close()
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    main()
