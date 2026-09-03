# navcode/_bootstrap.py
# Nythris Studio — navcode
# Author: Noman Rafique

"""Bootstrap utilities — ensures the ONNX embedding model is present on disk."""

from pathlib import Path

import httpx
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

MODEL_URL: str = (
    "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2"
    "/resolve/main/onnx/model_quantized.onnx"
)
MODEL_PATH: Path = Path.home() / ".navcode" / "models" / "model_quantized.onnx"

_console = Console()


def ensure_model() -> None:
    """Ensure the quantised ONNX embedding model exists locally.

    If the model file is already present at ``~/.navcode/models/model_quantized.onnx``
    this function returns immediately.  On first run it streams the file from
    HuggingFace, displaying a Rich progress bar.  Network failures are caught,
    shown as a Rich warning panel, and silently swallowed so the rest of navcode
    can still load (the model will be re-attempted on ``navcode init``).
    """
    if MODEL_PATH.exists():
        logger.debug("ONNX model already present at {}", MODEL_PATH)
        return

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.info("ONNX model not found — downloading from HuggingFace…")

    try:
        with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0)) or None

            with Progress(
                TextColumn("[bold blue]Downloading model[/bold blue]"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=_console,
                transient=True,
            ) as progress:
                task = progress.add_task("download", total=total)
                with MODEL_PATH.open("wb") as fh:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        fh.write(chunk)
                        progress.update(task, advance=len(chunk))

        logger.info("Model saved to {}", MODEL_PATH)

    except httpx.HTTPError as exc:
        _console.print(
            Panel(
                f"[yellow]navcode[/yellow] could not download the embedding model.\n"
                f"[dim]{exc}[/dim]\n\n"
                "navcode will still load — the model will be downloaded on first "
                "[cyan]navcode init[/cyan].",
                title="[bold yellow]⚠ Model download skipped[/bold yellow]",
                border_style="yellow",
            )
        )
        logger.warning("Model download failed: {}", exc)
