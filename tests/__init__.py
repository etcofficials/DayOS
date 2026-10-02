"""DayOS tests. UI tests run on Qt's off-screen platform; point it at the Windows fonts so text is
measured as it is in the real app (otherwise layouts are judged with a stand-in font)."""

import os

_FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
if os.path.isdir(_FONTS):
    os.environ.setdefault("QT_QPA_FONTDIR", _FONTS)
