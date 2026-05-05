# -*- coding: utf-8 -*-
"""Folio-OCR CLI — single file OCR subcommand."""
import asyncio
import json
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from ..database import init_db

console = Console()


async def _ocr_single(file_path: Path, use_layout: bool) -> dict:
    """OCR a single file, return result dict."""
    import httpx
    from app.ocr import engine as ocr_engine
    ocr_engine.http_client = httpx.AsyncClient(timeout=300.0)

    suffix = file_path.suffix.lower()
    page_images = []
    tmp_dirs = []

    try:
        # Single image
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".avif", ".jxl"}:
            page_images = [file_path]
        # PDF
        elif suffix == ".pdf":
            import fitz
            import tempfile
            tmp = Path(tempfile.mkdtemp(prefix="folio_ocr_"))
            tmp_dirs.append(tmp)
            doc = fitz.open(str(file_path))
            for i, page in enumerate(doc):
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                img_path = tmp / f"page_{i + 1:03d}.png"
                pix.save(str(img_path))
                page_images.append(img_path)
            doc.close()
        else:
            console.print(f"[red]✗ Unsupported file type: {suffix}[/]")
            return None

        # Pre-load layout model
        if use_layout:
            with console.status("[bold cyan]Loading layout model...[/]"):
                from app.layout.model import get_model
                get_model()

        # Check Ollama
        from app.ocr.engine import check_ollama, OLLAMA_BASE, OLLAMA_MODEL
        status = await check_ollama()
        if not status["online"]:
            console.print(f"[red]✗ Ollama not online at {OLLAMA_BASE}[/]")
            return None
        if not status["model_loaded"]:
            console.print(f"[red]✗ Model '{OLLAMA_MODEL}' not found[/]")
            return None

        # OCR each page
        all_text = []
        all_pages = []
        for i, img_path in enumerate(page_images):
            with console.status(f"[bold cyan]OCR page {i + 1}/{len(page_images)}...[/]"):
                t0 = time.time()
                if use_layout:
                    from app.ocr.engine import ocr_image_with_layout
                    text, regions = await ocr_image_with_layout(str(img_path), merge=True)
                else:
                    from app.ocr.engine import ocr_whole_image
                    from PIL import Image
                    img = Image.open(str(img_path)).convert("RGB")
                    text = await ocr_whole_image(img)
                    img.close()
                    regions = []
                elapsed = round(time.time() - t0, 2)
                all_text.append(text)
                all_pages.append({"page": i + 1, "text": text, "regions": regions, "time": elapsed})

        return {"pages": all_pages, "total_chars": sum(len(t) for t in all_text), "total_time": sum(p["time"] for p in all_pages)}

    finally:
        import shutil
        for td in tmp_dirs:
            if td.exists():
                shutil.rmtree(td, ignore_errors=True)
        await ocr_engine.http_client.aclose()


def run_ocr_cmd(file: str, layout: bool, output: str, format: str):
    """OCR a single file and display/save the result."""
    init_db()

    file_path = Path(file).resolve()
    if not file_path.exists():
        console.print(f"[red]✗ File not found: {file_path}[/]")
        raise SystemExit(1)

    console.print(Panel(f"[bold cyan]OCR[/]  {file_path.name}", border_style="cyan"))

    result = asyncio.run(_ocr_single(file_path, use_layout=layout))
    if not result:
        raise SystemExit(1)

    # Output
    if format == "json":
        out = json.dumps(result, ensure_ascii=False, indent=2)
        if output:
            Path(output).write_text(out, encoding="utf-8")
            console.print(f"[green]✓ Saved to {output}[/]")
        else:
            console.print(Syntax(out, "json", theme="monokai"))
    elif format == "md":
        md_lines = []
        for p in result["pages"]:
            md_lines.append(f"## Page {p['page']}\n\n{p['text']}\n")
        out = "\n".join(md_lines)
        if output:
            Path(output).write_text(out, encoding="utf-8")
            console.print(f"[green]✓ Saved to {output}[/]")
        else:
            console.print(out)
    else:  # text
        out = "\n\n".join(p["text"] for p in result["pages"])
        if output:
            Path(output).write_text(out, encoding="utf-8")
            console.print(f"[green]✓ Saved to {output}[/]")
        else:
            console.print(out)

    # Stats
    console.print(f"[dim]{result['total_chars']} chars, {result['total_time']}s[/]")
