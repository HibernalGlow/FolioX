#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch OCR — scan a local directory for archives/images, OCR them, output JSON.

Usage:
    # Process all archives in a directory
    python batch_ocr.py D:\scans

    # Process specific file types
    python batch_ocr.py D:\scans --ext .zip,.rar,.7z,.pdf

    # Include standalone images too
    python batch_ocr.py D:\scans --images

    # Custom output
    python batch_ocr.py D:\scans -o results.json

    # Skip already-processed files (incremental mode)
    python batch_ocr.py D:\scans --incremental

    # Limit concurrency (default: 4)
    python batch_ocr.py D:\scans -j 2

    # No layout detection (faster, less structured)
    python batch_ocr.py D:\scans --no-layout
"""
import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import after sys.path is set
from app.config import logger, OLLAMA_BASE, OLLAMA_MODEL
from app.database import init_db, get_db
from app.ocr.engine import ocr_image_with_layout, ocr_whole_image, image_to_b64, ocr_single
from app.ocr.postprocess import postprocess, dedup_lines
from app.layout import detect_layout

# --- Archive extraction ---

ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".avif", ".jxl"}
PDF_EXT = ".pdf"


# --- Fingerprinting ---

def file_fingerprint(path: Path) -> str:
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


def load_existing_results(output_path: Path) -> tuple[list[dict], set[str], set[str]]:
    """Load ocr_results.json, return (results, source_paths, file_hashes)."""
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
            sp = r.get("source", "")
            fh = r.get("file_hash", "")
            if sp:
                source_paths.add(sp)
            if fh:
                file_hashes.add(fh)
        return existing, source_paths, file_hashes
    except Exception:
        return [], set(), set()


def extract_archive(archive_path: Path, tmp_dir: Path) -> list[Path]:
    """Extract an archive to tmp_dir, return list of image/PDF files found."""
    suffix = archive_path.suffix.lower()

    if suffix == ".zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(tmp_dir)
    elif suffix in {".tar", ".gz", ".bz2", ".xz"}:
        shutil.unpack_archive(str(archive_path), str(tmp_dir))
    elif suffix == ".7z":
        try:
            import py7zr
            with py7zr.SevenZipFile(archive_path, mode="r") as z7:
                z7.extractall(path=tmp_dir)
        except ImportError:
            logger.error(f"[batch] .7z requires py7zr: pip install py7zr")
            return []
    elif suffix == ".rar":
        try:
            import rarfile
            with rarfile.RarFile(archive_path, "r") as rf:
                rf.extractall(tmp_dir)
        except ImportError:
            logger.error(f"[batch] .rar requires rarfile: pip install rarfile")
            return []
    else:
        logger.warning(f"[batch] Unknown archive format: {suffix}")
        return []

    # Collect all image and PDF files from extracted content
    found = []
    for p in sorted(tmp_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in (IMAGE_EXTS | {PDF_EXT}):
            found.append(p)
    return found


def pdf_to_page_images(pdf_path: Path, tmp_dir: Path) -> list[Path]:
    """Convert PDF pages to images, return list of image paths."""
    import fitz
    doc = fitz.open(str(pdf_path))
    images = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        img_path = tmp_dir / f"page_{i + 1:03d}.png"
        pix.save(str(img_path))
        images.append(img_path)
    doc.close()
    return images


def collect_files(input_dir: Path, ext_filter: set[str], include_images: bool) -> list[Path]:
    """Collect files to process from input directory."""
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


async def process_single_image(
    image_path: Path,
    use_layout: bool = True,
) -> dict:
    """OCR a single image, return page result."""
    t0 = time.time()
    try:
        if use_layout:
            text, regions = await ocr_image_with_layout(str(image_path), merge=True)
            return {
                "page": 1,
                "text": text,
                "regions": regions,
                "time": round(time.time() - t0, 2),
            }
        else:
            from PIL import Image
            img = Image.open(str(image_path)).convert("RGB")
            text = await ocr_whole_image(img)
            img.close()
            return {
                "page": 1,
                "text": text,
                "regions": [],
                "time": round(time.time() - t0, 2),
            }
    except Exception as e:
        logger.error(f"[batch] OCR error on {image_path.name}: {e}", exc_info=True)
        return {
            "page": 1,
            "text": "",
            "regions": [],
            "time": round(time.time() - t0, 2),
            "error": str(e),
        }


async def process_document(
    source_path: Path,
    use_layout: bool = True,
) -> dict:
    """Process a single document (archive, PDF, or image)."""
    t0 = time.time()
    file_hash = file_fingerprint(source_path)
    result = {
        "source": str(source_path),
        "file_hash": file_hash,
        "file_size": source_path.stat().st_size,
        "type": "",
        "pages": [],
        "total_time": 0,
        "total_chars": 0,
        "error": None,
    }

    suffix = source_path.suffix.lower()

    # Collect all page images
    page_images: list[Path] = []
    tmp_dir = None

    try:
        if suffix in ARCHIVE_EXTS:
            result["type"] = "archive"
            tmp_dir = Path(tempfile.mkdtemp(prefix="folio_batch_"))
            extracted = extract_archive(source_path, tmp_dir)
            if not extracted:
                result["error"] = f"No images/PDFs found in archive"
                return result

            # Separate images from PDFs
            image_files = [f for f in extracted if f.suffix.lower() in IMAGE_EXTS]
            pdf_files = [f for f in extracted if f.suffix.lower() == PDF_EXT]

            for pdf_f in pdf_files:
                pdf_tmp = Path(tempfile.mkdtemp(prefix="folio_pdf_"))
                page_images.extend(pdf_to_page_images(pdf_f, pdf_tmp))

            # Sort images by natural name order
            image_files.sort(key=lambda p: p.name)
            page_images.extend(image_files)

        elif suffix == PDF_EXT:
            result["type"] = "pdf"
            tmp_dir = Path(tempfile.mkdtemp(prefix="folio_batch_"))
            page_images = pdf_to_page_images(source_path, tmp_dir)

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
            page_result = await process_single_image(img_path, use_layout=use_layout)
            page_result["page"] = i + 1
            page_result["source"] = img_path.name
            result["pages"].append(page_result)

        result["total_chars"] = sum(len(p.get("text", "")) for p in result["pages"])
        result["total_time"] = round(time.time() - t0, 2)

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[batch] Error processing {source_path}: {e}", exc_info=True)
    finally:
        # Cleanup temp directories
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


async def run_batch(
    input_dir: Path,
    output_path: Path,
    ext_filter: set[str],
    include_images: bool,
    use_layout: bool,
    concurrency: int,
    incremental: bool,
):
    """Main batch processing loop."""
    # Initialize httpx client (required by OCR engine)
    import httpx
    from app.ocr import engine as ocr_engine
    ocr_engine.http_client = httpx.AsyncClient(timeout=300.0)

    # Also init the layout model eagerly
    from app.layout.model import get_model
    if use_layout:
        logger.info("[batch] Pre-loading layout model...")
        get_model()

    # Check Ollama
    from app.ocr.engine import check_ollama
    status = await check_ollama()
    if not status["online"]:
        logger.error(f"[batch] Ollama not online at {OLLAMA_BASE}")
        return
    if not status["model_loaded"]:
        logger.error(f"[batch] Model '{OLLAMA_MODEL}' not found. Available: {status['models']}")
        return
    logger.info(f"[batch] Ollama OK, model: {OLLAMA_MODEL}")

    # Collect files
    files = collect_files(input_dir, ext_filter, include_images)
    if not files:
        logger.warning(f"[batch] No files found in {input_dir}")
        return
    logger.info(f"[batch] Found {len(files)} file(s) to process")

    # Load existing results for incremental mode (path + hash dedup)
    existing_sources: set[str] = set()
    existing_hashes: set[str] = set()
    results: list[dict] = []
    if incremental:
        results, existing_sources, existing_hashes = load_existing_results(output_path)
        if existing_sources or existing_hashes:
            logger.info(f"[batch] Incremental: {len(existing_sources)} by path, {len(existing_hashes)} by hash")

    # Filter out already-processed: path match first, then hash match
    skipped_by_path = 0
    skipped_by_hash = 0
    todo: list[Path] = []
    for f in files:
        fstr = str(f)
        if fstr in existing_sources:
            skipped_by_path += 1
            continue
        if incremental and existing_hashes:
            fh = file_fingerprint(f)
            if fh in existing_hashes:
                skipped_by_hash += 1
                continue
        todo.append(f)
    if not todo:
        logger.info("[batch] All files already processed")
    else:
        skipped = skipped_by_path + skipped_by_hash
        parts = []
        if skipped_by_path: parts.append(f"{skipped_by_path} by path")
        if skipped_by_hash: parts.append(f"{skipped_by_hash} by hash")
        skip_msg = f" ({', '.join(parts)} skipped)" if skipped else ""
        logger.info(f"[batch] Processing {len(todo)} file(s){skip_msg}")

    # Process with limited concurrency
    semaphore = asyncio.Semaphore(concurrency)

    async def _process_with_semaphore(f: Path):
        async with semaphore:
            return await process_document(f, use_layout=use_layout)

    t_total = time.time()
    batch_results = await asyncio.gather(*[_process_with_semaphore(f) for f in todo])
    results.extend(batch_results)

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t_total
    total_chars = sum(r.get("total_chars", 0) for r in batch_results)
    errors = sum(1 for r in batch_results if r.get("error"))

    logger.info(
        f"[batch] Done: {len(batch_results)} docs, {total_chars} chars, "
        f"{errors} errors, {elapsed:.1f}s total"
    )
    logger.info(f"[batch] Output: {output_path}")

    # Cleanup
    await ocr_engine.http_client.aclose()


def main():
    parser = argparse.ArgumentParser(
        description="Batch OCR: process local archives/images, output JSON for text search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python batch_ocr.py D:\\scans
  python batch_ocr.py D:\\scans --ext .zip,.7z
  python batch_ocr.py D:\\scans --images -o output.json
  python batch_ocr.py D:\\scans --incremental -j 2
  python batch_ocr.py D:\\scans --no-layout
        """,
    )
    parser.add_argument("input_dir", type=str, help="Directory to scan for files")
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Output JSON path (default: <input_dir>/ocr_results.json)",
    )
    parser.add_argument(
        "--ext", type=str, default=".zip,.rar,.7z,.tar,.gz,.pdf",
        help="Comma-separated file extensions to process (default: .zip,.rar,.7z,.tar,.gz,.pdf)",
    )
    parser.add_argument(
        "--images", action="store_true",
        help="Also process standalone image files (png, jpg, webp, etc.)",
    )
    parser.add_argument(
        "--no-layout", action="store_true",
        help="Skip layout detection (faster, less structured output)",
    )
    parser.add_argument(
        "-j", "--concurrency", type=int, default=4,
        help="Max concurrent OCR tasks (default: 4)",
    )
    parser.add_argument(
        "--incremental", action="store_true",
        help="Skip files already in the output JSON",
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.is_dir():
        print(f"Error: {input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else input_dir / "ocr_results.json"
    ext_filter = {e.strip().lower() for e in args.ext.split(",") if e.strip()}

    # Ensure output dir exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Init DB (needed by OCR engine imports)
    init_db()

    asyncio.run(run_batch(
        input_dir=input_dir,
        output_path=output_path,
        ext_filter=ext_filter,
        include_images=args.images,
        use_layout=not args.no_layout,
        concurrency=args.concurrency,
        incremental=args.incremental,
    ))


if __name__ == "__main__":
    main()
