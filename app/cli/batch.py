# -*- coding: utf-8 -*-
"""
Folio-OCR CLI — batch subcommand with rich live progress.

Interactive path input + real-time per-page text output + retry.
"""
import asyncio
import json
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn,
    TimeElapsedColumn, TimeRemainingColumn,
)
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from ..config import logger, OLLAMA_BASE, OLLAMA_MODEL, BATCH_CONFIG
from ..database import init_db
from ..ocr.engine import ocr_image_with_layout, ocr_whole_image
from ..layout import detect_layout

# Force UTF-8 on Windows to avoid GBK encoding errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console(force_terminal=True)

# --- Constants ---
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".avif", ".jxl"}
PDF_EXT = ".pdf"

# --- Retry helper ---

async def _ocr_with_retry(coro_fn, *args, max_retries: int = 3, base_delay: float = 2.0, **kwargs):
    """Call an async OCR function with retry on 5xx / connection errors."""
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            err_str = str(e)
            # Only retry on 5xx / connection errors
            is_retryable = "500" in err_str or "502" in err_str or "503" in err_str or "ConnectError" in err_str or "ConnectionReset" in err_str
            if not is_retryable or attempt == max_retries:
                raise
            delay = base_delay * attempt
            logger.warning(f"[batch] Retry {attempt}/{max_retries} after error: {err_str[:80]}... (wait {delay:.0f}s)")
            await asyncio.sleep(delay)


# --- Fingerprinting ---

def file_fingerprint(path: Path) -> str:
    import hashlib
    h = hashlib.md5()
    try:
        st = path.stat()
        h.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
        with open(path, "rb") as f:
            h.update(f.read(1 << 20))
    except OSError:
        h.update(str(path).encode())
    return h.hexdigest()


def load_existing_results(output_path: Path) -> tuple[list[dict], set[str], set[str]]:
    if not output_path.exists():
        return [], set(), set()
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            return [], set(), set()
        source_paths, file_hashes = set(), set()
        for r in existing:
            sp = r.get("source", "")
            fh = r.get("file_hash", "")
            if sp: source_paths.add(sp)
            if fh: file_hashes.add(fh)
        return existing, source_paths, file_hashes
    except Exception:
        return [], set(), set()


# --- Archive / PDF helpers ---

def extract_archive(archive_path: Path, tmp_dir: Path) -> list[Path]:
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
        logger.warning(f"Extract failed: {e}")
        return []

    found = []
    for p in sorted(tmp_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in (IMAGE_EXTS | {PDF_EXT}):
            found.append(p)
    return found


def pdf_to_page_images(pdf_path: Path, tmp_dir: Path) -> list[Path]:
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


def _dir_cache_key(ext_filter: set[str], include_images: bool, blacklist: list[str]) -> str:
    """Build a cache key from scan parameters."""
    import hashlib
    h = hashlib.md5()
    h.update(",".join(sorted(ext_filter)).encode())
    h.update(str(include_images).encode())
    h.update(",".join(sorted(blacklist)).encode())
    return h.hexdigest()


def _try_dir_cache(input_dir: Path, ext_filter: set[str], include_images: bool,
                    blacklist: list[str]) -> tuple[list[Path], int] | None:
    """Try to load cached file listing from DB. Returns None if cache miss."""
    from ..database import get_db
    try:
        st = input_dir.stat()
    except OSError:
        return None
    bl_key = _dir_cache_key(ext_filter, include_images, blacklist)
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT files_json, skipped_count, dir_mtime FROM dir_cache WHERE dir_path = ? AND blacklist_key = ?",
                (str(input_dir), bl_key),
            ).fetchone()
            if not row:
                return None
            # Check directory mtime (quick stat of top-level dir)
            if abs(row["dir_mtime"] - st.st_mtime) > 1.0:
                return None
            # Spot-check a few cached files still exist
            import json
            cached_paths = json.loads(row["files_json"])
            if not cached_paths:
                return None
            # Check up to 5 random files
            import random
            sample = random.sample(cached_paths, min(5, len(cached_paths)))
            for p_str in sample:
                if not Path(p_str).exists():
                    return None
            return [Path(p) for p in cached_paths], row["skipped_count"]
    except Exception:
        return None


