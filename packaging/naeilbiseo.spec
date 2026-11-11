# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for NaeilBiseo. Run from the project root:
#   pyinstaller --noconfirm --clean packaging/naeilbiseo.spec
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NaeilBiseo",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no console window
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NaeilBiseo")
