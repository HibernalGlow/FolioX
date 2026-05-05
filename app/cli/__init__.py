# -*- coding: utf-8 -*-
"""
Folio-OCR CLI — typer application definition.

Subcommands:
    folio web       Start FastAPI web server
    folio desktop   Start pywebview desktop app
    folio batch     Batch OCR from CLI (interactive + progress)
    folio ocr       OCR a single file
"""
from .app import cli
