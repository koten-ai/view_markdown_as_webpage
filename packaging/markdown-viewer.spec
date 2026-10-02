# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
import re
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON_DIR = os.path.join(ROOT, "packaging", "icons")
ICON = os.path.join(ICON_DIR, "app.icns" if sys.platform == "darwin" else "app.ico")

serve_src = open(os.path.join(ROOT, "serve.py"), encoding="utf-8").read()
match = re.search(r'^VERSION = "([^"]+)"', serve_src, re.M)
VERSION = match.group(1) if match else "0.0.0"

datas = [
    (os.path.join(ROOT, "index.html"), "."),
    (os.path.join(ROOT, "viewer.html"), "."),
    (os.path.join(ROOT, "viewer.css"), "."),
    (os.path.join(ROOT, "viewer.js"), "."),
    (os.path.join(ROOT, "splash.js"), "."),
    (os.path.join(ROOT, "config.json"), "."),
    (os.path.join(ROOT, "ai"), "ai"),
    (os.path.join(ICON_DIR, "app.png"), "icons"),
]
hidden = collect_submodules("yake") + collect_submodules("segtok")
hidden += ["jellyfish", "networkx", "numpy", "tkinter", "tkinter.ttk"]

a = Analysis(
    [os.path.join(ROOT, "serve.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="Markdown Viewer",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=ICON if os.path.isfile(ICON) else None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="Markdown Viewer",
    )
    app = BUNDLE(
        coll,
        name="Markdown Viewer.app",
        icon=ICON if os.path.isfile(ICON) else None,
        bundle_identifier="ai.koten.markdown-viewer",
        info_plist={
            "CFBundleName": "Markdown Viewer",
            "CFBundleDisplayName": "Markdown Viewer",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSHumanReadableCopyright": "Apache-2.0",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="Markdown Viewer",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=ICON if os.path.isfile(ICON) else None,
    )
