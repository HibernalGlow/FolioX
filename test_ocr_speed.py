#!/usr/bin/env python3
"""Test Ollama OCR speed on a specific image file with auto-resize."""
import time, base64, io, asyncio, httpx, os, sys
from PIL import Image
import pillow_jxl

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "glm-ocr"
OCR_PROMPT = "识别图片中的全部内容，输出Markdown格式。跳过页眉页脚和页码。"
# glm-ocr F16 has issues with images that produce large PNG > ~1MB
MAX_PNG_BYTES = 1.5 * 1024 * 1024  # 1.5MB threshold

IMAGE_PATH = sys.argv[1] if len(sys.argv) > 1 else r"E:\1Hub\EH\1EHV\[Ogre illust (Ogre)]\1. 同人 CG\11_11.avif"

async def ocr_image(img: Image.Image, label: str) -> None:
    """OCR a PIL image and print timing."""
    buf = io.BytesIO()
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    print(f"  [{label}] PNG={len(png_bytes)/1024:.0f}KB, size={img.size}")

    t0 = time.time()
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": OCR_PROMPT, "images": [b64]}],
                "stream": False,
            },
        )
    t_ocr = time.time() - t0
    if resp.status_code == 200:
        result = resp.json()
        text = result.get("message", {}).get("content", "")
        print(f"  [{label}] OCR耗时: {t_ocr:.2f}s, 字数: {len(text)}")
        print(f"  [{label}] 结果(前300字): {text[:300]}")
    else:
        print(f"  [{label}] ERROR {resp.status_code}: {resp.text[:200]}")

async def main():
    print(f"文件: {IMAGE_PATH}")
    print(f"文件大小: {os.path.getsize(IMAGE_PATH)/1024/1024:.1f}MB")

    # Load image
    t0 = time.time()
    img = Image.open(IMAGE_PATH)
    img.load()
    t_load = time.time() - t0
    print(f"图片加载: {t_load:.2f}s  (size={img.size}, mode={img.mode})")

    # Check PNG size at original resolution
    buf = io.BytesIO()
    test_img = img.convert("RGB") if img.mode in ("RGBA", "P") else img
    test_img.save(buf, format="PNG")
    png_size = len(buf.getvalue())
    print(f"原始PNG大小: {png_size/1024/1024:.1f}MB")

    if png_size <= MAX_PNG_BYTES:
        print("\n=== 原图OCR ===")
        await ocr_image(img, "原图")
    else:
        # Find resize ratio
        ratio = (MAX_PNG_BYTES / png_size) ** 0.5
        new_w = int(img.size[0] * ratio)
        new_h = int(img.size[1] * ratio)
        print(f"\n原图PNG过大({png_size/1024/1024:.1f}MB), 缩放至 ~{new_w}x{new_h}")
        img_resized = img.resize((new_w, new_h), Image.LANCZOS)
        await ocr_image(img_resized, f"缩放{ratio:.0%}")

    t_total = time.time() - t0
    print(f"\n[Total] 总耗时: {t_total:.2f}s")

asyncio.run(main())
