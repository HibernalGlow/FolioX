# -*- coding: utf-8 -*-
"""Batch OCR routes — local directory scanning with real-time SSE progress."""
import asyncio
import json
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import fitz
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from PIL import Image

from ..config import logger, UPLOAD_DIR
from ..database import get_db
from ..ocr.engine import ocr_image_with_layout, ocr_whole_image
from ..ocr.postprocess import postprocess

router = APIRouter()

# --- Constants ---
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".avif", ".jxl"}
PDF_EXT = ".pdf"

# --- In-memory batch state ---
batch_tasks: dict[str, dict] = {}  # batch_id -> {status, progress, result, cancel}


# --- Fingerprinting ---

def _file_fingerprint(path: Path) -> str:
    """Fast fingerprint: md5 of (first 1MB + file size + mtime)."""
    import hashlib
    h = hashlib.md5()
    try:
        st = path.stat()
        h.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
        with open(path, "rb") as f:
            h.update(f.read(1 << 20))  # first 1MB
    except OSError:
        h.update(str(path).encode())
    return h.hexdigest()


def _load_existing_results(output_path: Path) -> tuple[list[dict], set[str], set[str]]:
    """Load existing ocr_results.json, return (results, source_paths, file_hashes)."""
    if not output_path.exists():
        return [], set(), set()
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            return [], set(), set()
        source_paths = set()
        file_hashes = set()
        for r in existing:
            sp = r.get("source_path", "")
            fh = r.get("file_hash", "")
            if sp:
                source_paths.add(sp)
            if fh:
                file_hashes.add(fh)
        return existing, source_paths, file_hashes
    except Exception:
        return [], set(), set()


