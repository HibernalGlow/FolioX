#!/usr/bin/env python3
"""Test concurrency strategies for OCR:
1. Page-level: multiple pages concurrently
2. Region-level: multiple regions of one page concurrently
3. Real server ocr_image_with_layout with concurrent regions
"""
import time, base64, io, asyncio, httpx, zipfile
from PIL import Image
import sys
sys.path.insert(0, ".")
from server import detect_layout, _image_to_b64, _postprocess, OCR_PROMPT, OLLAMA_BASE, OLLAMA_MODEL

ZIP_PATH = r"E:\1Hub\EH\1EHV\[NANIMOSHINAI (笹森トモエ)]\1. 同人志\(C82) 白菓 [氷菓] [空気系☆漢化][NANIMOSHINAI (笹森トモエ)].zip"


def extract_images(zip_path: str, n: int):
    images = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in sorted(zf.namelist()):
            if name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.avif', '.jxl')):
                images.append((name, zf.read(name)))
                if len(images) >= n:
                    break
    return images


async def ocr_single(client: httpx.AsyncClient, b64: str) -> str:
    """Single image OCR call."""
    resp = await client.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": OCR_PROMPT, "images": [b64]}],
            "stream": False,
        },
    )
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "")


async def test_page_concurrency(client: httpx.AsyncClient, n_pages: int = 10):
    """Test 1: Page-level concurrency — sequential vs concurrent."""
    print("=" * 60)
    print(f"测试1: 页级并发 (顺序 vs 并发, {n_pages}页)")
    print("=" * 60)

    images = extract_images(ZIP_PATH, n_pages)

    # Prepare all b64 images upfront
    b64_list = []
    for fname, data in images:
        img = Image.open(io.BytesIO(data))
        img.load()
        b64 = _image_to_b64(img)
        b64_list.append(b64)
        img.close()

    # A: Sequential
    print("\n--- A: 顺序 (for loop) ---")
    t0 = time.time()
    texts_seq = []
    for i, b64 in enumerate(b64_list):
        text = await ocr_single(client, b64)
        chars = len(text)
        texts_seq.append(text)
        print(f"  P{i+1}: {time.time()-t0:.2f}s elapsed, {chars} chars")
    seq_time = time.time() - t0
    print(f"  Total: {seq_time:.1f}s, {sum(len(t) for t in texts_seq)} chars")

    # B: Concurrent (all at once)
    print(f"\n--- B: 并发 asyncio.gather (all {n_pages} at once) ---")
    t0 = time.time()
    tasks = [ocr_single(client, b64) for b64 in b64_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    para_time = time.time() - t0
    texts_para = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"  P{i+1}: ERROR {r}")
            texts_para.append("")
        else:
            texts_para.append(r)
            print(f"  P{i+1}: {len(r)} chars")
    print(f"  Total: {para_time:.1f}s, {sum(len(t) for t in texts_para)} chars")

    # C: Concurrent with semaphore (limit to N concurrent)
    for sem_size in [2, 3, 4]:
        print(f"\n--- C: 并发 semaphore={sem_size} ---")
        sem = asyncio.Semaphore(sem_size)
        async def limited_ocr(b64):
            async with sem:
                return await ocr_single(client, b64)

        t0 = time.time()
        tasks = [limited_ocr(b64) for b64 in b64_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        sem_time = time.time() - t0
        total_chars = sum(len(r) for r in results if isinstance(r, str))
        print(f"  Total: {sem_time:.1f}s, {total_chars} chars")

    # Summary
    print(f"\n--- 页级并发汇总 ---")
    print(f"  {'方式':<25} {'总耗时':>8} {'字数':>8} {'加速比'}")
    print(f"  {'A-顺序':<25} {seq_time:>7.1f}s {sum(len(t) for t in texts_seq):>8} 1.0x")
    print(f"  {'B-并发(all)':<25} {para_time:>7.1f}s {sum(len(t) for t in texts_para):>8} {seq_time/para_time:.1f}x")


async def test_region_concurrency(client: httpx.AsyncClient):
    """Test 2: Region-level concurrency within a single page."""
    print("\n" + "=" * 60)
    print("测试2: 区域级并发 (单页多区域并发OCR)")
    print("=" * 60)

    # Pick a page with multiple regions
    images = extract_images(ZIP_PATH, 5)

    for page_idx in range(len(images)):
        fname, data = images[page_idx]
        img = Image.open(io.BytesIO(data))
        img.load()

        raw_regions = detect_layout(img)
        print(f"\n  Page {page_idx+1}: {len(raw_regions)} regions detected")
        if len(raw_regions) < 3:
            img.close()
            continue

        # Prepare b64 for each region
        region_b64s = []
        for r in raw_regions:
            bbox = r["bbox"]
            cropped = img.crop(bbox)
            b64 = _image_to_b64(cropped)
            region_b64s.append(b64)

        # A: Sequential regions
        print(f"  --- A: 顺序 ({len(region_b64s)} regions) ---")
        t0 = time.time()
        texts_seq = []
        for i, b64 in enumerate(region_b64s):
            text = await ocr_single(client, b64)
            text = _postprocess(text)
            texts_seq.append(text)
            print(f"    R{i+1}: {time.time()-t0:.2f}s, {len(text)} chars ({raw_regions[i]['label']})")
        seq_time = time.time() - t0
        print(f"    Total: {seq_time:.1f}s")

        # B: Concurrent regions
        print(f"  --- B: 并发 ({len(region_b64s)} regions) ---")
        t0 = time.time()
        tasks = [ocr_single(client, b64) for b64 in region_b64s]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        texts_para = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"    R{i+1}: ERROR {r}")
                texts_para.append("")
            else:
                text = _postprocess(r)
                texts_para.append(text)
                print(f"    R{i+1}: {len(text)} chars ({raw_regions[i]['label']})")
        para_time = time.time() - t0
        print(f"    Total: {para_time:.1f}s, speedup: {seq_time/para_time:.1f}x")

        # Text quality comparison
        seq_combined = "\n".join(texts_seq)
        para_combined = "\n".join(texts_para)
        print(f"  --- 文本质量对比 ---")
        print(f"    顺序: {len(seq_combined)} chars")
        print(f"    并发: {len(para_combined)} chars")
        print(f"    差异: {abs(len(seq_combined) - len(para_combined))} chars")

        img.close()
        break  # Only test first multi-region page


