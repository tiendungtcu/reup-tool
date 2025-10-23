# -*- mode: python ; coding: utf-8 -*-

import inspect
import pathlib
import sys

SPEC_PATH = pathlib.Path(inspect.getfile(inspect.currentframe())).resolve()
PROJECT_ROOT = SPEC_PATH.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

block_cipher = None


a = Analysis(
    [str(PROJECT_ROOT / 'launch_gui.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (
            str(PROJECT_ROOT / 'resources' / 'i18n' / 'translations.json'),
            'resources/i18n',
        ),
    ],
    hiddenimports=[
        'moviepy',
        'moviepy.editor',
        'moviepy.video.fx.all',
        'moviepy.audio.fx.all',
        'numpy',
        'PySide6.QtNetwork',
        'PySide6.QtSvg',
        'PySide6.QtPrintSupport',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    [],
    [],
    [],
    name='AutoBot-GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    exclude_binaries=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AutoBot-GUI',
)

app = BUNDLE(
    coll,
    name='AutoBot GUI.app',
    icon=None,
    bundle_identifier='com.autobot.gui',
)
