#!/usr/bin/env python3
"""Find optimal resolution for glm-ocr that balances accuracy and speed.

Tests multiple scales, measures OCR time, character count, and text quality.
Compares each scale's result against the best available reference to estimate accuracy.
"""
import time, base64, io, asyncio, httpx, sys, os, difflib
from PIL import Image
import pillow_jxl

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "glm-ocr"
OCR_PROMPT = "识别图片中的全部内容，输出Markdown格式。跳过页眉页脚和页码。"

IMAGE_PATH = sys.argv[1] if len(sys.argv) > 1 else r"E:\1Hub\EH\1EHV\[Ogre illust (Ogre)]\1. 同人 CG\11_11.avif"

# Scales to test (from large to small)
SCALES = [1.0, 0.75, 0.6, 0.5, 0.4, 0.3, 0.2]

# Max long side targets (alternative approach: cap max dimension)
MAX_LONG_SIDE_TARGETS = [1600, 1280, 1024, 800]


async def ocr_single(img: Image.Image, label: str, timeout: int = 180) -> dict:
    """OCR a PIL image, return timing and result info."""
    buf = io.BytesIO()
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    b64 = base64.b64encode(png_bytes).decode("utf-8")

    result = {
        "label": label,
        "size": img.size,
        "png_kb": len(png_bytes) // 1024,
        "success": False,
        "time": 0,
        "chars": 0,
        "text": "",
    }

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": OCR_PROMPT, "images": [b64]}],
                    "stream": False,
                },
            )
        elapsed = time.time() - t0
        result["time"] = elapsed

        if resp.status_code == 200:
            data = resp.json()
            text = data.get("message", {}).get("content", "")
            result["success"] = True
            result["chars"] = len(text)
            result["text"] = text
        else:
            result["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
    except httpx.ReadTimeout:
        result["time"] = time.time() - t0
        result["error"] = "Timeout"
    except Exception as e:
        result["time"] = time.time() - t0
        result["error"] = str(e)[:200]

    return result


def normalize_text(text: str) -> str:
    """Normalize text for comparison: strip markdown fences, collapse whitespace."""
    text = text.strip()
    # Remove markdown code fences
    import re
    text = re.sub(r'^```\w*\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def similarity(text1: str, text2: str) -> float:
    """Compute text similarity ratio (0-1) using difflib."""
    n1, n2 = normalize_text(text1), normalize_text(text2)
    if not n1 or not n2:
        return 0.0
    return difflib.SequenceMatcher(None, n1, n2).ratio()


async def test_by_scale(img: Image.Image) -> list[dict]:
    """Test OCR at different percentage scales."""
    w, h = img.size
    print(f"\n{'='*60}")
    print(f"策略1: 按比例缩放 (原图 {w}x{h})")
    print(f"{'='*60}")
    print(f"{'比例':>6} | {'分辨率':>12} | {'PNG':>6} | {'状态':>4} | {'耗时':>6} | {'字数':>5} | {'相似度':>6}")
    print(f"{'-'*6}-+-{'-'*12}-+-{'-'*6}-+-{'-'*4}-+-{'-'*6}-+-{'-'*5}-+-{'-'*6}")

    results = []
    for scale in SCALES:
        sw, sh = int(w * scale), int(h * scale)
        if sw < 10 or sh < 10:
            continue
        resized = img.resize((sw, sh), Image.LANCZOS)
        if resized.mode in ("RGBA", "P"):
            resized = resized.convert("RGB")
        r = await ocr_single(resized, f"{scale:.0%}")
        results.append(r)

        status = "OK" if r["success"] else "FAIL"
        sim = ""
        print(f"{scale:>5.0%} | {sw:>5}x{sh:<5} | {r['png_kb']:>5}KB | {status:>4} | {r['time']:>5.1f}s | {r['chars']:>5} | {sim:>6}")

    return results


async def test_by_max_side(img: Image.Image) -> list[dict]:
    """Test OCR by capping the max dimension to specific targets."""
    w, h = img.size
    long_side = max(w, h)

    print(f"\n{'='*60}")
    print(f"策略2: 限制最大边长 (原图 {w}x{h}, 最长边={long_side})")
    print(f"{'='*60}")
    print(f"{'长边':>6} | {'分辨率':>12} | {'PNG':>6} | {'状态':>4} | {'耗时':>6} | {'字数':>5} | {'相似度':>6}")
    print(f"{'-'*6}-+-{'-'*12}-+-{'-'*6}-+-{'-'*4}-+-{'-'*6}-+-{'-'*5}-+-{'-'*6}")

    results = []
    for target in MAX_LONG_SIDE_TARGETS:
        if target >= long_side:
            sw, sh = w, h
        else:
            ratio = target / long_side
            sw, sh = int(w * ratio), int(h * ratio)
        if sw < 10 or sh < 10:
            continue
        resized = img.resize((sw, sh), Image.LANCZOS)
        if resized.mode in ("RGBA", "P"):
            resized = resized.convert("RGB")
        r = await ocr_single(resized, f"max{target}")
        r["max_side"] = target
        results.append(r)

        status = "OK" if r["success"] else "FAIL"
        print(f"{target:>5}px | {sw:>5}x{sh:<5} | {r['png_kb']:>5}KB | {status:>4} | {r['time']:>5.1f}s | {r['chars']:>5} |")

    return results


def compute_similarities(results: list[dict]) -> None:
    """Compute similarity of each result against the best successful result (most chars)."""
    successful = [r for r in results if r["success"] and r["chars"] > 50]
    if len(successful) < 2:
        return

    # Use the result with most chars as reference
    reference = max(successful, key=lambda r: r["chars"])
    print(f"\n参考基准: {reference['label']} ({reference['size'][0]}x{reference['size'][1]}, {reference['chars']}字)")

    print(f"\n{'标签':>8} | {'分辨率':>12} | {'字数':>5} | {'耗时':>6} | {'相似度':>6} | {'速度/字':>7} | {'评分':>4}")
    print(f"{'-'*8}-+-{'-'*12}-+-{'-'*5}-+-{'-'*6}-+-{'-'*6}-+-{'-'*7}-+-{'-'*4}")

    scores = []
    for r in results:
        if not r["success"] or r["chars"] < 10:
            continue
        sim = similarity(r["text"], reference["text"])
        r["similarity"] = sim
        speed_per_char = r["time"] / max(r["chars"], 1)
        # Composite score: similarity * 0.6 + speed_bonus * 0.4
        # speed_bonus: faster = better, normalize by fastest
        r["speed_per_char"] = speed_per_char
        scores.append((r, sim, speed_per_char))

    if not scores:
        return

    # Normalize speed for scoring
    min_speed = min(s[2] for s in scores)
    max_speed = max(s[2] for s in scores)
    speed_range = max_speed - min_speed if max_speed > min_speed else 1.0

    ranked = []
    for r, sim, spc in scores:
        speed_score = 1.0 - (spc - min_speed) / speed_range  # faster = 1.0, slower = 0.0
        composite = sim * 0.6 + speed_score * 0.4
        r["composite_score"] = composite
        ranked.append((r, sim, spc, composite))

    ranked.sort(key=lambda x: x[3], reverse=True)

    for r, sim, spc, score in ranked:
        print(f"{r['label']:>8} | {r['size'][0]:>5}x{r['size'][1]:<5} | {r['chars']:>5} | {r['time']:>5.1f}s | {sim:>5.1%} | {spc:>6.3f}s | {score:>4.2f}")

    best = ranked[0]
    print(f"\n[最佳平衡点] {best[0]['label']} ({best[0]['size'][0]}x{best[0]['size'][1]})")
    print(f"   相似度: {best[1]:.1%}, 速度: {best[0]['time']:.1f}s, 综合评分: {best[3]:.2f}")

    # Find the "elbow" - where increasing resolution yields diminishing returns
    if len(ranked) >= 2:
        print(f"\n[分辨率推荐]")
        # Group by similarity threshold
        for threshold in [0.95, 0.90, 0.85, 0.80]:
            meets = [r for r, sim, _, _ in ranked if sim >= threshold]
            if meets:
                fastest = min(meets, key=lambda x: x[2])  # fastest speed_per_char
                r = fastest
                print(f"   相似度≥{threshold:.0%}: {r['label']} ({r['size'][0]}x{r['size'][1]}), {r['time']:.1f}s, 相似度={r['similarity']:.1%}")


async def main():
    print(f"文件: {IMAGE_PATH}")
    if not os.path.exists(IMAGE_PATH):
        print(f"文件不存在: {IMAGE_PATH}")
        return

    print(f"文件大小: {os.path.getsize(IMAGE_PATH)/1024/1024:.1f}MB")

    t0 = time.time()
    img = Image.open(IMAGE_PATH)
    img.load()
    print(f"图片加载: {time.time()-t0:.2f}s (size={img.size}, mode={img.mode})")

    # Strategy 1: percentage scales
    scale_results = await test_by_scale(img)

    # Strategy 2: max side targets
    side_results = await test_by_max_side(img)

    # Combine all results for analysis
    all_results = scale_results + side_results

    print(f"\n{'='*60}")
    print(f"综合分析")
    print(f"{'='*60}")

    compute_similarities(all_results)

    # Find the maximum safe PNG size
    successful = [r for r in all_results if r["success"]]
    failed = [r for r in all_results if not r["success"]]

    if failed:
        print(f"\n[警告] 以下分辨率导致失败:")
        for r in failed:
            print(f"   {r['label']} ({r['size'][0]}x{r['size'][1]}): {r.get('error', 'Unknown')[:100]}")

    if successful:
        max_png = max(r["png_kb"] for r in successful)
        min_png = min(r["png_kb"] for r in successful)
        print(f"\n成功范围: PNG {min_png}KB ~ {max_png}KB")

        # Find max successful resolution
        max_res = max(successful, key=lambda r: r["size"][0] * r["size"][1])
        print(f"最大成功分辨率: {max_res['label']} ({max_res['size'][0]}x{max_res['size'][1]}), PNG={max_res['png_kb']}KB")

        # Find min resolution with acceptable quality
        for r in sorted(successful, key=lambda r: r["size"][0] * r["size"][1]):
            sim = r.get("similarity", 0)
            if sim >= 0.9:
                print(f"推荐最低分辨率(相似度≥90%): {r['label']} ({r['size'][0]}x{r['size'][1]})")
                break

    total = time.time() - t0
    print(f"\n总测试耗时: {total:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
