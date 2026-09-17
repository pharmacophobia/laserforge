# -*- mode: python ; coding: utf-8 -*-
# PyInstaller specification for LaserForge on Microsoft Windows (x64)
import os
import sys

block_cipher = None

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
ROOT_DIR = os.path.dirname(SPEC_DIR)

added_files = [
    (os.path.join(ROOT_DIR, 'assets'), 'assets'),
    (os.path.join(ROOT_DIR, 'examples'), 'examples'),
]

hidden_imports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'shapely',
    'shapely.geometry',
    'shapely.affinity',
    'shapely.ops',
    'ezdxf',
    'serial',
    'serial.tools.list_ports',
    'serial.win32',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFilter',
    'numpy',
    'qrcode',
    'barcode',
    'barcode.writer',
]

a = Analysis(
    [os.path.join(ROOT_DIR, 'laserforge', 'main.py')],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'diffusers', 'transformers', 'accelerate', 'cuda', 'xformers'],
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
    exclude_binaries=True,
    name='LaserForge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT_DIR, 'assets', 'laserforge.ico') if os.path.exists(os.path.join(ROOT_DIR, 'assets', 'laserforge.ico')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LaserForge-Windows-x64',
)
