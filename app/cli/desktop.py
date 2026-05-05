# -*- coding: utf-8 -*-
"""Folio-OCR CLI — desktop (pywebview) subcommand."""
import os
import sys
import socket
import threading
import logging
import time
from pathlib import Path

from rich.console import Console

console = Console()


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 15.0) -> bool:
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
    APP_DIR = Path(__file__).resolve().parent.parent.parent
    dist_dir = APP_DIR / "dist-frontend"
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        return True

    import subprocess
    frontend_dir = APP_DIR / "frontend"
    if not frontend_dir.exists():
        return False

    console.print("[cyan]Building Svelte frontend...[/]")
    try:
        result = subprocess.run(
            ["pnpm", "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            console.print(f"[red]Frontend build failed:\n{result.stderr}[/]")
            return False
        console.print("[green]✓ Frontend built[/]")
        return True
    except Exception as e:
        console.print(f"[red]Frontend build error: {e}[/]")
        return False


class JsApi:
    """暴露给 JavaScript 的原生 API"""
    def __init__(self):
        self._window = None

    def set_window(self, window):
        self._window = window

    def selectFolder(self, initial_dir: str = "") -> str:
        if not self._window:
            return ""
        try:
            import webview
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=initial_dir or str(Path.home()),
            )
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logging.getLogger(__name__).warning(f"Folder dialog error: {e}")
        return ""

    def isDesktop(self) -> bool:
        return True


def run_desktop():
    """启动 pywebview 桌面应用"""
    import webview

    build_frontend_if_needed()

    port = find_free_port()
    os.environ["FOLIO_PORT"] = str(port)

    # 后台启动 FastAPI
    def _start_server(port: int):
        import uvicorn
        from app import app
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    server_thread = threading.Thread(target=_start_server, args=(port,), daemon=True)
    server_thread.start()

    with console.status("[bold cyan]Starting server...[/]"):
        if not wait_for_server(port):
            console.print("[red]✗ Server failed to start![/]")
            sys.exit(1)

    console.print(f"[green]✓ Server ready on port {port}[/]")

    api = JsApi()
    window = webview.create_window(
        title="Folio-OCR",
        url=f"http://127.0.0.1:{port}",
        width=1400, height=900,
        min_size=(1000, 600),
        text_select=True,
        js_api=api,
    )
    api.set_window(window)

    webview.start(debug=False)
    console.print("[dim]Window closed.[/]")
    sys.exit(0)