def _save_dir_cache(input_dir: Path, ext_filter: set[str], include_images: bool,
                    blacklist: list[str], files: list[Path], skipped: int):
    """Save file listing cache to DB."""
    from ..database import get_db
    import json
    from datetime import datetime
    try:
        st = input_dir.stat()
        bl_key = _dir_cache_key(ext_filter, include_images, blacklist)
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO dir_cache
                   (dir_path, dir_mtime, ext_filter, include_images, blacklist_key, files_json, skipped_count, scanned_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(input_dir),
                    st.st_mtime,
                    ",".join(sorted(ext_filter)),
                    int(include_images),
                    bl_key,
                    json.dumps([str(f) for f in files], ensure_ascii=False),
                    skipped,
                    datetime.now().isoformat(),
                ),
            )
    except Exception as e:
        logger.debug(f"Failed to save dir cache: {e}")


def collect_files(input_dir: Path, ext_filter: set[str], include_images: bool,
                  blacklist: list[str] | None = None, rescan: bool = False) -> tuple[list[Path], int, bool]:
    """Collect files matching ext_filter, skipping folders with blacklisted names.
    Returns (matched_files, skipped_by_blacklist_count, from_cache).
    Uses DB cache to avoid repeated directory scans.
    """
    bl = blacklist or BATCH_CONFIG.get("blacklist", [])

    # Try cache first (unless --rescan)
    if not rescan:
        cached = _try_dir_cache(input_dir, ext_filter, include_images, bl)
        if cached is not None:
            return cached[0], cached[1], True

    files = []
    skipped = 0
    for p in sorted(input_dir.rglob("*")):
        if not p.is_file():
            continue
        # Skip if any parent folder name contains a blacklisted keyword
        if bl and any(kw in part for part in p.relative_to(input_dir).parts for kw in bl):
            skipped += 1
            continue
        suffix = p.suffix.lower()
        if suffix in ext_filter:
            files.append(p)
        elif include_images and suffix in IMAGE_EXTS:
            files.append(p)

    # Save to cache
    _save_dir_cache(input_dir, ext_filter, include_images, bl, files, skipped)
    return files, skipped, False


# --- OCR processing (page-by-page generator) ---

