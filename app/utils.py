# -*- coding: utf-8 -*-
"""Utility functions — PDF conversion, path safety, format constants."""
import io
import shutil
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from fastapi import HTTPException

from .config import UPLOAD_DIR


def pdf_to_images(pdf_path: str, output_dir: Path) -> list[str]:
    """Convert PDF pages to images in the specified directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filenames = []
    mat = fitz.Matrix(2.0, 2.0)
    doc = fitz.open(pdf_path)

    for page_num, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat)
        filename = f"page_{page_num + 1:03d}.png"
        pix.save(str(output_dir / filename))
        filenames.append(filename)

    doc.close()
    return filenames


def safe_doc_path(doc_id: str, filename: str = "") -> Path:
    """Build a path inside UPLOAD_DIR/{doc_id} with traversal protection."""
    doc_dir = (UPLOAD_DIR / doc_id).resolve()
    if not str(doc_dir).startswith(str(UPLOAD_DIR.resolve())):
        raise HTTPException(403, "Invalid document ID")
    if filename:
        file_path = (doc_dir / filename).resolve()
        if not str(file_path).startswith(str(doc_dir)):
            raise HTTPException(403, "Invalid filename")
        return file_path
    return doc_dir
