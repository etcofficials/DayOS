"""System-wide keyboard shortcuts on Windows via ``RegisterHotKey``.

Only the exact key combinations registered here are claimed. DayOS never
hooks or reads other keyboard input. If another program already owns a
combination, registration fails gracefully and the reason is shown in Settings.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_SPECIAL_VK = {
    Qt.Key.Key_Space: 0x20, Qt.Key.Key_Return: 0x0D, Qt.Key.Key_Enter: 0x0D, Qt.Key.Key_Tab: 0x09,
    Qt.Key.Key_Insert: 0x2D, Qt.Key.Key_Home: 0x24, Qt.Key.Key_End: 0x23, Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22, Qt.Key.Key_Period: 0xBE, Qt.Key.Key_Comma: 0xBC, Qt.Key.Key_Slash: 0xBF,
    Qt.Key.Key_Semicolon: 0xBA, Qt.Key.Key_Minus: 0xBD, Qt.Key.Key_Equal: 0xBB, Qt.Key.Key_BracketLeft: 0xDB,
    Qt.Key.Key_BracketRight: 0xDD, Qt.Key.Key_Apostrophe: 0xDE, Qt.Key.Key_QuoteLeft: 0xC0,
}


def parse_sequence(text: str) -> tuple[int, int] | None:
    """``"Ctrl+Alt+Space"`` → (modifiers, virtual key). ``None`` if it can't be a global hotkey."""
    seq = QKeySequence(text)
    if seq.isEmpty() or seq.count() != 1:
        return None
    combo = seq[0]
    key = combo.key()
    mods = combo.keyboardModifiers()
    flags = 0
    if mods & Qt.KeyboardModifier.ControlModifier:
        flags |= MOD_CONTROL
    if mods & Qt.KeyboardModifier.AltModifier:
        flags |= MOD_ALT
    if mods & Qt.KeyboardModifier.ShiftModifier:
        flags |= MOD_SHIFT
    if mods & Qt.KeyboardModifier.MetaModifier:
        flags |= MOD_WIN
    if not flags & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return None  # a global shortcut must include Ctrl, Alt or Win so it can't swallow typing
    k = int(key.value) if hasattr(key, "value") else int(key)
    if Qt.Key.Key_A.value <= k <= Qt.Key.Key_Z.value or Qt.Key.Key_0.value <= k <= Qt.Key.Key_9.value:
        vk = k
    elif Qt.Key.Key_F1.value <= k <= Qt.Key.Key_F24.value:
        vk = 0x70 + (k - Qt.Key.Key_F1.value)
    else:
        vk = _SPECIAL_VK.get(Qt.Key(k))
        if vk is None:
            return None
    return flags, vk


class GlobalHotkeys(QObject, QAbstractNativeEventFilter):
    activated = Signal(str)

    def __init__(self) -> None:
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self._ids: dict[str, int] = {}
        self._names: dict[int, str] = {}
        self._next_id = 0xB100
        self.errors: dict[str, str] = {}
        self._installed = False
        self.supported = sys.platform == "win32"

    def _install(self) -> None:
        if not self._installed:
            app = QApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self)
                self._installed = True

    def register(self, name: str, sequence: str) -> bool:
        """(Re)register ``name``. Returns False (and records why in ``errors``) on failure."""
        self.unregister(name)
        self.errors.pop(name, None)
        if not self.supported:
            self.errors[name] = "System-wide shortcuts are only available on Windows."
            return False
        parsed = parse_sequence(sequence)
        if parsed is None:
            self.errors[name] = "Use a combination with Ctrl, Alt or Win plus a letter, digit, F-key or Space."
            return False
        import ctypes

        self._install()
        hotkey_id = self._next_id
        self._next_id += 1
        ok = ctypes.windll.user32.RegisterHotKey(None, hotkey_id, parsed[0] | MOD_NOREPEAT, parsed[1])
        if not ok:
            self.errors[name] = (f"{sequence} is already used by another program or by Windows. "
                                 "Choose a different combination.")
            log.info("Global hotkey %s (%s) could not be registered", name, sequence)
            return False
        self._ids[name] = hotkey_id
        self._names[hotkey_id] = name
        log.info("Global hotkey %s registered", name)
        return True

    def unregister(self, name: str) -> None:
        hotkey_id = self._ids.pop(name, None)
        if hotkey_id is None:
            return
        self._names.pop(hotkey_id, None)
        if self.supported:
            import ctypes

            ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)

    def unregister_all(self) -> None:
        for name in list(self._ids):
            self.unregister(name)

    def is_registered(self, name: str) -> bool:
        return name in self._ids

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt override
        if self._names and event_type == b"windows_generic_MSG":
            try:
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam in self._names:
                    self.activated.emit(self._names[msg.wParam])
                    return True, 0
            except (ValueError, TypeError, OSError):
                log.debug("Could not read native message", exc_info=True)
        return False, 0
