# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build for DayOS: a single, windowed DayOS.exe (no console).
#
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
#
# Output: dist\DayOS.exe. The EXE carries its Python runtime, Qt libraries and
# assets; at launch it unpacks them to a private temporary folder (standard for
# one-file apps) and runs the real application. User data is never stored
# there: it lives in a "DayOS Data" folder next to DayOS.exe (see src/config.py).

import os

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets/dayos.ico", "assets"),
        ("assets/art/*.svg", "assets/art"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtOpenGL"],
    noarchive=False,
    optimize=1,
)

# Drop Qt pieces a raster Qt Widgets app never loads (keeps the EXE small and
# its start-up unpacking quick): the software OpenGL fallback, translations,
# network/TLS plugins and image codecs other than SVG/ICO (PNG is built in).
KEEP_IMAGE_PLUGINS = {"qsvg.dll", "qico.dll"}


def wanted(entry) -> bool:
    dest = entry[0].replace("\\", "/").lower()
    name = os.path.basename(dest)
    if name == "opengl32sw.dll" or "/translations/" in dest:
        return False
    if "/plugins/imageformats/" in dest and name not in KEEP_IMAGE_PLUGINS:
        return False
    if "/plugins/tls/" in dest or "/plugins/networkinformation/" in dest:
        return False
    return True


a.binaries = [b for b in a.binaries if wanted(b)]
a.datas = [d for d in a.datas if wanted(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DayOS",
    icon="assets/dayos.ico",
    version="version_info.txt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
