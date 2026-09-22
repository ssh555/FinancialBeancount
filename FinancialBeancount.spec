# -*- mode: python ; coding: utf-8 -*-

import sys

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("beancount_dedup", includes=["webapp/*"])
hiddenimports = ["beancount_dedup.webapp"]

analysis = Analysis(
    ["desktop_launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="FinancialBeancount",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

app = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="FinancialBeancount",
)

if sys.platform == "darwin":
    bundle = BUNDLE(
        app,
        name="FinancialBeancount.app",
        bundle_identifier="io.github.ssh555.financialbeancount",
        info_plist={"NSHighResolutionCapable": True},
    )
