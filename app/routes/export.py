# -*- coding: utf-8 -*-
"""Export route — DOCX generation."""
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..database import get_db
from ..export import ExportRequest, build_docx

router = APIRouter()


@router.post("/api/export/{doc_id}")
async def export_docx(doc_id: str, req: ExportRequest):
    """Export document as a real DOCX file."""
    with get_db() as conn:
        doc_meta = conn.execute(
            "SELECT * FROM documents WHERE doc_id=?", (doc_id,)
        ).fetchone()
    if doc_meta is None:
        raise HTTPException(404, "Document not found")

    fallback = (doc_meta["filename"] or "Document").replace(".pdf", "")
    title = req.title or fallback

    buf = build_docx(title, req.pages)

    safe_name = f"{title}.docx"
    encoded_name = quote(safe_name)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"
        },
    )
