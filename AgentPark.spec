# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('src')
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('nodes')
hiddenimports += collect_submodules('functions')


a = Analysis(
    ['src\\fast_api.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('webui\\dist', 'webui\\dist'),
        ('config', 'config'),
        ('functions', 'functions'),
        ('nodes', 'nodes'),
        ('skills', 'skills'),
        ('plugins', 'plugins'),
        ('docs', 'docs'),
    ],
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
