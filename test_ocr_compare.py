#!/usr/bin/env python3
"""Compare Ollama glm-ocr vs UmiOCR on manga/doujin images from a zip file."""
import time, base64, io, asyncio, httpx, zipfile, sys, os, tempfile
from PIL import Image
import pillow_jxl

# --- Config ---
ZIP_PATH = r"E:\1Hub\EH\1EHV\[NANIMOSHINAI (笹森トモエ)]\1. 同人志\(C82) 白菓 [氷菓] [空気系☆漢化][NANIMOSHINAI (笹森トモエ)].zip"
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "glm-ocr"
OLLAMA_PROMPT = "识别图片中的全部内容，输出Markdown格式。跳过页眉页脚和页码。"
UMI_API = "http://127.0.0.1:1224/api/ocr"

# Max pages to test (0 = all)
MAX_PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 0


def extract_images_from_zip(zip_path: str) -> list[tuple[str, bytes]]:
    """Extract image files from a zip, return (filename, bytes) list sorted by name."""
    images = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in sorted(zf.namelist()):
            lower = name.lower()
            if lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.avif', '.jxl')):
                images.append((name, zf.read(name)))
    return images


MAX_LONG_SIDE = 1280

def resize_for_ocr(img: Image.Image) -> Image.Image:
    """Resize image so longest side <= MAX_LONG_SIDE for stable OCR."""
    w, h = img.size
    long_side = max(w, h)
    if long_side > MAX_LONG_SIDE:
        ratio = MAX_LONG_SIDE / long_side
        nw, nh = int(w * ratio), int(h * ratio)
        img = img.resize((nw, nh), Image.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    return img


async def ollama_ocr(img: Image.Image) -> dict:
    """OCR using Ollama glm-ocr."""
    img = resize_for_ocr(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    b64 = base64.b64encode(png_bytes).decode("utf-8")

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": OLLAMA_PROMPT, "images": [b64]}],
                    "stream": False,
                },
            )
        elapsed = time.time() - t0
        if resp.status_code == 200:
            text = resp.json().get("message", {}).get("content", "")
            return {"success": True, "time": elapsed, "chars": len(text), "text": text}
        else:
            return {"success": False, "time": elapsed, "chars": 0, "text": "", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "time": time.time() - t0, "chars": 0, "text": "", "error": str(e)[:100]}


def umiocr_ocr(img: Image.Image) -> dict:
    """OCR using UmiOCR HTTP API."""
    img = resize_for_ocr(img)
    buf = io.BytesIO()
    if img.mode == "RGBA":
        # UmiOCR handles RGBA, but let's convert to avoid issues
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode == "P":
        img = img.convert("RGB")
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    t0 = time.time()
    try:
        resp = httpx.post(
            UMI_API,
            json={"base64": b64},
            timeout=60,
        )
        elapsed = time.time() - t0
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 100:
                # UmiOCR returns structured data
                results = data.get("data", [])
                # Extract text from each text block
                text_parts = []
                for item in results:
                    if isinstance(item, dict):
                        text_parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        text_parts.append(item)
                text = "\n".join(t for t in text_parts if t.strip())
                return {"success": True, "time": elapsed, "chars": len(text), "text": text}
            else:
                return {"success": False, "time": elapsed, "chars": 0, "text": "", "error": f"UmiOCR code {data.get('code')}: {data.get('data', '')}"}
        else:
            return {"success": False, "time": elapsed, "chars": 0, "text": "", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "time": time.time() - t0, "chars": 0, "text": "", "error": str(e)[:100]}


