# -*- mode: python ; coding: utf-8 -*-
# PyInstaller one-folder build for DayOS.
#
#   build.ps1   (sets cache/temp folders on G: and runs this spec)
#
# Output: dist\DayOS\DayOS.exe. At runtime the packaged app keeps its data next
# to the executable (dist\DayOS\data, backups, logs), never in the bundled
# read-only _internal folder.

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets/dayos.svg", "assets"),
        ("assets/dayos.ico", "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DayOS",
    icon="assets/dayos.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DayOS",
)
