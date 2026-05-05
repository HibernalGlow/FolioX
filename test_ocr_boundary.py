#!/usr/bin/env python3
"""Test glm-ocr at different image scales to find the size limit."""
import time, base64, io, asyncio, httpx, sys
from PIL import Image

OLLAMA_BASE = "http://localhost:11434"
IMAGE_PATH = r"E:\1Hub\EH\1EHV\[Ogre illust (Ogre)]\1. 同人 CG\11_11.avif"
OCR_PROMPT = "识别图片中的全部内容，输出Markdown格式。跳过页眉页脚和页码。"

img = Image.open(IMAGE_PATH)
img.load()
w, h = img.size

scales = [1.0, 0.75, 0.5, 0.35]

async def test_scale(scale):
    sw, sh = int(w * scale), int(h * scale)
    resized = img.resize((sw, sh), Image.LANCZOS).convert("RGB")
    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    png_kb = len(buf.getvalue()) // 1024
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    t0 = time.time()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/chat",
            json={
                "model": "glm-ocr",
                "messages": [{"role": "user", "content": OCR_PROMPT, "images": [b64]}],
                "stream": False,
            },
        )
    elapsed = time.time() - t0
    ok = resp.status_code == 200
    text_len = (
        len(resp.json().get("message", {}).get("content", "")) if ok else 0
    )
    status = "OK" if ok else "FAIL"
    print(f"  {scale:.0%} ({sw}x{sh}) PNG={png_kb}KB  {status}  {elapsed:.2f}s  {text_len}chars")
    return ok


async def main():
    print(f"原图: {w}x{h}")
    for s in scales:
        await test_scale(s)


asyncio.run(main())
