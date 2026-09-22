# -*- mode: python ; coding: utf-8 -*-

import sys

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("beancount_dedup", includes=["webapp/*"])
hiddenimports = ["beancount_dedup.webapp"]
# The desktop API has native XLSX/PDF import paths and never uses the legacy
# pandas converter. PyInstaller otherwise follows optional imports and bundles
# the development stack, adding tens of megabytes to every release.
excludes = ["numpy", "pandas", "pytest"]

analysis = Analysis(
    ["desktop_launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(analysis.pure)

helper_analysis = Analysis(
    ["update_helper_launcher.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
helper_pyz = PYZ(helper_analysis.pure)
helper_exe = EXE(
    helper_pyz,
    helper_analysis.scripts,
    helper_analysis.binaries,
    helper_analysis.datas,
    [],
    name="FinancialBeancountUpdater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

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
    helper_exe,
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
