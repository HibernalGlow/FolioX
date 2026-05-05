# -*- coding: utf-8 -*-
"""Application configuration — all constants in one place."""
import json
import logging
import os
import sys
from pathlib import Path

# Application root directory (compatible with PyInstaller frozen mode)
APP_ROOT = Path(os.environ.get("FOLIO_APP_ROOT", Path(__file__).resolve().parent.parent))

# --- Load folio.toml config ---
_CONFIG_FILE = Path(os.environ.get("FOLIO_CONFIG", APP_ROOT / "folio.toml"))


def _load_toml_config() -> dict:
    """Load folio.toml if it exists, return parsed dict."""
    if not _CONFIG_FILE.exists():
        return {}
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore[no-redef]
        with open(_CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.warning(f"Failed to load config {_CONFIG_FILE}: {e}")
        return {}


TOML_CONFIG = _load_toml_config()
BATCH_CONFIG = TOML_CONFIG.get("batch", {})

# Frontend directory: prefer Svelte build output, fallback to legacy files
FRONTEND_DIR = APP_ROOT / "dist-frontend"
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = APP_ROOT  # fallback to legacy index.html in root

# --- Logging ---
LOG_FILE = APP_ROOT / "server.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("folio")
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- Directories ---
UPLOAD_DIR = APP_ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# --- Database ---
DB_PATH = Path(os.environ.get("DB_PATH", APP_ROOT / "folio_ocr.db"))

# --- Ollama ---
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "glm-ocr")
OCR_PROMPT = "识别图片中的全部内容，输出Markdown格式。跳过页眉页脚和页码。"

# --- OCR image limits ---
OCR_MAX_LONG_SIDE = 1280  # resize so longest edge <= this before sending to Ollama
MAX_IMAGE_HEIGHT = 1600   # max height for single OCR call (fallback whole-image)
SEGMENT_OVERLAP = 80      # overlap pixels when splitting tall images

# --- Layout detection ---
LAYOUT_MODEL_NAME = "PaddlePaddle/PP-DocLayoutV3_safetensors"
LAYOUT_SKIP_LABELS = {"header", "footer", "footnote", "number"}
LAYOUT_SOLO_LABELS = {"table", "figure"}
LAYOUT_THRESHOLD = 0.5

# --- LaTeX -> Unicode mapping (loaded once) ---
_LATEX_MAP_FILE = APP_ROOT / "latex_unicode.json"
with open(_LATEX_MAP_FILE, "r", encoding="utf-8") as _f:
    _LATEX_DATA = json.load(_f)
LATEX_SIMPLE: list[tuple[str, str]] = sorted(
    _LATEX_DATA["simple"].items(), key=lambda x: -len(x[0])
)  # longest match first
LATEX_FRACTIONS: dict[str, str] = _LATEX_DATA.get("fractions", {})
CIRCLED = {str(i): chr(0x2460 + i - 1) for i in range(1, 21)}  # ①-⑳

# --- Upload ---
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".pdf", ".webp", ".avif", ".jxl"}

# --- MIME type mapping ---
MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".jxl": "image/jxl",
}
