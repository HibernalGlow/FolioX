#!/usr/bin/env python3
"""Test: 1) WebP/AVIF native format support  2) Multi-image batch OCR"""
import time, base64, io, asyncio, httpx, zipfile, os
from PIL import Image
import pillow_jxl

ZIP_PATH = r"E:\1Hub\EH\1EHV\[NANIMOSHINAI (笹森トモエ)]\1. 同人志\(C82) 白菓 [氷菓] [空気系☆漢化][NANIMOSHINAI (笹森トモエ)].zip"
OLLAMA_BASE = "http://localhost:11434"
OCR_PROMPT = "识别图片中的全部内容，输出Markdown格式。跳过页眉页脚和页码。"
MAX_LONG_SIDE = 1280
MODEL = "glm-ocr"


def extract_images(zip_path: str, n: int):
    """Extract first n images from zip."""
    images = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in sorted(zf.namelist()):
            if name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.avif', '.jxl')):
                images.append((name, zf.read(name)))
                if len(images) >= n:
                    break
    return images


def resize_img(img: Image.Image) -> Image.Image:
    w, h = img.size
    if max(w, h) > MAX_LONG_SIDE:
        ratio = MAX_LONG_SIDE / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def encode_as(img: Image.Image, fmt: str, quality: int = 85) -> bytes:
    """Encode PIL Image to specified format bytes."""
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.save(buf, format="JPEG", quality=quality)
    elif fmt == "PNG":
        img.save(buf, format="PNG")
    elif fmt == "WEBP":
        img.save(buf, format="WEBP", quality=quality)
    elif fmt == "AVIF":
        # pillow-avif-plugin or pillow with avif support
        try:
            img.save(buf, format="AVIF", quality=quality)
        except Exception as e:
            print(f"  [WARN] AVIF encode failed: {e}")
            return None
    else:
        raise ValueError(f"Unknown format: {fmt}")
    return buf.getvalue()


async def ocr_images(client: httpx.AsyncClient, model: str, b64_list: list[str]) -> dict:
    """Send one or more images to Ollama for OCR."""
    t0 = time.time()
    resp = await client.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": OCR_PROMPT, "images": b64_list}],
            "stream": False,
        },
    )
    elapsed = time.time() - t0
    if resp.status_code == 200:
        text = resp.json().get("message", {}).get("content", "")
        return {"ok": True, "time": elapsed, "chars": len(text), "text": text}
    return {"ok": False, "time": elapsed, "chars": 0, "text": "", "error": resp.status_code}


async def test_format_support(client: httpx.AsyncClient):
    """Test 1: Does glm-ocr natively handle WebP/AVIF without PIL conversion?"""
    print("=" * 60)
    print("测试1: WebP / AVIF 原生格式支持")
    print("=" * 60)

    images = extract_images(ZIP_PATH, 1)
    if not images:
        print("No images found!")
        return

    fname, data = images[0]
    img = Image.open(io.BytesIO(data))
    img.load()
    img = resize_img(img)

    formats = [
        ("JPEG", 85),
        ("PNG", None),
        ("WEBP", 85),
        ("AVIF", 85),
    ]

    # Also test: send raw original file bytes (no PIL re-encode)
    results = []

    for fmt, quality in formats:
        print(f"\n--- {fmt} (quality={quality}) ---")
        encoded = encode_as(img, fmt, quality)
        if encoded is None:
            print("  SKIP (encode failed)")
            continue

        b64 = base64.b64encode(encoded).decode("utf-8")
        print(f"  Size: {len(encoded)//1024}KB, base64: {len(b64)//1024}KB")

        r = await ocr_images(client, MODEL, [b64])
        if r["ok"]:
            print(f"  OK: {r['time']:.2f}s, {r['chars']} chars")
            print(f"  Preview: {r['text'][:200]}")
            results.append((fmt, r["time"], r["chars"], len(encoded)))
        else:
            print(f"  FAIL: {r.get('error', '')}, {r['time']:.2f}s")
            results.append((fmt, r["time"], 0, len(encoded)))

    # Also test: send the raw original bytes directly (no PIL re-encoding)
    print(f"\n--- Raw original (no PIL re-encode) ---")
    raw_b64 = base64.b64encode(data).decode("utf-8")
    print(f"  Size: {len(data)//1024}KB, base64: {len(raw_b64)//1024}KB, ext: {os.path.splitext(fname)[1]}")
    r = await ocr_images(client, MODEL, [raw_b64])
    if r["ok"]:
        print(f"  OK: {r['time']:.2f}s, {r['chars']} chars")
        print(f"  Preview: {r['text'][:200]}")
        results.append(("Raw", r["time"], r["chars"], len(data)))
    else:
        print(f"  FAIL: {r.get('error', '')}, {r['time']:.2f}s")
        results.append(("Raw", r["time"], 0, len(data)))

    print(f"\n--- 格式对比汇总 ---")
    print(f"  {'格式':<6} {'体积':>8} {'耗时':>8} {'字数':>6}")
    for fmt, t, chars, size in results:
        print(f"  {fmt:<6} {size//1024:>6}KB {t:>6.2f}s {chars:>6}")


