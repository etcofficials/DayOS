"""Small, read-only Windows clipboard helpers (ctypes, no extra packages).

* :func:`private_formats` checks whether the app that copied asked clipboard
  tools to ignore the content (password managers set these formats).
* :func:`owner_app` names the executable that owns the clipboard.
* :func:`paste_into` brings a window back to the front and sends one Ctrl+V,
  only when the user explicitly chooses "paste" in ClipVault.

DayOS never installs keyboard hooks and never reads other input.
Everything fails safe: on any error the helpers return "unknown".
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
VK_CONTROL, VK_V = 0x11, 0x56
KEYEVENTF_KEYUP = 0x0002

_format_ids: dict[str, int] = {}


def _user32():
    import ctypes

    return ctypes.windll.user32


def private_formats(names: tuple[str, ...]) -> set[str]:
    """Which of the registered clipboard ``names`` are on the clipboard right now."""
    if not IS_WINDOWS:
        return set()
    try:
        user32 = _user32()
        found = set()
        for name in names:
            fmt = _format_ids.get(name)
            if fmt is None:
                fmt = int(user32.RegisterClipboardFormatW(name))
                _format_ids[name] = fmt
            if fmt and user32.IsClipboardFormatAvailable(fmt):
                found.add(name)
        return found
    except (OSError, AttributeError, ValueError):
        log.debug("Clipboard format check failed", exc_info=True)
        return set()


def _exe_of_window(hwnd) -> tuple[str, int]:
    import ctypes
    from ctypes import wintypes

    pid = wintypes.DWORD(0)
    _user32().GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    if not pid.value:
        return "", 0
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return "", int(pid.value)
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(ctypes.c_void_p(handle), 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value), int(pid.value)
        return "", int(pid.value)
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def owner_app() -> tuple[str, bool]:
    """(executable name of the clipboard owner, whether it is this DayOS process)."""
    if not IS_WINDOWS:
        return "", False
    try:
        user32 = _user32()
        user32.GetClipboardOwner.restype = __import__("ctypes").c_void_p
        hwnd = user32.GetClipboardOwner()
        if not hwnd:
            return "", False
        exe, pid = _exe_of_window(hwnd)
        return exe, pid == os.getpid()
    except (OSError, AttributeError, ValueError):
        log.debug("Clipboard owner lookup failed", exc_info=True)
        return "", False


def foreground_window() -> int:
    if not IS_WINDOWS:
        return 0
    try:
        user32 = _user32()
        user32.GetForegroundWindow.restype = __import__("ctypes").c_void_p
        return int(user32.GetForegroundWindow() or 0)
    except (OSError, AttributeError):
        return 0


def foreground_app() -> tuple[str, bool]:
    """(executable name of the window in front, whether it is this DayOS process)."""
    hwnd = foreground_window()
    if not hwnd:
        return "", False
    try:
        exe, pid = _exe_of_window(hwnd)
        return exe, pid == os.getpid()
    except (OSError, AttributeError, ValueError):
        return "", False


def is_own_window(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        return _exe_of_window(hwnd)[1] == os.getpid()
    except (OSError, AttributeError, ValueError):
        return False


def paste_into(hwnd: int) -> bool:
    """Bring ``hwnd`` to the front and send a single Ctrl+V. Returns False if that wasn't possible."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        import ctypes

        user32 = _user32()
        if not user32.IsWindow(ctypes.c_void_p(hwnd)):
            return False
        user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        return True
    except (OSError, AttributeError, ValueError):
        log.debug("Paste into window failed", exc_info=True)
        return False