def _extract_archive(archive_path: Path, tmp_dir: Path) -> list[Path]:
    """Extract archive, return list of image/PDF files."""
    suffix = archive_path.suffix.lower()
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(tmp_dir)
        elif suffix in {".tar", ".gz", ".bz2", ".xz"}:
            shutil.unpack_archive(str(archive_path), str(tmp_dir))
        elif suffix == ".7z":
            import py7zr
            with py7zr.SevenZipFile(archive_path, mode="r") as z7:
                z7.extractall(path=tmp_dir)
        elif suffix == ".rar":
            import rarfile
            with rarfile.RarFile(archive_path, "r") as rf:
                rf.extractall(tmp_dir)
        else:
            return []
    except Exception as e:
        logger.error(f"[batch] Extract failed: {e}")
        return []

    found = []
    for p in sorted(tmp_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in (IMAGE_EXTS | {PDF_EXT}):
            found.append(p)
    return found


def _pdf_to_images(pdf_path: Path, tmp_dir: Path) -> list[Path]:
    """Convert PDF to page images."""
    doc = fitz.open(str(pdf_path))
    images = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        img_path = tmp_dir / f"page_{i + 1:03d}.png"
        pix.save(str(img_path))
        images.append(img_path)
    doc.close()
    return images


def _collect_files(input_dir: Path, ext_filter: set[str], include_images: bool) -> list[Path]:
    """Collect files to process from directory."""
    files = []
    for p in sorted(input_dir.rglob("*")):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix in ext_filter:
            files.append(p)
        elif include_images and suffix in IMAGE_EXTS:
            files.append(p)
    return files


async def _process_document(source_path: Path, use_layout: bool = True) -> dict:
    """Process a single document, return result dict."""
    t0 = time.time()
    file_hash = _file_fingerprint(source_path)
    result = {
        "source": source_path.name,
        "source_path": str(source_path),
        "file_hash": file_hash,
        "file_size": source_path.stat().st_size,
        "type": "",
        "pages": [],
        "total_time": 0,
        "total_chars": 0,
        "error": None,
    }

    suffix = source_path.suffix.lower()
    page_images: list[Path] = []
    tmp_dirs: list[Path] = []

    try:
        if suffix in ARCHIVE_EXTS:
            result["type"] = "archive"
            tmp = Path(tempfile.mkdtemp(prefix="folio_batch_"))
            tmp_dirs.append(tmp)
            extracted = _extract_archive(source_path, tmp)
            if not extracted:
                result["error"] = "No images/PDFs found in archive"
                return result

            image_files = sorted([f for f in extracted if f.suffix.lower() in IMAGE_EXTS], key=lambda p: p.name)
            pdf_files = [f for f in extracted if f.suffix.lower() == PDF_EXT]

            for pdf_f in pdf_files:
                pdf_tmp = Path(tempfile.mkdtemp(prefix="folio_pdf_"))
                tmp_dirs.append(pdf_tmp)
                page_images.extend(_pdf_to_images(pdf_f, pdf_tmp))
            page_images.extend(image_files)

        elif suffix == PDF_EXT:
            result["type"] = "pdf"
            tmp = Path(tempfile.mkdtemp(prefix="folio_batch_"))
            tmp_dirs.append(tmp)
            page_images = _pdf_to_images(source_path, tmp)

        elif suffix in IMAGE_EXTS:
            result["type"] = "image"
            page_images = [source_path]
        else:
            result["error"] = f"Unsupported file type: {suffix}"
            return result

        if not page_images:
            result["error"] = "No page images found"
            return result

        # OCR all pages
        for i, img_path in enumerate(page_images):
            try:
                t1 = time.time()
                if use_layout:
                    text, regions = await ocr_image_with_layout(str(img_path), merge=True)
                    result["pages"].append({
                        "page": i + 1,
                        "source": img_path.name,
                        "text": text,
                        "regions": [{"idx": r["idx"], "label": r["label"], "bbox": r["bbox"], "text": r["text"]} for r in regions],
                        "time": round(time.time() - t1, 2),
                    })
                else:
                    img = Image.open(str(img_path)).convert("RGB")
                    text = await ocr_whole_image(img)
                    img.close()
                    result["pages"].append({
                        "page": i + 1,
                        "source": img_path.name,
                        "text": text,
                        "regions": [],
                        "time": round(time.time() - t1, 2),
                    })
            except Exception as e:
                result["pages"].append({
                    "page": i + 1,
                    "source": img_path.name,
                    "text": "",
                    "regions": [],
                    "time": 0,
                    "error": str(e),
                })

        result["total_chars"] = sum(len(p.get("text", "")) for p in result["pages"])
        result["total_time"] = round(time.time() - t0, 2)

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[batch] Error processing {source_path}: {e}", exc_info=True)
    finally:
        for td in tmp_dirs:
            if td.exists():
                shutil.rmtree(td, ignore_errors=True)

    return result


@router.post("/api/batch/start")
async def batch_start(
    path: str = Query(..., description="Local directory path to scan"),
    ext: str = Query(".zip,.rar,.7z,.tar,.gz,.pdf", description="Comma-separated file extensions"),
    images: bool = Query(False, description="Also process standalone image files"),
    layout: bool = Query(True, description="Use layout detection"),
    incremental: bool = Query(False, description="Skip already-processed files"),
):
    """Start a batch OCR job on a local directory. Returns batch_id, then streams progress via SSE."""
    path = _clean_path(path)
    input_dir = Path(path).resolve()
    if not input_dir.is_dir():
        raise HTTPException(400, f"Not a directory: {path}")

    ext_filter = {e.strip().lower() for e in ext.split(",") if e.strip()}
    files = _collect_files(input_dir, ext_filter, images)
    if not files:
        raise HTTPException(400, f"No matching files found in {path}")

    batch_id = str(uuid.uuid4())[:8]

    # Load previous results for incremental (path + hash dedup)
    output_path = input_dir / "ocr_results.json"
    existing_results: list[dict] = []
    existing_sources: set[str] = set()
    existing_hashes: set[str] = set()
    if incremental:
        existing_results, existing_sources, existing_hashes = _load_existing_results(output_path)

    # Filter out already-processed: path match first, then hash match
    skipped_by_path = 0
    skipped_by_hash = 0
    todo: list[Path] = []
    for f in files:
        fstr = str(f)
        if fstr in existing_sources:
            skipped_by_path += 1
            continue
        # Compute hash only if incremental and path not matched
        if incremental and existing_hashes:
            fh = _file_fingerprint(f)
            if fh in existing_hashes:
                skipped_by_hash += 1
                continue
        todo.append(f)

    # Initialize batch state
    batch_tasks[batch_id] = {
        "status": "running",
        "total": len(todo),
        "done": 0,
        "current": "",
        "results": list(existing_results) if incremental else [],
        "cancel": False,
        "output_path": str(output_path),
        "start_time": time.time(),
    }

    # Return batch_id immediately, then start processing in background
    asyncio.create_task(_run_batch(batch_id, todo, layout, output_path))

    return {
        "batch_id": batch_id,
        "total": len(todo),
        "skipped": len(files) - len(todo),
        "skipped_by_path": skipped_by_path,
        "skipped_by_hash": skipped_by_hash,
    }


async def _run_batch(
    batch_id: str,
    files: list[Path],
    use_layout: bool,
    output_path: Path,
):
    """Background task to process files and save results."""
    state = batch_tasks[batch_id]
    results = list(state["results"])  # copy existing results if incremental

    try:
        for i, f in enumerate(files):
            if state["cancel"]:
                state["status"] = "cancelled"
                break

            state["current"] = f.name
            result = await _process_document(f, use_layout=use_layout)
            result["batch_index"] = i
            results.append(result)
            state["done"] = i + 1
            state["results"] = results

            # Save intermediate results
            try:
                with open(output_path, "w", encoding="utf-8") as fp:
                    json.dump(results, fp, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"[batch] Failed to save intermediate results: {e}")

        state["status"] = "cancelled" if state["cancel"] else "completed"
        state["elapsed"] = round(time.time() - state["start_time"], 1)

        # Final save
        with open(output_path, "w", encoding="utf-8") as fp:
            json.dump(results, fp, ensure_ascii=False, indent=2)

        total_chars = sum(r.get("total_chars", 0) for r in results)
        errors = sum(1 for r in results if r.get("error"))
        logger.info(f"[batch] {batch_id} done: {len(results)} docs, {total_chars} chars, {errors} errors")

    except Exception as e:
        state["status"] = "error"
        state["error"] = str(e)
        logger.error(f"[batch] {batch_id} failed: {e}", exc_info=True)


@router.get("/api/batch/{batch_id}/progress")
async def batch_progress(batch_id: str):
    """SSE endpoint for real-time batch progress."""
    if batch_id not in batch_tasks:
        raise HTTPException(404, "Batch not found")

    async def event_stream():
        state = batch_tasks[batch_id]
        last_done = -1

        while True:
            # Send progress update
            data = {
                "status": state["status"],
                "total": state["total"],
                "done": state["done"],
                "current": state.get("current", ""),
                "elapsed": round(time.time() - state["start_time"], 1) if "start_time" in state else 0,
            }

            # If new results arrived, send them
            if state["done"] > last_done:
                results = state.get("results", [])
                # Send only newly completed results
                new_results = results[last_done + 1:] if last_done >= 0 else []
                if new_results:
                    data["new_results"] = [
                        {
                            "source": r.get("source", ""),
                            "type": r.get("type", ""),
                            "pages": len(r.get("pages", [])),
                            "total_chars": r.get("total_chars", 0),
                            "total_time": r.get("total_time", 0),
                            "error": r.get("error"),
                        }
                        for r in new_results
                    ]
                    # Include full text for the latest result(s)
                    data["latest_texts"] = new_results[-1:] if new_results else []
                last_done = state["done"]

            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            if state["status"] in ("completed", "cancelled", "error"):
                # Send final summary
                summary = {
                    "status": state["status"],
                    "total": state["total"],
                    "done": state["done"],
                    "elapsed": state.get("elapsed", 0),
                    "output_path": state.get("output_path", ""),
                    "error": state.get("error"),
                }
                total_results = state.get("results", [])
                if total_results:
                    summary["total_chars"] = sum(r.get("total_chars", 0) for r in total_results)
                    summary["total_errors"] = sum(1 for r in total_results if r.get("error"))
                yield f"data: {json.dumps(summary, ensure_ascii=False)}\n\n"
                # Cleanup after a delay
                await asyncio.sleep(30)
                batch_tasks.pop(batch_id, None)
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/batch/{batch_id}/cancel")
async def batch_cancel(batch_id: str):
    """Cancel a running batch job."""
    if batch_id not in batch_tasks:
        raise HTTPException(404, "Batch not found")
    batch_tasks[batch_id]["cancel"] = True
    return {"status": "cancelling"}


@router.get("/api/batch/{batch_id}/results")
async def batch_results(batch_id: str):
    """Get current results of a batch job."""
    if batch_id not in batch_tasks:
        raise HTTPException(404, "Batch not found")
    state = batch_tasks[batch_id]
    return {
        "batch_id": batch_id,
        "status": state["status"],
        "total": state["total"],
        "done": state["done"],
        "results": state["results"],
    }


def _clean_path(p: str) -> str:
    """Strip wrapping quotes from a path string."""
    p = p.strip()
    if len(p) >= 2 and ((p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'"))):
        p = p[1:-1].strip()
    return p


@router.post("/api/batch/browse")
async def batch_browse(path: str = Query(..., description="Directory path to browse")):
    """Browse a local directory to show available files for batch processing."""
    path = _clean_path(path)
    input_dir = Path(path).resolve()
    if not input_dir.exists():
        raise HTTPException(400, f"Path does not exist: {path}")
    if not input_dir.is_dir():
        raise HTTPException(400, f"Not a directory: {path}")

    # Pre-read existing results for fast "processed" marking
    output_path = input_dir / "ocr_results.json"
    _, existing_sources, existing_hashes = _load_existing_results(output_path)

    archives = []
    image_files = []
    pdfs = []

    for p in sorted(input_dir.iterdir()):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        size_mb = round(p.stat().st_size / 1024 / 1024, 1)
        fstr = str(p)

        # Check if already processed (path first, then hash)
        processed = fstr in existing_sources
        if not processed and existing_hashes:
            processed = _file_fingerprint(p) in existing_hashes

        entry = {"name": p.name, "size_mb": size_mb, "path": fstr, "processed": processed}
        if suffix in ARCHIVE_EXTS:
            archives.append(entry)
        elif suffix == PDF_EXT:
            pdfs.append(entry)
        elif suffix in IMAGE_EXTS:
            image_files.append(entry)

    # Subdirectories
    subdirs = []
    for p in sorted(input_dir.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            subdirs.append({"name": p.name, "path": str(p)})

    total = len(archives) + len(pdfs) + len(image_files)
    processed_count = sum(1 for f in (archives + pdfs + image_files) if f["processed"])

    return {
        "path": str(input_dir),
        "parent": str(input_dir.parent),
        "subdirs": subdirs,
        "archives": archives,
        "pdfs": pdfs,
        "images": image_files,
        "total_files": total,
        "processed_count": processed_count,
    }
