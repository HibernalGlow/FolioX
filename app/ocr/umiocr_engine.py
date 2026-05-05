# -*- coding: utf-8 -*-
"""UmiOCR engine — HTTP API client for Umi-OCR local service.

Umi-OCR provides a local HTTP server (default http://127.0.0.1:1224)
with a simple REST API for OCR. This module wraps that API.

API docs: https://github.com/hiroi-sora/Umi-OCR/blob/main/docs/http/api_ocr.md
"""
import base64
import io

import httpx
from PIL import Image

from ..config import logger, UMIOCR_BASE, OCR_MAX_LONG_SIDE

# Shared httpx client (set by caller on startup)
http_client: httpx.AsyncClient | None = None


def image_to_b64(img: Image.Image) -> str:
    """Convert PIL Image to base64 string for UmiOCR.
    Automatically downscales if the image longest side exceeds OCR_MAX_LONG_SIDE.
    """
    w, h = img.size
    long_side = max(w, h)
    if long_side > OCR_MAX_LONG_SIDE:
        ratio = OCR_MAX_LONG_SIDE / long_side
        nw, nh = int(w * ratio), int(h * ratio)
        img = img.resize((nw, nh), Image.LANCZOS)

    if img.mode != "RGB":
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


async def ocr_single(image_b64: str) -> str:
    """Send a single image to UmiOCR for text recognition.

    Returns plain text result.
    """
    payload = {
        "base64": image_b64,
        "options": {
            "data.format": "text",
            "tbpu.parser": "multi_para",
        },
    }
    resp = await http_client.post(
        f"{UMIOCR_BASE}/api/ocr",
        json=payload,
    )
    resp.raise_for_status()
    result = resp.json()

    code = result.get("code", -1)
    if code == 100:
        # Success — data is plain text string
        return result.get("data", "")
    elif code == 101:
        # No text found in image
        return ""
    else:
        # Error
        err_msg = result.get("data", "unknown error") if isinstance(result.get("data"), str) else str(result.get("data"))
        raise RuntimeError(f"UmiOCR error (code={code}): {err_msg}")


async def ocr_single_dict(image_b64: str) -> list[dict]:
    """Send a single image to UmiOCR, return detailed result with bounding boxes.

    Returns list of dicts, each with: text, score, box, end.
    """
    payload = {
        "base64": image_b64,
        "options": {
            "data.format": "dict",
            "tbpu.parser": "multi_para",
        },
    }
    resp = await http_client.post(
        f"{UMIOCR_BASE}/api/ocr",
        json=payload,
    )
    resp.raise_for_status()
    result = resp.json()

    code = result.get("code", -1)
    if code == 100:
        return result.get("data", [])
    elif code == 101:
        return []
    else:
        err_msg = result.get("data", "unknown error") if isinstance(result.get("data"), str) else str(result.get("data"))
        raise RuntimeError(f"UmiOCR error (code={code}): {err_msg}")


async def check_umiocr() -> dict:
    """Check UmiOCR service status."""
    try:
        resp = await http_client.get(f"{UMIOCR_BASE}/api/ocr/get_options", timeout=5.0)
        resp.raise_for_status()
        return {"online": True}
    except Exception:
        return {"online": False}
