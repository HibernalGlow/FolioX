# -*- coding: utf-8 -*-
"""OCR engine — image encoding, Ollama API calls, and orchestration."""
import asyncio
import base64
import io

import httpx
from PIL import Image

from ..config import (
    logger, OLLAMA_BASE, OLLAMA_MODEL, OCR_PROMPT,
    OCR_MAX_LONG_SIDE, MAX_IMAGE_HEIGHT, SEGMENT_OVERLAP,
)
from ..layout import detect_layout
from ..layout.columns import merge_adjacent_regions, group_bbox, dedup_regions
from .postprocess import postprocess

# Shared httpx client (initialized on app startup)
http_client: httpx.AsyncClient | None = None


def image_to_b64(img: Image.Image) -> str:
    """Convert PIL Image to base64 string for Ollama OCR.
    Uses WebP encoding (quality=90) for smallest payload with full OCR quality.
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
    img.save(buf, format="WEBP", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


async def ocr_single(image_b64: str) -> str:
    """Send a single image to Ollama for OCR."""
    resp = await http_client.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": OCR_PROMPT,
                    "images": [image_b64],
                }
            ],
            "stream": False,
        },
    )
    resp.raise_for_status()
    result = resp.json()
    return result.get("message", {}).get("content", "")


def _split_image(img: Image.Image) -> list[Image.Image]:
    """Split a tall image into overlapping segments."""
    w, h = img.size
    step = MAX_IMAGE_HEIGHT - SEGMENT_OVERLAP
    segments = []
    y = 0
    while y < h:
        bottom = min(y + MAX_IMAGE_HEIGHT, h)
        seg = img.crop((0, y, w, bottom))
        segments.append(seg)
        y += step
        if bottom == h:
            break
    return segments


async def ocr_whole_image(img: Image.Image) -> str:
    """Fallback: OCR whole image, with splitting for tall images."""
    w, h = img.size
    if h > MAX_IMAGE_HEIGHT:
        segments = _split_image(img)
    else:
        segments = [img]

    seg_b64s = [image_to_b64(seg) for seg in segments]
    results = await asyncio.gather(*[ocr_single(b64) for b64 in seg_b64s])
    all_text = []
    for text in results:
        text = postprocess(text)
        if text:
            all_text.append(text)
    return "\n\n".join(all_text)


async def ocr_image_with_layout(image_path: str, merge: bool = True) -> tuple[str, list[dict]]:
    """Run layout detection + OCR.
    merge=True:  adjacent text regions merged into fewer OCR calls (fast).
    merge=False: each region OCR'd individually (fine-grained for proofreading).
    """
    import time
    t0 = time.time()
    img = Image.open(image_path).convert("RGB")

    t1 = time.time()
    raw_regions = detect_layout(img)
    logger.info(f"[OCR] Layout detection: {time.time() - t1:.2f}s, {len(raw_regions)} regions")

    if not raw_regions:
        logger.info("[OCR] No layout regions, fallback to whole-image OCR")
        text = await ocr_whole_image(img)
        img.close()
        elapsed = time.time() - t0
        logger.info(f"[OCR] TOTAL (fallback): {elapsed:.2f}s")
        return text, []

    regions = []

    if merge:
        groups = merge_adjacent_regions(raw_regions)
        logger.info(f"[OCR] Merged {len(raw_regions)} regions into {len(groups)} groups")

        group_crops = []
        for gi, group in enumerate(groups):
            bbox = group_bbox(group)
            cropped = img.crop(bbox)
            seg_b64 = image_to_b64(cropped)
            label = group[0]["label"] if len(group) == 1 else "text"
            group_crops.append((gi, group, bbox, seg_b64, label))

        async def _ocr_group(gi, group, bbox, seg_b64, label):
            text = await ocr_single(seg_b64)
            text = postprocess(text)
            return gi, group, bbox, label, text

        results = await asyncio.gather(*[
            _ocr_group(gi, group, bbox, seg_b64, label)
            for gi, group, bbox, seg_b64, label in group_crops
        ])
        for gi, group, bbox, label, text in results:
            regions.append({
                "idx": gi,
                "label": label,
                "bbox": bbox,
                "text": text or "",
            })
            logger.info(f"[OCR] Group {gi+1}/{len(groups)} ({label}, {len(group)} merged): {len(text)} chars")
    else:
        region_crops = []
        for i, region in enumerate(raw_regions):
            bbox = region["bbox"]
            cropped = img.crop(bbox)
            seg_b64 = image_to_b64(cropped)
            region_crops.append((i, region, bbox, seg_b64))

        async def _ocr_region(i, region, bbox, seg_b64):
            text = await ocr_single(seg_b64)
            text = postprocess(text)
            return i, region, bbox, text

        results = await asyncio.gather(*[
            _ocr_region(i, region, bbox, seg_b64)
            for i, region, bbox, seg_b64 in region_crops
        ])
        for i, region, bbox, text in results:
            regions.append({
                "idx": i,
                "label": region["label"],
                "bbox": bbox,
                "text": text or "",
            })
            logger.info(f"[OCR] Region {i+1}/{len(raw_regions)} ({region['label']}): {len(text)} chars")

    img.close()

    regions = dedup_regions(regions)
    combined = "\n\n".join(r["text"] for r in regions if r["text"])
    combined = dedup_lines(combined)
    logger.info(f"[OCR] TOTAL: {time.time() - t0:.2f}s ({len(raw_regions)} regions, {len(regions)} calls, merge={'on' if merge else 'off'})")
    return combined, regions


async def check_ollama() -> dict:
    """Check Ollama status and model availability."""
    try:
        resp = await http_client.get(f"{OLLAMA_BASE}/api/tags", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        has_model = any(OLLAMA_MODEL in m for m in models)
        return {"online": True, "model_loaded": has_model, "models": models}
    except Exception:
        return {"online": False, "model_loaded": False, "models": []}


# Import here to avoid circular dependency
from .postprocess import dedup_lines
