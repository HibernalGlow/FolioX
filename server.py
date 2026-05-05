#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Folio-OCR Server — backward-compatible entry point.
Usage: python server.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cli.app import cli

if __name__ == "__main__":
    # Default to web mode if no args given
    if len(sys.argv) == 1:
        sys.argv.append("web")
    cli()
