# -*- coding: utf-8 -*-
"""OCR routes — single page and all pages."""
import asyncio
import json
import time

import httpx
from fastapi import APIRouter, HTTPException, Query

from ..config import logger
from ..database import get_db
from ..utils import safe_doc_path
from ..ocr.engine import ocr_image_with_layout

router = APIRouter()


@router.post("/api/ocr/{doc_id}/{page_num}")
async def ocr_single_page(doc_id: str, page_num: int, layout: bool = Query(True), force: bool = Query(False)):
    """Run OCR on a single page. Pass ?force=true to re-scan ignoring cache."""
    with get_db() as conn:
        page = conn.execute(
            "SELECT * FROM pages WHERE doc_id=? AND num=?", (doc_id, page_num)
        ).fetchone()
    if page is None:
        raise HTTPException(404, f"Page {page_num} not found")

    if page["ocr_text"] is not None and not force:
        return {
            "doc_id": doc_id,
            "page_num": page_num,
            "text": page["ocr_text"],
            "regions": json.loads(page["ocr_regions"]) if page["ocr_regions"] else [],
            "time": page["ocr_time"],
            "cached": True,
        }

    image_path = safe_doc_path(doc_id, page["filename"])
    if not image_path.exists():
        raise HTTPException(404, "Image file not found")

    try:
        t0 = time.time()
        text, regions = await ocr_image_with_layout(str(image_path), merge=not layout)
        elapsed = round(time.time() - t0, 2)

        with get_db() as conn:
            conn.execute(
                "UPDATE pages SET ocr_text=?, ocr_regions=?, ocr_time=? WHERE doc_id=? AND num=?",
                (text, json.dumps(regions), elapsed, doc_id, page_num),
            )

        return {
            "doc_id": doc_id,
            "page_num": page_num,
            "text": text,
            "regions": regions,
            "time": elapsed,
            "cached": False,
        }
    except httpx.HTTPStatusError as e:
        detail = e.response.text
        logger.error(f"[OCR] Ollama error: {detail}", exc_info=True)
        raise HTTPException(500, f"OCR failed: {detail}")
    except Exception as e:
        logger.error(f"[OCR] Error: {e}", exc_info=True)
        raise HTTPException(500, f"OCR failed: {e}")


@router.post("/api/ocr/{doc_id}/all")
async def ocr_all_pages(doc_id: str, layout: bool = Query(True)):
    """Run OCR on all pages of a document. Pass ?layout=false to skip layout detection."""
    with get_db() as conn:
        doc_row = conn.execute(
            "SELECT * FROM documents WHERE doc_id=?", (doc_id,)
        ).fetchone()
        if doc_row is None:
            raise HTTPException(404, "Document not found")
        pages = conn.execute(
            "SELECT * FROM pages WHERE doc_id=? ORDER BY num", (doc_id,)
        ).fetchall()

    results = []
    uncached = []

    for page in pages:
        if page["ocr_text"] is not None:
            results.append({
                "page_num": page["num"],
                "text": page["ocr_text"],
                "regions": json.loads(page["ocr_regions"]) if page["ocr_regions"] else [],
                "time": page["ocr_time"],
                "cached": True,
            })
        else:
            results.append(None)
            uncached.append((len(results) - 1, page))

    async def _process_page(idx, page):
        image_path = safe_doc_path(doc_id, page["filename"])
        try:
            t0 = time.time()
            text, regions = await ocr_image_with_layout(str(image_path), merge=not layout)
            elapsed = round(time.time() - t0, 2)

            with get_db() as conn:
                conn.execute(
                    "UPDATE pages SET ocr_text=?, ocr_regions=?, ocr_time=? WHERE doc_id=? AND num=?",
                    (text, json.dumps(regions), elapsed, doc_id, page["num"]),
                )

            return idx, {
                "page_num": page["num"],
                "text": text,
                "regions": regions,
                "time": elapsed,
                "cached": False,
            }
        except Exception as e:
            logger.error(f"[OCR] Page {page['num']} error: {e}", exc_info=True)
            return idx, {
                "page_num": page["num"],
                "text": None,
                "regions": [],
                "time": None,
                "error": str(e),
            }

    if uncached:
        page_results = await asyncio.gather(*[
            _process_page(idx, page) for idx, page in uncached
        ])
        for idx, result in page_results:
            results[idx] = result

    return {
        "doc_id": doc_id,
        "filename": doc_row["filename"],
        "results": results,
    }
