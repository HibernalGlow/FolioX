# -*- coding: utf-8 -*-
"""
Folio-OCR Desktop Entry
使用 pywebview 将 FastAPI 后端 + Svelte 前端打包为桌面应用
"""
import os
import sys
import time
import socket
import threading
import logging
import subprocess
from pathlib import Path

# 确保工作目录为脚本所在目录（兼容 PyInstaller 打包后的路径）
APP_DIR = Path(__file__).parent.resolve()
os.chdir(APP_DIR)

# --- 日志 ---
LOG_FILE = APP_DIR / "desktop.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def find_free_port() -> int:
    """找一个可用的本地端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """等待 FastAPI 服务就绪"""
    import httpx

    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=2.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def build_frontend_if_needed():
    """如果前端未构建，自动执行 pnpm build"""
    dist_dir = APP_DIR / "dist-frontend"
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        logger.info("Frontend already built, skipping...")
        return True

    frontend_dir = APP_DIR / "frontend"
    if not frontend_dir.exists():
        logger.warning("No frontend/ directory found, using legacy mode")
        return False

    logger.info("Building Svelte frontend...")
    try:
        result = subprocess.run(
            ["pnpm", "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"Frontend build failed:\n{result.stderr}")
            return False
        logger.info("Frontend built successfully")
        return True
    except Exception as e:
        logger.error(f"Frontend build error: {e}")
        return False


def start_server(port: int):
    """在子线程中启动 FastAPI 服务"""
    import uvicorn
    from app import app

    logger.info(f"Starting FastAPI on 127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main():
    """桌面应用主入口"""
    import webview

    # 尝试构建前端
    build_frontend_if_needed()

    port = find_free_port()
    logger.info(f"Using port: {port}")

    # 将端口写入环境变量，供 server.py 读取
    os.environ["FOLIO_PORT"] = str(port)

    # 后台启动 FastAPI
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()

    # 等待服务就绪
    if not wait_for_server(port):
        logger.error("Server failed to start within timeout!")
        sys.exit(1)

    logger.info("Server is ready, opening window...")

    # 创建桌面窗口
    window = webview.create_window(
        title="Folio-OCR",
        url=f"http://127.0.0.1:{port}",
        width=1400,
        height=900,
        min_size=(1000, 600),
        text_select=True,
    )

    # 窗口关闭时，整个进程退出
    webview.start(debug=False)
    logger.info("Window closed, exiting...")
    sys.exit(0)


if __name__ == "__main__":
    main()
