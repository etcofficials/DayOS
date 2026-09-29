"""Optional "launch at login" via the current user's Run registry key.

Disabled by default and only changed when the user flips the setting. Only the
``HKEY_CURRENT_USER`` key for this user is touched (no admin rights needed).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.config import is_frozen

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DayOS"


def launch_command() -> str:
    if is_frozen():
        return f'"{Path(sys.executable).resolve()}"'
    exe = Path(sys.executable).resolve()
    pythonw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent.parent / "main.py"
    return f'"{pythonw if pythonw.exists() else exe}" "{main}"'


def is_supported() -> bool:
    return sys.platform == "win32"


def is_enabled() -> bool:
    if not is_supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        log.warning("Could not read the startup registry key", exc_info=True)
        return False


def set_enabled(enabled: bool) -> None:
    if not is_supported():
        raise OSError("Launch at login is only available on Windows.")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
