# -*- coding: utf-8 -*-
"""OCR module — public API."""
from .engine import (
    ocr_image_with_layout,
    ocr_whole_image,
    ocr_single,
    image_to_b64,
    check_ollama,
    check_umiocr,
    check_backend,
    http_client,
)
from .postprocess import postprocess
