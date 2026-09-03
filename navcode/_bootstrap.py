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

_HF_BASE: str = (
    "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main"
)
MODEL_URL: str = f"{_HF_BASE}/onnx/model_quantized.onnx"
MODEL_PATH: Path = Path.home() / ".navcode" / "models" / "model_quantized.onnx"

# Tokenizer files required by EmbeddingsEngine
_TOKENIZER_FILES: list[str] = [
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "special_tokens_map.json",
]

_console = Console()


def _download_file(url: str, dest: Path, label: str) -> None:
    """Stream *url* to *dest* with a Rich progress bar.

    Raises:
        httpx.HTTPError: on any HTTP-level failure.
    """
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0)) or None

        with Progress(
            TextColumn(f"[bold blue]{label}[/bold blue]"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=_console,
            transient=True,
        ) as progress:
            task = progress.add_task("download", total=total)
            with dest.open("wb") as fh:
                for chunk in response.iter_bytes(chunk_size=8192):
                    fh.write(chunk)
                    progress.update(task, advance=len(chunk))


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
    else:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        logger.info("ONNX model not found — downloading from HuggingFace…")

        try:
            _download_file(MODEL_URL, MODEL_PATH, "Downloading model")
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

    # Ensure tokenizer files are present alongside the model
    _ensure_tokenizer_files()


def _ensure_tokenizer_files() -> None:
    """Download any missing tokenizer files from HuggingFace."""
    models_dir = MODEL_PATH.parent
    models_dir.mkdir(parents=True, exist_ok=True)

    for filename in _TOKENIZER_FILES:
        dest = models_dir / filename
        if dest.exists():
            logger.debug("Tokenizer file already present: {}", filename)
            continue

        url = f"{_HF_BASE}/{filename}"
        logger.info("Tokenizer file not found — downloading: {}", filename)
        try:
            _download_file(url, dest, f"Downloading {filename}")
            logger.info("Saved {}", dest)
        except httpx.HTTPError as exc:
            _console.print(
                Panel(
                    f"[yellow]navcode[/yellow] could not download [cyan]{filename}[/cyan].\n"
                    f"[dim]{exc}[/dim]\n\n"
                    "Semantic search may be unavailable until this file is present.",
                    title="[bold yellow]⚠ Tokenizer file download skipped[/bold yellow]",
                    border_style="yellow",
                )
            )
            logger.warning("Tokenizer file download failed ({}): {}", filename, exc)
