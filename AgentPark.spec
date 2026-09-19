# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('src')
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('uvicorn')
computer_datas, computer_binaries = [], []
if sys.platform == 'win32':
    for package in ('windows_capture', 'pywinauto', 'comtypes'):
        package_datas, package_binaries, package_imports = collect_all(package)
        computer_datas += package_datas
        computer_binaries += package_binaries
        hiddenimports += package_imports

# Knowledge indexing uses LanceDB/Arrow, PDFium and the Chinese tokenizer at
# runtime. These packages contain dynamically loaded native/data files which
# ordinary import analysis does not reliably discover in a frozen executable.
for package in ('lancedb', 'pyarrow', 'pypdfium2', 'jieba'):
    package_datas, package_binaries, package_imports = collect_all(package)
    computer_datas += package_datas
    computer_binaries += package_binaries
    hiddenimports += package_imports


a = Analysis(
    ['src\\fast_api.py'],
    pathex=[],
    binaries=computer_binaries,
    datas=[('webui\\dist', 'webui\\dist')] + computer_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['flask'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AgentPark',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