async def test_ollama_concurrency_limit(client: httpx.AsyncClient):
    """Test 3: How many concurrent requests can Ollama handle?"""
    print("\n" + "=" * 60)
    print("测试3: Ollama 并发上限 (1/2/4/8 同时请求)")
    print("=" * 60)

    images = extract_images(ZIP_PATH, 8)
    b64_list = []
    for fname, data in images:
        img = Image.open(io.BytesIO(data))
        img.load()
        b64_list.append(_image_to_b64(img))
        img.close()

    for concurrency in [1, 2, 4, 8]:
        print(f"\n  Concurrency={concurrency}:")
        sem = asyncio.Semaphore(concurrency)

        async def limited(b64, idx):
            async with sem:
                t0 = time.time()
                text = await ocr_single(client, b64)
                elapsed = time.time() - t0
                return idx, text, elapsed

        t0 = time.time()
        tasks = [limited(b64, i) for i, b64 in enumerate(b64_list)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.time() - t0

        for r in sorted(results, key=lambda x: x[0] if isinstance(x, tuple) else 999):
            if isinstance(r, tuple):
                idx, text, elapsed = r
                print(f"    P{idx+1}: {elapsed:.2f}s wall, {len(text)} chars")
            else:
                print(f"    ERROR: {r}")
        print(f"    Total: {total_time:.1f}s, avg: {total_time/len(b64_list):.2f}s/page")


async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        await test_page_concurrency(client, n_pages=8)
        await test_region_concurrency(client)
        await test_ollama_concurrency_limit(client)


if __name__ == "__main__":
    asyncio.run(main())