async def main():
    print(f"ZIP: {ZIP_PATH}")
    if not os.path.exists(ZIP_PATH):
        print(f"File not found: {ZIP_PATH}")
        return

    print(f"Extracting images...")
    images = extract_images_from_zip(ZIP_PATH)
    total = len(images)
    print(f"Found {total} images")

    if MAX_PAGES > 0:
        images = images[:MAX_PAGES]
        print(f"Testing first {MAX_PAGES} pages")

    # Results storage
    ollama_results = []
    umi_results = []

    print(f"\n{'='*80}")
    print(f"{'Page':>4} | {'Filename':>30} | {'Size':>12} | {'Ollama':>12} | {'UmiOCR':>12} | {'OllamaCh':>8} | {'UmiCh':>6}")
    print(f"{'-'*4}-+-{'-'*30}-+-{'-'*12}-+-{'-'*12}-+-{'-'*12}-+-{'-'*8}-+-{'-'*6}")

    for i, (fname, data) in enumerate(images):
        # Load image
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception as e:
            print(f"{i+1:>4} | {os.path.basename(fname)[:30]:>30} | LOAD ERROR: {e}")
            continue

        size_str = f"{img.size[0]}x{img.size[1]}"
        basename = os.path.basename(fname)[:30]

        # Run both OCR
        ollama_r = await ollama_ocr(img.copy())
        umi_r = umiocr_ocr(img.copy())

        ollama_results.append(ollama_r)
        umi_results.append(umi_r)

        o_str = f"{ollama_r['time']:.1f}s" if ollama_r['success'] else f"FAIL({ollama_r.get('error','')[:8]})"
        u_str = f"{umi_r['time']:.1f}s" if umi_r['success'] else f"FAIL({umi_r.get('error','')[:8]})"
        o_chars = str(ollama_r['chars']) if ollama_r['success'] else "-"
        u_chars = str(umi_r['chars']) if umi_r['success'] else "-"

        print(f"{i+1:>4} | {basename:>30} | {size_str:>12} | {o_str:>12} | {u_str:>12} | {o_chars:>8} | {u_chars:>6}")

        # Show text comparison for selected pages
        SHOW_PAGES = {0, 4, 8, 11, 17, 20, 23}  # 0-indexed
        if i in SHOW_PAGES:
            print(f"\n--- Page {i+1} Ollama ({ollama_r['chars']} chars) ---")
            print(ollama_r.get('text', '')[:600])
            print(f"\n--- Page {i+1} UmiOCR ({umi_r['chars']} chars) ---")
            print(umi_r.get('text', '')[:600])
            print()

    # Summary
    ollama_ok = [r for r in ollama_results if r['success']]
    umi_ok = [r for r in umi_results if r['success']]

    print(f"\n{'='*80}")
    print(f"SUMMARY ({len(images)} pages)")
    print(f"{'='*80}")

    if ollama_ok:
        o_times = [r['time'] for r in ollama_ok]
        o_chars = [r['chars'] for r in ollama_ok]
        print(f"Ollama glm-ocr: {len(ollama_ok)}/{len(images)} success")
        print(f"  Time: avg={sum(o_times)/len(o_times):.2f}s, min={min(o_times):.2f}s, max={max(o_times):.2f}s")
        print(f"  Total time: {sum(o_times):.1f}s")
        print(f"  Chars: avg={sum(o_chars)/len(o_chars):.0f}, total={sum(o_chars)}")

    if umi_ok:
        u_times = [r['time'] for r in umi_ok]
        u_chars = [r['chars'] for r in umi_ok]
        print(f"UmiOCR: {len(umi_ok)}/{len(images)} success")
        print(f"  Time: avg={sum(u_times)/len(u_times):.2f}s, min={min(u_times):.2f}s, max={max(u_times):.2f}s")
        print(f"  Total time: {sum(u_times):.1f}s")
        print(f"  Chars: avg={sum(u_chars)/len(u_chars):.0f}, total={sum(u_chars)}")

    if ollama_ok and umi_ok:
        o_avg = sum(r['time'] for r in ollama_ok) / len(ollama_ok)
        u_avg = sum(r['time'] for r in umi_ok) / len(umi_ok)
        faster = "UmiOCR" if u_avg < o_avg else "Ollama"
        ratio = max(o_avg, u_avg) / min(o_avg, u_avg)
        print(f"\nSpeed winner: {faster} ({ratio:.1f}x faster)")


if __name__ == "__main__":
    asyncio.run(main())
