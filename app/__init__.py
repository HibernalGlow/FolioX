# -*- coding: utf-8 -*-
"""
Folio-OCR Server — FastAPI application factory.
All modules are wired together here.
"""
import asyncio
import shutil

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import logger, FRONTEND_DIR, UPLOAD_DIR
from .database import get_db
from .ocr.engine import http_client
from .layout.model import ensure_model, is_loaded as layout_is_loaded
from .routes import all_routers

# --- Create FastAPI app ---
app = FastAPI(title="Folio-OCR Service", version="3.2.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all route routers
for router in all_routers:
    app.include_router(router)


# --- Lifecycle events ---
@app.on_event("startup")
async def startup_event():
    """Initialize httpx client, clean up orphans, auto-load models."""
    import httpx as _httpx
    from .ocr import engine as _engine
    _engine.http_client = _httpx.AsyncClient(timeout=_httpx.Timeout(300.0))

    # Clean up orphan directories not tracked in DB
    with get_db() as conn:
        rows = conn.execute("SELECT doc_id FROM documents").fetchall()
        known_ids = {r["doc_id"] for r in rows}
    for child in UPLOAD_DIR.iterdir():
        if child.is_dir() and child.name not in known_ids:
            logger.info(f"[cleanup] Removing orphan directory: {child}")
            shutil.rmtree(child, ignore_errors=True)

    # Auto-load models in background
    async def _auto_load():
        try:
            # Import here to avoid circular dependency at module level
            from .routes.status import load_model_endpoint
            await load_model_endpoint()
            logger.info("[startup] Auto-load models completed")
        except Exception as e:
            logger.warning(f"[startup] Auto-load models failed: {e}")

    asyncio.create_task(_auto_load())


@app.on_event("shutdown")
async def shutdown_event():
    """Close httpx client."""
    from .ocr import engine as _engine
    if _engine.http_client:
        await _engine.http_client.aclose()


# Static files — must be last so it doesn't shadow API routes
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
