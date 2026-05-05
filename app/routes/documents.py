# -*- coding: utf-8 -*-
"""Document CRUD routes — list, get, delete, save text."""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import logger, UPLOAD_DIR
from ..database import get_db
from ..utils import safe_doc_path

router = APIRouter()


class SaveTextRequest(BaseModel):
    text: str


@router.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document and its images."""
    import shutil
    with get_db() as conn:
        row = conn.execute("SELECT doc_id FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Document not found")
        conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))

    doc_dir = safe_doc_path(doc_id)
    if doc_dir.exists():
        shutil.rmtree(doc_dir, ignore_errors=True)

    logger.info(f"[delete] Document {doc_id} removed")
    return {"success": True}


@router.put("/api/pages/{doc_id}/{page_num}/text")
async def save_page_text(doc_id: str, page_num: int, req: SaveTextRequest):
    """Save user-edited text for a page."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE pages SET ocr_text=? WHERE doc_id=? AND num=?",
            (req.text, doc_id, page_num),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Page not found")
    return {"success": True}


@router.get("/api/documents")
async def list_documents():
    """List all documents with page counts."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT d.doc_id, d.filename, d.created_at,
                   COUNT(p.num) AS page_count,
                   SUM(CASE WHEN p.ocr_text IS NOT NULL THEN 1 ELSE 0 END) AS ocr_count
            FROM documents d
            LEFT JOIN pages p ON d.doc_id = p.doc_id
            GROUP BY d.doc_id
            ORDER BY d.created_at DESC
        """).fetchall()
    return [
        {
            "doc_id": r["doc_id"],
            "filename": r["filename"],
            "created_at": r["created_at"],
            "page_count": r["page_count"],
            "ocr_count": r["ocr_count"],
        }
        for r in rows
    ]


@router.get("/api/documents/{doc_id}")
async def get_document(doc_id: str):
    """Load a document with all its pages (for restore)."""
    with get_db() as conn:
        doc_row = conn.execute(
            "SELECT * FROM documents WHERE doc_id=?", (doc_id,)
        ).fetchone()
        if doc_row is None:
            raise HTTPException(404, "Document not found")
        pages = conn.execute(
            "SELECT * FROM pages WHERE doc_id=? ORDER BY num", (doc_id,)
        ).fetchall()

    return {
        "doc_id": doc_row["doc_id"],
        "filename": doc_row["filename"],
        "created_at": doc_row["created_at"],
        "pages": [
            {
                "num": p["num"],
                "filename": p["filename"],
                "image_url": f"/api/images/{doc_id}/{p['filename']}",
                "ocr_text": p["ocr_text"],
                "ocr_regions": json.loads(p["ocr_regions"]) if p["ocr_regions"] else None,
                "ocr_time": p["ocr_time"],
            }
            for p in pages
        ],
    }
