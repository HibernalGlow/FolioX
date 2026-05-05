# -*- coding: utf-8 -*-
"""Upload and image serving routes."""
import asyncio
import io
import json
import uuid
from datetime import datetime
from pathlib import Path

import fitz
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from PIL import Image

from ..config import logger, UPLOAD_DIR, ALLOWED_SUFFIXES, MIME_MAP
from ..database import get_db
from ..utils import safe_doc_path

router = APIRouter()


@router.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """Upload one or more files. Multiple images become pages of one document.
    Always streams pages via SSE so the frontend gets incremental updates.
    """
    if not files:
        raise HTTPException(400, "No files provided")

    for f in files:
        if Path(f.filename).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(400, f"Unsupported file type: {f.filename}")

    file_data: list[tuple[str, str, bytes]] = []
    for f in files:
        suffix = Path(f.filename).suffix.lower()
        content = await f.read()
        file_data.append((f.filename, suffix, content))

    doc_id = str(uuid.uuid4())
    doc_dir = UPLOAD_DIR / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    if len(file_data) == 1:
        display_name = file_data[0][0]
    else:
        display_name = f"{len(file_data)} files"

    created_at = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO documents (doc_id, filename, created_at) VALUES (?, ?, ?)",
            (doc_id, display_name, created_at),
        )

    async def generate():
        page_num = 0

        yield f"data: {json.dumps({'type': 'init', 'doc_id': doc_id, 'filename': display_name})}\n\n"

        for fname, suffix, content in file_data:
            if suffix == ".pdf":
                pdf_path = doc_dir / f"src_{uuid.uuid4().hex[:8]}.pdf"
                with open(pdf_path, "wb") as fp:
                    fp.write(content)

                mat = fitz.Matrix(2.0, 2.0)
                doc = fitz.open(str(pdf_path))
                for fitz_page in doc:
                    page_num += 1
                    pix = fitz_page.get_pixmap(matrix=mat)
                    img_name = f"page_{page_num:03d}.png"
                    pix.save(str(doc_dir / img_name))

                    with get_db() as conn:
                        conn.execute(
                            "INSERT INTO pages (doc_id, num, filename) VALUES (?, ?, ?)",
                            (doc_id, page_num, img_name),
                        )

                    page_info = {
                        "num": page_num,
                        "filename": img_name,
                        "image_url": f"/api/images/{doc_id}/{img_name}",
                        "ocr_text": None,
                        "ocr_regions": None,
                        "ocr_time": None,
                    }
                    yield f"data: {json.dumps({'type': 'page', 'page': page_info})}\n\n"
                    await asyncio.sleep(0)

                doc.close()
                pdf_path.unlink(missing_ok=True)
            else:
                page_num += 1
                NEED_CONVERT = {'.jxl'}
                if suffix in NEED_CONVERT:
                    img = Image.open(io.BytesIO(content)).convert("RGB")
                    img_name = f"page_{page_num:03d}.png"
                    img.save(str(doc_dir / img_name), format="PNG")
                else:
                    img_name = f"page_{page_num:03d}{suffix}"
                    with open(doc_dir / img_name, "wb") as fp:
                        fp.write(content)

                with get_db() as conn:
                    conn.execute(
                        "INSERT INTO pages (doc_id, num, filename) VALUES (?, ?, ?)",
                        (doc_id, page_num, img_name),
                    )

                page_info = {
                    "num": page_num,
                    "filename": img_name,
                    "image_url": f"/api/images/{doc_id}/{img_name}",
                    "ocr_text": None,
                    "ocr_regions": None,
                    "ocr_time": None,
                }
                yield f"data: {json.dumps({'type': 'page', 'page': page_info})}\n\n"
                await asyncio.sleep(0)

        yield f"data: {json.dumps({'type': 'done', 'page_count': page_num})}\n\n"
        logger.info(f"[upload] {display_name} -> {doc_id}, {page_num} page(s)")

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/images/{doc_id}/{filename}")
async def get_image(doc_id: str, filename: str):
    """Serve an uploaded page image."""
    file_path = safe_doc_path(doc_id, filename)
    if not file_path.exists():
        raise HTTPException(404, "Image not found")
    suffix = file_path.suffix.lower()
    media_type = MIME_MAP.get(suffix, 'application/octet-stream')
    return FileResponse(file_path, media_type=media_type)
