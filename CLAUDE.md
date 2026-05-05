# CLAUDE.md
1、只能用中文回答我

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Folio-OCR is a three-column document OCR workbench powered by [GLM-OCR](https://huggingface.co/zai-org/GLM-OCR) via Ollama. Desktop app via pywebview + FastAPI embedded server.

## Commands

```bash
# 桌面应用模式（推荐）
python main.py

# Web 服务模式（开发调试）
python server.py

# 使用 uv 管理依赖
uv sync                          # 安装依赖
uv venv --python 3.11            # 创建虚拟环境

# 热重载开发
uvicorn server:app --reload --host 0.0.0.0 --port 3000

# Windows 一键启动（桌面模式）
start.bat

# Windows 一键启动（Web 模式）
start-web.bat

# 打包为 .exe
pyinstaller Folio-OCR.spec
```

## Prerequisites

- [Ollama](https://ollama.com/) installed and `ollama` in PATH
- Pull the model: `ollama pull glm-ocr`
- Python 3.10+ (推荐 3.11，torch 兼容性最好)

## Architecture

**Desktop Entry** (`main.py`):
- pywebview creates a native window loading the FastAPI frontend
- FastAPI runs on a random free port (via `FOLIO_PORT` env var)
- `wait_for_server()` polls `/api/status` until ready, then opens window
- Window close → entire process exits

**Backend** (`server.py`):
- FastAPI app with CORS, version 3.2.0
- All paths based on `APP_ROOT` (resolved from `__file__` or `FOLIO_APP_ROOT` env var, PyInstaller compatible)
- OCR via Ollama `/api/chat` (base64 images), model `glm-ocr` on `localhost:11434`
- Chinese OCR prompt: 识别正文 + 跳过页眉页脚 + 表格输出为 Markdown/HTML
- Auto-strips ```` ```markdown ``` ```` fences from model output
- PDF → PNG via PyMuPDF at 2x resolution
- Upload returns SSE stream (`init` → `page` × N → `done`) for progressive page loading
- SQLite persistence (`folio_ocr.db`), uploads in `uploads/{doc_id}/`, orphan cleanup on startup
- Path traversal protection via `_safe_doc_path()`
- Auto-starts Ollama if not running
- Standalone mode: `python server.py` → port 3000 (or `FOLIO_PORT` env var)

**Frontend** (`index.html`):
- Warm cream/charcoal theme (CSS variables: `--cream`, `--charcoal`, `--accent`)
- Three-column layout: page list (200px) | image preview (flex) | OCR result (380px)
- Multi-file upload (click/drag, images + PDFs mixed), SSE stream parsing via ReadableStream
- Auto-OCR on page select, result caching in state
- Editable OCR results (`<textarea>`) with Edit/Preview toggle (renders HTML tables)
- Batch "OCR All Pages" with Stop button, progress bar + ETA display
- Export: .md / .txt / .docx (Word-compatible HTML, zero dependencies)
- Copy per-page or all pages

**API Endpoints**:
- `GET /api/status` — Service status and Ollama connectivity
- `POST /api/load-model` — Start Ollama if needed, pre-warm model into GPU
- `POST /api/upload` — Upload files (multi-select), returns SSE page stream
- `GET /api/images/{doc_id}/{filename}` — Serve page images
- `POST /api/ocr/{doc_id}/{page_num}` — OCR single page (cached if available)
- `POST /api/ocr/{doc_id}/all` — OCR all pages sequentially
- `DELETE /api/documents/{doc_id}` — Delete document and images
- `GET /api/documents` — List all documents with page/OCR counts
- `GET /api/documents/{doc_id}` — Load document with all pages (for restore)
- `PUT /api/pages/{doc_id}/{page_num}/text` — Save edited OCR text

## Key Details

- PDF pages rendered at 2x scale matrix for OCR quality
- First request after model load ~50s (cold start), subsequent ~0.5s
- GLM-OCR outputs HTML tables for tabular content; Preview mode renders them natively
- DOCX export uses real python-docx, no external HTML needed
- SQLite persistence (`folio_ocr.db`) — documents and OCR results survive server restarts
- Frontend auto-restores last document on page load, auto-saves edits (800ms debounce)
- Desktop mode: `main.py` → pywebview window + FastAPI on random port
- Web mode: `python server.py` → http://localhost:3000
