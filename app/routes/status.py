# -*- coding: utf-8 -*-
"""Status and model loading routes."""
import asyncio
import os
import subprocess

from fastapi import APIRouter, HTTPException

from ..config import logger, OLLAMA_BASE, OLLAMA_MODEL, FRONTEND_DIR
from ..layout.model import ensure_model, is_loaded as layout_is_loaded
from ..ocr.engine import check_ollama, http_client

router = APIRouter()


@router.get("/")
async def root():
    """Serve frontend page."""
    from fastapi.responses import HTMLResponse
    index_path = FRONTEND_DIR / "index.html"
    with open(str(index_path), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@router.get("/api/status")
async def status():
    """Check service status."""
    ollama = await check_ollama()
    return {
        "status": "running",
        "model_loaded": ollama["model_loaded"],
        "layout_loaded": layout_is_loaded(),
        "device": "ollama",
        "gpu": {"name": f"Ollama ({OLLAMA_MODEL})"} if ollama["online"] else None,
    }


async def _ensure_ollama_running() -> dict:
    """Start Ollama if not running, wait until ready."""
    ollama = await check_ollama()
    if ollama["online"]:
        return ollama

    logger.info("[ollama] Not running, attempting to start ollama serve...")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        logger.info("[ollama] Popen launched, waiting for service...")
    except FileNotFoundError:
        logger.error("[ollama] 'ollama' command not found in PATH")
        raise HTTPException(500, "Ollama not found. Please install Ollama first.")
    except Exception as e:
        logger.error(f"[ollama] Failed to start: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to start Ollama: {e}")

    for i in range(60):
        await asyncio.sleep(0.5)
        ollama = await check_ollama()
        if ollama["online"]:
            logger.info(f"[ollama] Started in {(i + 1) * 0.5:.1f}s")
            return ollama

    raise HTTPException(500, "Failed to start Ollama after 30s")


@router.post("/api/load-model")
async def load_model_endpoint():
    """Load layout model + start Ollama + pre-warm OCR model."""
    import time

    if not layout_is_loaded():
        await asyncio.to_thread(ensure_model)

    ollama = await _ensure_ollama_running()

    if not ollama["model_loaded"]:
        raise HTTPException(500, f"Model '{OLLAMA_MODEL}' not found. Run: ollama pull {OLLAMA_MODEL}")

    try:
        t0 = time.time()
        await http_client.post(
            f"{OLLAMA_BASE}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": "hi"}], "stream": False},
        )
        logger.info(f"[load_model] Warmup done: {time.time() - t0:.2f}s")
    except Exception as e:
        logger.warning(f"[load_model] Warmup failed: {e}")
    return {"success": True, "message": "All models loaded"}
