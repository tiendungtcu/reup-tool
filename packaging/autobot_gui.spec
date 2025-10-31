# -*- mode: python ; coding: utf-8 -*-

import inspect
import pathlib
import sys

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

SPEC_PATH = pathlib.Path(inspect.getfile(inspect.currentframe())).resolve()
PROJECT_ROOT = SPEC_PATH.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

block_cipher = None

cv2_datas, cv2_binaries, cv2_hiddenimports = collect_all("cv2")
cv2_binaries.extend(collect_dynamic_libs("cv2"))

numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all("numpy")
numpy_binaries.extend(collect_dynamic_libs("numpy"))


base_datas = [
    (
        str(PROJECT_ROOT / 'resources' / 'i18n' / 'translations.json'),
        'resources/i18n',
    ),
    (
        str(PROJECT_ROOT / 'resources' / 'icons'),
        'resources/icons',
    ),
]
base_datas.extend(cv2_datas)
base_datas.extend(numpy_datas)

a = Analysis(
    [str(PROJECT_ROOT / 'launch_gui.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=cv2_binaries + numpy_binaries,
    datas=base_datas,
    hiddenimports=[
    *cv2_hiddenimports,
    *numpy_hiddenimports,
        'moviepy',
        'moviepy.video.fx',
        'moviepy.video.fx.Resize',
        'moviepy.audio.fx',
        'moviepy.audio.fx.AudioLoop',
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
    icon=str(PROJECT_ROOT / 'resources' / 'icons' / 'icon.icns'),
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
    icon=str(PROJECT_ROOT / 'resources' / 'icons' / 'icon.icns'),
    bundle_identifier='com.autobot.gui',
)