async def process_document_pages(source_path: Path, use_layout: bool = True):
    """Yield (event_type, data) for each page processed.
    
    Events:
      ("page", {page_num, source, text, regions, time, error})
      ("done", {source, file_hash, file_size, type, total_chars, total_time, error, pages})
    """
    t0 = time.time()
    file_hash = file_fingerprint(source_path)
    suffix = source_path.suffix.lower()
    page_images: list[Path] = []
    tmp_dirs: list[Path] = []
    doc_type = ""
    doc_error = None

    try:
        if suffix in ARCHIVE_EXTS:
            doc_type = "archive"
            tmp = Path(tempfile.mkdtemp(prefix="folio_batch_"))
            tmp_dirs.append(tmp)
            extracted = extract_archive(source_path, tmp)
            if not extracted:
                doc_error = "No images/PDFs found in archive"
                yield ("done", {"source": str(source_path), "file_hash": file_hash,
                                "file_size": source_path.stat().st_size, "type": doc_type,
                                "total_chars": 0, "total_time": round(time.time() - t0, 2),
                                "error": doc_error, "pages": []})
                return
            image_files = sorted([f for f in extracted if f.suffix.lower() in IMAGE_EXTS], key=lambda p: p.name)
            pdf_files = [f for f in extracted if f.suffix.lower() == PDF_EXT]
            for pdf_f in pdf_files:
                pdf_tmp = Path(tempfile.mkdtemp(prefix="folio_pdf_"))
                tmp_dirs.append(pdf_tmp)
                page_images.extend(pdf_to_page_images(pdf_f, pdf_tmp))
            page_images.extend(image_files)

        elif suffix == PDF_EXT:
            doc_type = "pdf"
            tmp = Path(tempfile.mkdtemp(prefix="folio_batch_"))
            tmp_dirs.append(tmp)
            page_images = pdf_to_page_images(source_path, tmp)

        elif suffix in IMAGE_EXTS:
            doc_type = "image"
            page_images = [source_path]
        else:
            doc_error = f"Unsupported: {suffix}"
            yield ("done", {"source": str(source_path), "file_hash": file_hash,
                            "file_size": source_path.stat().st_size, "type": doc_type,
                            "total_chars": 0, "total_time": round(time.time() - t0, 2),
                            "error": doc_error, "pages": []})
            return

        if not page_images:
            doc_error = "No page images found"
            yield ("done", {"source": str(source_path), "file_hash": file_hash,
                            "file_size": source_path.stat().st_size, "type": doc_type,
                            "total_chars": 0, "total_time": round(time.time() - t0, 2),
                            "error": doc_error, "pages": []})
            return

        pages = []
        for i, img_path in enumerate(page_images):
            t1 = time.time()
            page_data = {"page": i + 1, "source": img_path.name, "text": "", "regions": [], "time": 0, "error": None}
            try:
                if use_layout:
                    text, regions = await _ocr_with_retry(ocr_image_with_layout, str(img_path), merge=True)
                else:
                    from PIL import Image as PILImage
                    img = PILImage.open(str(img_path)).convert("RGB")
                    text = await _ocr_with_retry(ocr_whole_image, img)
                    img.close()
                    regions = []
                page_data["text"] = text
                page_data["regions"] = regions if use_layout else []
                page_data["time"] = round(time.time() - t1, 2)
            except Exception as e:
                page_data["error"] = str(e)
                logger.warning(f"[batch] Page {i+1} error: {e}")

            pages.append(page_data)
            yield ("page", page_data)

        total_chars = sum(len(p.get("text", "")) for p in pages)
        yield ("done", {"source": str(source_path), "file_hash": file_hash,
                        "file_size": source_path.stat().st_size, "type": doc_type,
                        "total_chars": total_chars, "total_time": round(time.time() - t0, 2),
                        "error": None, "pages": pages})

    except Exception as e:
        yield ("done", {"source": str(source_path), "file_hash": file_hash,
                        "file_size": source_path.stat().st_size, "type": doc_type,
                        "total_chars": 0, "total_time": round(time.time() - t0, 2),
                        "error": str(e), "pages": []})
    finally:
        for td in tmp_dirs:
            if td.exists():
                shutil.rmtree(td, ignore_errors=True)


# --- File preview table ---

def show_file_preview(input_dir: Path, ext_filter: set[str], include_images: bool,
                      existing_sources: set[str], existing_hashes: set[str],
                      blacklist: list[str] | None = None, rescan: bool = False) -> list[Path]:
    """Show a rich table of files to be processed, return the todo list."""
    all_files, skipped, from_cache = collect_files(input_dir, ext_filter, include_images, blacklist=blacklist, rescan=rescan)
    if from_cache:
        console.print(f"[dim]📂 Using cached file listing[/]")
    if not all_files:
        if skipped:
            console.print(f"[yellow]No matching files found.[/] [dim]({skipped} skipped by blacklist)[/]")
        else:
            console.print("[yellow]No matching files found.[/]")
        return []

    # Determine which are already processed
    todo, done = [], []
    for f in all_files:
        fstr = str(f)
        if fstr in existing_sources:
            done.append((f, "path"))
        elif existing_hashes and file_fingerprint(f) in existing_hashes:
            done.append((f, "hash"))
        else:
            todo.append(f)

    table = Table(title=f"[bold]{input_dir}[/]", show_header=True, header_style="bold cyan", pad_edge=False)
    table.add_column("", width=3)
    table.add_column("Type", width=8, style="dim")
    table.add_column("Size", justify="right", width=9)
    table.add_column("Name", overflow="fold")

    for f, method in done:
        size_mb = round(f.stat().st_size / 1024 / 1024, 1)
        size_str = f"{size_mb} MB" if size_mb >= 1 else f"{round(f.stat().st_size / 1024)} KB"
        ftype = "archive" if f.suffix.lower() in ARCHIVE_EXTS else "pdf" if f.suffix.lower() == PDF_EXT else "image"
        table.add_row("[green]✓[/]", ftype, size_str, f"[dim]{f.name}[/]")

    for f in todo:
        size_mb = round(f.stat().st_size / 1024 / 1024, 1)
        size_str = f"{size_mb} MB" if size_mb >= 1 else f"{round(f.stat().st_size / 1024)} KB"
        ftype = "archive" if f.suffix.lower() in ARCHIVE_EXTS else "pdf" if f.suffix.lower() == PDF_EXT else "image"
        table.add_row("[cyan]○[/]", ftype, size_str, f.name)

    console.print(table)
    if done:
        console.print(f"  [green]✓ {len(done)} already processed[/]  [cyan]○ {len(todo)} pending[/]")
    if skipped:
        console.print(f"  [dim]✗ {skipped} skipped by blacklist[/]")
    return todo


