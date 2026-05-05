"""测试 5 种图片格式（PNG/JPEG/WEBP/AVIF/JXL）的编码、解码和 OCR 管线兼容性"""
import base64
import io

import pillow_jxl  # 必须在 PIL 操作前导入，注册 JXL 编解码器  # noqa: F401
import pytest
from PIL import Image

# ── 固件 ──────────────────────────────────────────────

SRC_RGB = Image.new("RGB", (200, 150), (255, 80, 40))
SRC_RGBA = Image.new("RGBA", (200, 150), (255, 80, 40, 200))

FORMATS = [
    pytest.param("PNG", id="png"),
    pytest.param("JPEG", id="jpeg"),
    pytest.param("WEBP", id="webp"),
    pytest.param("AVIF", id="avif"),
    pytest.param("JXL",  id="jxl"),
]


# ── helpers ───────────────────────────────────────────

def roundtrip(src: Image.Image, fmt: str) -> Image.Image:
    """编码后再解码，返回读回的 Image"""
    buf = io.BytesIO()
    src.save(buf, format=fmt)
    buf.seek(0)
    img = Image.open(buf)
    img.load()
    return img


# ── 1. 编码/解码往返 ─────────────────────────────────

class TestRoundtrip:
    @pytest.mark.parametrize("fmt", FORMATS)
    def test_rgb_roundtrip(self, fmt: str):
        """RGB 图像编码→解码，尺寸和模式应保持一致"""
        out = roundtrip(SRC_RGB, fmt)
        assert out.size == SRC_RGB.size, f"{fmt}: size mismatch"
        # JPEG 会丢 alpha，转为 RGB
        if fmt == "JPEG":
            assert out.mode == "RGB"
        else:
            assert out.mode in ("RGB", "RGBA")

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_encoded_nonempty(self, fmt: str):
        """编码后的字节流应非空"""
        buf = io.BytesIO()
        SRC_RGB.save(buf, format=fmt)
        assert len(buf.getvalue()) > 0, f"{fmt}: empty output"


# ── 2. OCR 管线兼容性 ─────────────────────────────────

class TestOcrPipeline:
    """模拟 server.py 中 ocr_image_with_layout 的流程：
    Image.open(path) -> convert("RGB") -> save PNG -> base64
    """

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_open_convert_rgb(self, fmt: str):
        """从格式编码的字节流打开并转为 RGB"""
        buf = io.BytesIO()
        SRC_RGB.save(buf, format=fmt)
        buf.seek(0)
        img = Image.open(buf).convert("RGB")
        assert img.mode == "RGB"
        assert img.size == SRC_RGB.size

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_rgb_to_png_b64(self, fmt: str):
        """从格式编码的字节流转为 PNG base64（OCR 发送给 Ollama 的格式）"""
        buf = io.BytesIO()
        SRC_RGB.save(buf, format=fmt)
        buf.seek(0)
        img = Image.open(buf).convert("RGB")

        out = io.BytesIO()
        img.save(out, format="PNG")
        b64 = base64.b64encode(out.getvalue()).decode("utf-8")
        assert len(b64) > 0, f"{fmt}: empty base64"
        # 解码回来应该还是有效 PNG
        decoded = base64.b64decode(b64)
        verify = Image.open(io.BytesIO(decoded))
        verify.load()
        assert verify.format == "PNG"


# ── 3. RGBA (带透明通道) ──────────────────────────────

RGBA_FORMATS = [
    pytest.param("PNG", id="png"),
    pytest.param("WEBP", id="webp"),
    pytest.param("AVIF", id="avif"),
    pytest.param("JXL",  id="jxl"),
    # JPEG 不支持 alpha，排除
]


class TestAlphaChannel:
    @pytest.mark.parametrize("fmt", RGBA_FORMATS)
    def test_rgba_roundtrip(self, fmt: str):
        """RGBA 图像编码→解码，保留透明通道"""
        out = roundtrip(SRC_RGBA, fmt)
        assert out.mode == "RGBA", f"{fmt}: expected RGBA, got {out.mode}"
        assert out.size == SRC_RGBA.size

    @pytest.mark.parametrize("fmt", RGBA_FORMATS)
    def test_rgba_to_rgb_ocr(self, fmt: str):
        """RGBA 图像经过 convert("RGB") 后可用于 OCR"""
        buf = io.BytesIO()
        SRC_RGBA.save(buf, format=fmt)
        buf.seek(0)
        img = Image.open(buf).convert("RGB")
        assert img.mode == "RGB"
        assert img.size == SRC_RGBA.size
