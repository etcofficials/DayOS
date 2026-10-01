"""Secrets (API keys, access tokens) in Windows Credential Manager.

DayOS never stores secrets in its database, settings, exports, logs or source.
Each secret is a "generic" credential named ``DayOS/<name>`` that belongs to the
current Windows user. Values are never logged; errors mention only the name.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import POINTER, Structure, byref, c_void_p, c_wchar_p
from ctypes import wintypes

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
PREFIX = "DayOS/"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
MAX_SECRET_CHARS = 1024


class CredentialError(RuntimeError):
    pass


class FILETIME(Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class CREDENTIALW(Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", c_wchar_p), ("Comment", c_wchar_p),
        ("LastWritten", FILETIME), ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", c_void_p),
        ("TargetAlias", c_wchar_p), ("UserName", c_wchar_p),
    ]


def _advapi():
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredWriteW.argtypes = [POINTER(CREDENTIALW), wintypes.DWORD]
    advapi.CredWriteW.restype = wintypes.BOOL
    advapi.CredReadW.argtypes = [c_wchar_p, wintypes.DWORD, wintypes.DWORD, POINTER(POINTER(CREDENTIALW))]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredDeleteW.argtypes = [c_wchar_p, wintypes.DWORD, wintypes.DWORD]
    advapi.CredDeleteW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [c_void_p]
    advapi.CredFree.restype = None
    return advapi


def _target(name: str) -> str:
    if not name or len(name) > 100 or any(c in name for c in "\0\n"):
        raise CredentialError("Invalid credential name.")
    return PREFIX + name


def save(name: str, secret: str) -> None:
    if not IS_WINDOWS:
        raise CredentialError("Secure storage is only available on Windows.")
    secret = (secret or "").strip()
    if not secret:
        raise CredentialError("Nothing to save.")
    if len(secret) > MAX_SECRET_CHARS:
        raise CredentialError("That key is unusually long.")
    data = secret.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    cred = CREDENTIALW()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = _target(name)
    cred.Comment = "Saved by DayOS"
    cred.CredentialBlobSize = len(data)
    cred.CredentialBlob = ctypes.cast(blob, POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "DayOS"
    if not _advapi().CredWriteW(byref(cred), 0):
        raise CredentialError(f"Windows couldn't save the credential (error {ctypes.get_last_error()}).")
    log.info("Credential %s saved", name)


def load(name: str) -> str | None:
    if not IS_WINDOWS:
        return None
    advapi = _advapi()
    ptr = POINTER(CREDENTIALW)()
    if not advapi.CredReadW(_target(name), CRED_TYPE_GENERIC, 0, byref(ptr)):
        err = ctypes.get_last_error()
        if err != ERROR_NOT_FOUND:
            log.info("Credential %s could not be read (error %s)", name, err)
        return None
    try:
        cred = ptr.contents
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        advapi.CredFree(ptr)


def exists(name: str) -> bool:
    return load(name) is not None


def delete(name: str) -> bool:
    if not IS_WINDOWS:
        return False
    ok = bool(_advapi().CredDeleteW(_target(name), CRED_TYPE_GENERIC, 0))
    if ok:
        log.info("Credential %s removed", name)
    return ok


def mask(secret: str | None) -> str:
    """Safe to show: the last four characters only."""
    if not secret:
        return ""
    return "•" * 8 + secret[-4:] if len(secret) > 8 else "•" * 8
