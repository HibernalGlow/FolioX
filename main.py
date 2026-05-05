#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Folio-OCR — 统一入口

用法:
    python main.py web          启动 Web 服务
    python main.py desktop      启动桌面应用
    python main.py batch        批量 OCR（交互式）
    python main.py batch D:\scans  批量 OCR（指定路径）
    python main.py ocr file.pdf   单文件 OCR

安装后可直接使用:
    folio web / folio desktop / folio batch / folio ocr
"""
import sys
from pathlib import Path

# Ensure project root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cli.app import cli

if __name__ == "__main__":
    cli()