# --- Text display helper ---

def _truncate_text(text: str, max_len: int = 120) -> str:
    """Truncate text for display, collapsing whitespace."""
    text = text.strip().replace("\n", " ")
    # Collapse multiple spaces
    import re
    text = re.sub(r"  +", " ", text)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


# --- Main batch command ---

async def _run_batch(
    todo: list[Path],
    output_path: Path,
    use_layout: bool,
    concurrency: int,
    existing_results: list[dict],
):
    """Core batch processing with Rich live progress + per-page text output."""
    import httpx
    from app.ocr import engine as ocr_engine
    ocr_engine.http_client = httpx.AsyncClient(timeout=300.0)

    # Pre-load layout model (only when enabled)
    if use_layout:
        with console.status("[bold cyan]Loading layout model...[/]"):
            from app.layout.model import ensure_model
            ensure_model()
        console.print("[green]✓ Layout model loaded[/]")
    else:
        console.print("[dim]Layout detection: OFF (faster mode)[/]")

    # Check Ollama
    from app.ocr.engine import check_ollama
    status = await check_ollama()
    if not status["online"]:
        console.print(f"[red]✗ Ollama not online at {OLLAMA_BASE}[/]")
        await ocr_engine.http_client.aclose()
        return False
    if not status["model_loaded"]:
        console.print(f"[red]✗ Model '{OLLAMA_MODEL}' not found. Available: {status['models']}[/]")
        await ocr_engine.http_client.aclose()
        return False
    console.print(f"[green]✓ Ollama ready, model: {OLLAMA_MODEL}[/]")

    # --- Rich layout: progress bar on top, text log below ---
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        TimeElapsedColumn(),
        TextColumn("~"),
        TimeRemainingColumn(),
        console=console,
    )
    task_id = progress.add_task("OCR", total=len(todo))

    results = list(existing_results)
    total_chars = 0
    total_errors = 0
    semaphore = asyncio.Semaphore(concurrency)

    # Text log lines (shown below progress bar)
    text_lines: list[str] = []

    def _build_display() -> Panel:
        """Build the full live display: progress + recent text."""
        # Show last 8 text lines
        recent = text_lines[-8:] if text_lines else []
        body = progress.get_renderable()
        if recent:
            lines_text = "\n".join(recent)
            from rich.columns import Columns
            from rich.console import Group
            group = Group(body, Text(""), Text(lines_text))
            return Panel(group, title="[bold]Batch OCR[/]", border_style="cyan", height=18)
        return Panel(body, title="[bold]Batch OCR[/]", border_style="cyan")

    async def _process_one(f: Path):
        nonlocal total_chars, total_errors
        async with semaphore:
            progress.update(task_id, description=str(f))
            result_dict = None
            async for event_type, data in process_document_pages(f, use_layout=use_layout):
                if event_type == "page":
                    pg = data
                    pg_num = pg.get("page", "?")
                    pg_src = pg.get("source", "?")
                    pg_text = pg.get("text", "")
                    pg_err = pg.get("error")
                    chars = len(pg_text)
                    if pg_err:
                        line = f"  [dim]p{pg_num}[/] [red]✗ {pg_err[:50]}[/]"
                    elif chars == 0:
                        line = f"  [dim]p{pg_num} {pg_src} — (empty)[/]"
                    else:
                        preview = _truncate_text(pg_text, 100)
                        line = f"  [dim]p{pg_num}[/] [green]{chars}c[/] {preview}"
                    text_lines.append(line)
                elif event_type == "done":
                    result_dict = data
            # Finalize
            if result_dict is None:
                result_dict = {"source": str(f), "error": "no result", "pages": [], "total_chars": 0}

            results.append(result_dict)
            if result_dict.get("error"):
                total_errors += 1
                progress.update(task_id, advance=1, description=f"[red]✗[/] {f}")
            else:
                chars = result_dict.get("total_chars", 0)
                total_chars += chars
                progress.update(task_id, advance=1, description=f"[green]✓[/] {f} [{chars:,}c]")

            # Intermediate save
            try:
                with open(output_path, "w", encoding="utf-8") as fp:
                    json.dump(results, fp, ensure_ascii=False, indent=2)
            except Exception:
                pass

    with Live(_build_display(), console=console, refresh_per_second=4) as live:
        async def _run_and_update(f: Path):
            await _process_one(f)
            live.update(_build_display())

        await asyncio.gather(*[_run_and_update(f) for f in todo])

    # Final save
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=2)

    # Summary
    summary = Table(title="Results", show_header=False, pad_edge=False, show_lines=False)
    summary.add_column("K", style="dim", width=18)
    summary.add_column("V", justify="right")
    summary.add_row("Files processed", str(len(todo)))
    summary.add_row("Total characters", f"{total_chars:,}")
    summary.add_row("Errors", str(total_errors) if total_errors == 0 else f"[red]{total_errors}[/red]")
    summary.add_row("Output", str(output_path))
    console.print(summary)

    await ocr_engine.http_client.aclose()
    return True


