# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Folio-OCR Desktop App
使用方法: pyinstaller Folio-OCR.spec
"""
import sys
from pathlib import Path

block_cipher = None

APP_ROOT = Path('.')

# 需要打包的前端资源文件
datas = [
    (str(APP_ROOT / 'index.html'), '.'),
    (str(APP_ROOT / 'script.js'), '.'),
    (str(APP_ROOT / 'style.css'), '.'),
    (str(APP_ROOT / 'latex_unicode.json'), '.'),
]

# PyInstaller 隐式导入（未被自动检测到的依赖）
hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'multipart',
    'transformers',
    'safetensors',
    'PIL',
    'fitz',
    'docx',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'pandas',
        'notebook',
        'IPython',
        'tkinter',
    ],
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
    name='Folio-OCR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,        # 不显示命令行窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,            # 可替换为自定义 .ico 文件
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Folio-OCR',
)
