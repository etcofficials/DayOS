"""Windows file helpers for FilePilot (ctypes only).

* :func:`recycle` sends one file to the Recycle Bin (recoverable). It is only
  used after the user has previewed and confirmed the operation, and only on
  fixed drives, which have a Recycle Bin.
* :func:`drive_type` tells fixed, removable and network drives apart.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

DRIVE_UNKNOWN, DRIVE_NO_ROOT, DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_CDROM, DRIVE_RAMDISK = range(7)

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000  # ask before anything would be deleted permanently instead of recycled


def drive_type(path: str) -> int:
    if not IS_WINDOWS:
        return DRIVE_UNKNOWN
    import ctypes

    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive:
        return DRIVE_UNKNOWN
    root = drive + "\\" if not drive.startswith("\\\\") else drive.rstrip("\\") + "\\"
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
    except (OSError, AttributeError):
        return DRIVE_UNKNOWN


def can_recycle(path: str) -> bool:
    return IS_WINDOWS and drive_type(path) == DRIVE_FIXED


def recycle(path: str) -> tuple[bool, str]:
    """Send ``path`` (a file) to the Recycle Bin. Returns (ok, message)."""
    if not IS_WINDOWS:
        return False, "The Recycle Bin is only available on Windows."
    path = os.path.abspath(path)
    if not can_recycle(path):
        return False, "This drive has no Recycle Bin. Move the file instead."
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = path + "\0"  # the list must end with two NULs; ctypes adds the second
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except (OSError, AttributeError) as exc:
        return False, f"Windows refused: {exc}"
    if result != 0:
        return False, f"Windows could not recycle the file (code {result:#x})."
    if op.fAnyOperationsAborted:
        return False, "The operation was cancelled."
    if os.path.lexists(path):
        return False, "The file is still there; it may be open in another program."
    return True, "Sent to the Recycle Bin"