def run_batch_cmd(
    path: Optional[str],
    output: Optional[str],
    ext: str,
    images: bool,
    no_layout: bool,
    concurrency: int,
    incremental: bool,
    blacklist: Optional[list[str]] = None,
    yes: bool = False,
    rescan: bool = False,
):
    """Typer callback for `folio batch`."""
    # Init DB
    init_db()

    # Merge blacklist from CLI args and config
    bl = blacklist if blacklist is not None else BATCH_CONFIG.get("blacklist", [])
    if bl:
        console.print(f"[dim]Blacklist keywords: {', '.join(bl)}[/]")

    # Interactive path prompt if not provided
    if not path:
        console.print(Panel(
            "[bold cyan]Folio-OCR Batch Processor[/]\n\n"
            "Enter the directory path to scan.\n"
            "Supports: [green].zip .rar .7z .tar .gz .pdf[/] and images",
            border_style="cyan",
        ))
        while True:
            raw = Prompt.ask("[bold]📁 Directory path[/]", console=console)
            raw = raw.strip()
            if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
                raw = raw[1:-1].strip()
            p = Path(raw).resolve()
            if not p.exists():
                console.print(f"[red]✗ Path does not exist: {p}[/]")
                continue
            if not p.is_dir():
                console.print(f"[red]✗ Not a directory: {p}[/]")
                continue
            input_dir = p
            break
    else:
        # Strip quotes from argument too
        p_str = path.strip()
        if (p_str.startswith('"') and p_str.endswith('"')) or (p_str.startswith("'") and p_str.endswith("'")):
            p_str = p_str[1:-1].strip()
        input_dir = Path(p_str).resolve()
    if not input_dir.is_dir():
        console.print(f"[red]✗ Not a directory: {input_dir}[/]")
        raise SystemExit(1)

    ext_filter = {e.strip().lower() for e in ext.split(",") if e.strip()}
    output_path = Path(output) if output else input_dir / "ocr_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing results
    existing_results, existing_sources, existing_hashes = [], set(), set()
    if incremental:
        existing_results, existing_sources, existing_hashes = load_existing_results(output_path)

    # Show file preview
    todo = show_file_preview(input_dir, ext_filter, images, existing_sources, existing_hashes,
                             blacklist=bl, rescan=rescan)
    if not todo:
        console.print("[green]All files already processed ✓[/]")
        return

    # Confirm
    console.print(f"\n[bold]Will process {len(todo)} file(s)[/]  →  [dim]{output_path}[/]")
    if not yes:
        from rich.prompt import Confirm
        if not Confirm.ask("Proceed?", default=True):
            console.print("[dim]Cancelled.[/]")
            return

    # Run
    asyncio.run(_run_batch(
        todo=todo,
        output_path=output_path,
        use_layout=not no_layout,
        concurrency=concurrency,
        existing_results=existing_results,
    ))
