#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch OCR — backward-compatible entry point.
Usage: python batch_ocr.py [PATH] [OPTIONS]

For the full CLI experience, use: python main.py batch
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cli.app import cli

if __name__ == "__main__":
    # Insert 'batch' subcommand before user args
    sys.argv = [sys.argv[0], "batch"] + sys.argv[1:]
    cli()
