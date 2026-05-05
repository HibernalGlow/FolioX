#!/usr/bin/env python3
"""Quick speed test: F16 vs Q8_0 + PNG vs JPEG encoding."""
import time, base64, io, asyncio, httpx, zipfile, os
from PIL import Image
import pillow_jxl

ZIP_PATH = r"E:\1Hub\EH\1EHV\[NANIMOSHINAI (笹森トモエ)]\1. 同人志\(C82) 白菓 [氷菓] [空気系☆漢化][NANIMOSHINAI (笹森トモエ)].zip"
OLLAMA_BASE = "http://localhost:11434"
OCR_PROMPT = "识别图片中的全部内容，输出Markdown格式。跳过页眉页脚和页码。"
MAX_LONG_SIDE = 1280

# Test configs
CONFIGS = [
    ("F16+PNG",  "glm-ocr",        "PNG",  None),
    ("F16+JPEG", "glm-ocr",        "JPEG", 85),
    ("Q8+PNG",   "glm-ocr:q8_0",   "PNG",  None),
    ("Q8+JPEG",  "glm-ocr:q8_0",   "JPEG", 85),
]

# Test first N pages
TEST_PAGES = 5


def extract_images(zip_path: str, n: int):
    images = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in sorted(zf.namelist()):
            if name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.avif', '.jxl')):
                images.append((name, zf.read(name)))
                if len(images) >= n:
                    break
    return images


def prepare_image(data: bytes, fmt: str, quality: int | None) -> tuple[str, int]:
    """Resize + encode, return (base64_str, encoded_bytes)."""
    img = Image.open(io.BytesIO(data))
    img.load()
    # Resize
    w, h = img.size
    long_side = max(w, h)
    if long_side > MAX_LONG_SIDE:
        ratio = MAX_LONG_SIDE / long_side
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    # Encode
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.save(buf, format="JPEG", quality=quality or 85)
    else:
        img.save(buf, format="PNG")
    encoded = buf.getvalue()
    return base64.b64encode(encoded).decode("utf-8"), len(encoded)


async def ocr_one(client: httpx.AsyncClient, model: str, b64: str) -> dict:
    t0 = time.time()
    resp = await client.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": OCR_PROMPT, "images": [b64]}],
            "stream": False,
        },
    )
    elapsed = time.time() - t0
    if resp.status_code == 200:
        text = resp.json().get("message", {}).get("content", "")
        return {"ok": True, "time": elapsed, "chars": len(text), "text": text}
    return {"ok": False, "time": elapsed, "chars": 0, "text": "", "error": resp.status_code}


async def main():
    print(f"ZIP: {ZIP_PATH}")
    images = extract_images(ZIP_PATH, TEST_PAGES)
    print(f"Testing {len(images)} pages x {len(CONFIGS)} configs\n")

    async with httpx.AsyncClient(timeout=120) as client:
        for config_name, model, fmt, quality in CONFIGS:
            print(f"--- {config_name} (model={model}, fmt={fmt}) ---")
            times = []
            total_chars = 0
            sample_text = ""

            for i, (fname, data) in enumerate(images):
                b64, enc_size = prepare_image(data, fmt, quality)
                r = await ocr_one(client, model, b64)
                if r["ok"]:
                    times.append(r["time"])
                    total_chars += r["chars"]
                    if i == 0:
                        sample_text = r["text"][:300]
                    print(f"  P{i+1}: {r['time']:.2f}s, {r['chars']}chars, img={enc_size//1024}KB")
                else:
                    print(f"  P{i+1}: FAIL ({r.get('error', '')})")

            if times:
                avg = sum(times) / len(times)
                print(f"  => avg={avg:.2f}s, total={sum(times):.1f}s, chars={total_chars}")
                if sample_text:
                    print(f"  => Sample: {sample_text[:150]}")
            print()

if __name__ == "__main__":
    asyncio.run(main())