async def test_batch_ocr(client: httpx.AsyncClient):
    """Test 2: Multi-image batch OCR (send N images in one request)."""
    print("\n" + "=" * 60)
    print("测试2: 多图批量 OCR (单次请求包含多张图)")
    print("=" * 60)

    n_pages = 5
    images = extract_images(ZIP_PATH, n_pages)
    if not images:
        print("No images found!")
        return

    # Prepare all images as JPEG b64
    b64_list = []
    for fname, data in images:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = resize_img(img)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64_list.append(base64.b64encode(buf.getvalue()).decode("utf-8"))

    # Strategy A: One-by-one (sequential)
    print(f"\n--- 方式A: 逐页顺序 ({n_pages}张 x 1图/请求) ---")
    t0 = time.time()
    total_chars_seq = 0
    seq_texts = []
    for i, b64 in enumerate(b64_list):
        r = await ocr_images(client, MODEL, [b64])
        if r["ok"]:
            total_chars_seq += r["chars"]
            seq_texts.append(r["text"])
            print(f"  P{i+1}: {r['time']:.2f}s, {r['chars']}chars")
        else:
            print(f"  P{i+1}: FAIL ({r.get('error', '')})")
            seq_texts.append("")
    seq_total = time.time() - t0
    print(f"  Total: {seq_total:.1f}s, chars: {total_chars_seq}")

    # Strategy B: All images in one request
    print(f"\n--- 方式B: 批量 ({n_pages}张 → 1个请求) ---")
    t0 = time.time()
    r = await ocr_images(client, MODEL, b64_list)
    batch_total = time.time() - t0
    if r["ok"]:
        print(f"  OK: {r['time']:.2f}s, {r['chars']} chars")
        print(f"  Preview: {r['text'][:400]}")
    else:
        print(f"  FAIL: {r.get('error', '')}, {r['time']:.2f}s")

    # Strategy C: 2 images per request
    print(f"\n--- 方式C: 2张/请求 ---")
    t0 = time.time()
    total_chars_2 = 0
    pair_texts = []
    for i in range(0, len(b64_list), 2):
        chunk = b64_list[i:i+2]
        r = await ocr_images(client, MODEL, chunk)
        if r["ok"]:
            total_chars_2 += r["chars"]
            pair_texts.append(r["text"])
            print(f"  Pair {i//2+1} ({len(chunk)} imgs): {r['time']:.2f}s, {r['chars']}chars")
        else:
            print(f"  Pair {i//2+1}: FAIL ({r.get('error', '')})")
    pair_total = time.time() - t0
    print(f"  Total: {pair_total:.1f}s, chars: {total_chars_2}")

    # Strategy D: All in parallel (concurrent single-image requests)
    print(f"\n--- 方式D: 并发 ({n_pages}张 x 1图/请求, asyncio.gather) ---")
    t0 = time.time()
    tasks = [ocr_images(client, MODEL, [b64]) for b64 in b64_list]
    results = await asyncio.gather(*tasks)
    para_total = time.time() - t0
    total_chars_para = 0
    for i, r in enumerate(results):
        if r["ok"]:
            total_chars_para += r["chars"]
            print(f"  P{i+1}: {r['time']:.2f}s, {r['chars']}chars")
        else:
            print(f"  P{i+1}: FAIL")
    print(f"  Total: {para_total:.1f}s, chars: {total_chars_para}")

    # Summary
    print(f"\n--- 批量对比汇总 ---")
    print(f"  {'方式':<20} {'总耗时':>8} {'总字数':>8} {'备注'}")
    print(f"  {'A-顺序单图':<20} {seq_total:>7.1f}s {total_chars_seq:>8} {'基线'}")
    if r["ok"] or True:  # batch might fail
        print(f"  {'B-全部1请求':<20} {batch_total:>7.1f}s {'?':>8} {'多图1次请求'}")
    print(f"  {'C-2张/请求':<20} {pair_total:>7.1f}s {total_chars_2:>8} {'折中'}")
    print(f"  {'D-并发单图':<20} {para_total:>7.1f}s {total_chars_para:>8} {'asyncio.gather'}")

    # Quality comparison: show page 1 text from each strategy
    print(f"\n--- 第1页文本质量对比 ---")
    if seq_texts:
        print(f"  [顺序] {seq_texts[0][:300]}")
    if pair_texts:
        print(f"  [2张/请求] {pair_texts[0][:300]}")


async def main():
    async with httpx.AsyncClient(timeout=180) as client:
        await test_format_support(client)
        await test_batch_ocr(client)


if __name__ == "__main__":
    asyncio.run(main())
