# -*- coding: utf-8 -*-
"""Folio-OCR CLI — main typer app with subcommands."""
import sys

import typer
from rich.console import Console

# Force UTF-8 on Windows to avoid GBK encoding errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console(force_terminal=True)

cli = typer.Typer(
    name="folio",
    help="[bold cyan]Folio-OCR[/] — 文档 OCR 工作台",
    add_completion=False,
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@cli.command()
def web(
    port: int = typer.Option(3000, "--port", "-p", help="服务端口"),
    host: str = typer.Option("0.0.0.0", "--host", help="绑定地址"),
    reload: bool = typer.Option(False, "--reload", help="开发模式热重载"),
):
    """启动 FastAPI Web 服务"""
    import uvicorn
    console.print(f"[bold cyan]Folio-OCR Web Server[/]  →  http://{host}:{port}")
    uvicorn.run("app:app", host=host, port=port, reload=reload)


@cli.command()
def desktop():
    """启动 pywebview 桌面应用"""
    from .desktop import run_desktop
    run_desktop()


@cli.command()
def batch(
    path: str = typer.Argument(None, help="要扫描的目录路径（不填则交互输入）"),
    output: str = typer.Option(None, "--output", "-o", help="输出 JSON 路径"),
    ext: str = typer.Option(None, "--ext", help="要处理的文件扩展名（逗号分隔）"),
    images: bool = typer.Option(None, "--images/--no-images", help="同时处理独立图片文件"),
    no_layout: bool = typer.Option(None, "--no-layout", help="跳过版面检测（更快）"),
    concurrency: int = typer.Option(None, "--concurrency", "-j", help="最大并发数"),
    incremental: bool = typer.Option(None, "--incremental/--no-incremental", help="增量模式（跳过已处理文件）"),
    blacklist: str = typer.Option(None, "--blacklist", help="黑名单关键词（逗号分隔，跳过匹配的文件夹）"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认直接开始"),
):
    """批量 OCR：扫描目录中的压缩包/图片，输出 JSON"""
    from ..config import BATCH_CONFIG
    # Merge defaults from folio.toml
    _ext = ext if ext is not None else ",".join(BATCH_CONFIG.get("ext", [".zip", ".rar", ".7z", ".tar", ".gz", ".pdf"]))
    _images = images if images is not None else BATCH_CONFIG.get("include_images", False)
    _no_layout = no_layout if no_layout is not None else BATCH_CONFIG.get("no_layout", True)
    _concurrency = concurrency if concurrency is not None else BATCH_CONFIG.get("concurrency", 4)
    _incremental = incremental if incremental is not None else BATCH_CONFIG.get("incremental", True)
    _blacklist = [kw.strip() for kw in blacklist.split(",") if kw.strip()] if blacklist is not None else None

    from .batch import run_batch_cmd
    run_batch_cmd(
        path=path,
        output=output,
        ext=_ext,
        images=_images,
        no_layout=_no_layout,
        concurrency=_concurrency,
        incremental=_incremental,
        blacklist=_blacklist,
        yes=yes,
    )


@cli.command()
def ocr(
    file: str = typer.Argument(..., help="要识别的文件路径（图片/PDF）"),
    layout: bool = typer.Option(True, "--layout/--no-layout", help="版面检测"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径（默认 stdout）"),
    format: str = typer.Option("text", "--format", "-f", help="输出格式: text / json / md"),
):
    """OCR 单个文件"""
    from .ocr_file import run_ocr_cmd
    run_ocr_cmd(file=file, layout=layout, output=output, format=format)
