"""Typer CLI entry point for navcode."""

import sys
import io
from pathlib import Path
from typing import Any, Optional

import typer
from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from navcode import __version__

# Force UTF-8 output on Windows so Rich unicode symbols don't crash cp1252
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

app = typer.Typer(
    name="navcode",
    help="Codebase intelligence layer for AI coding agents - 80-90% token reduction.",
    add_completion=False,
)

_console = Console()

# ---------------------------------------------------------------------------
# Version flag
# ---------------------------------------------------------------------------

_AGENTS = [
    "claude",
    "cursor",
    "codex",
    "copilot",
    "bob",
    "kimi",
    "antigravity",
    "windsurf",
    "continue",
]


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        _console.print(f"navcode [bold cyan]{__version__}[/bold cyan]")
        raise typer.Exit()


def _setup_logging() -> None:
    """Activate file logging into .navcode/navcode.log if the dir exists."""
    log_dir = Path.cwd() / ".navcode"
    if log_dir.exists():
        logger.add(
            log_dir / "navcode.log",
            rotation="5 MB",
            retention="7 days",
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        )


@app.callback()
def app_startup(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        help="Show navcode version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Runs before every CLI command."""
    _setup_logging()

    # Step 1 — heal ~/.navcode/ if deleted
    from navcode._bootstrap import ensure_model, is_model_ready
    if not is_model_ready():
        _console.print(
            "[yellow]⚠ navcode model missing — re-downloading...[/yellow]"
        )
        ensure_model()

    # Step 2 — heal .navcode/ if deleted
    # Skip for commands that manage the dirs themselves
    if ctx.invoked_subcommand in ("init", "install", "uninstall"):
        return

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"
    if not codenav_dir.exists():
        _console.print(
            "[yellow]⚠ .navcode/ missing — running auto-reindex...[/yellow]"
        )
        _auto_heal(project_root)


def _collect_files(root: Path) -> list[Path]:
    """Return all indexable files under *root*, skipping ignored dirs and binary files."""
    from navcode.indexer import _SKIP_DIRS, _BINARY_SUFFIXES  # type: ignore[attr-defined]

    result: list[Path] = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        # Skip files inside ignored directories
        try:
            rel_parts = f.relative_to(root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in rel_parts):
            continue
        if f.suffix.lower() in _BINARY_SUFFIXES:
            continue
        result.append(f)
    return result


def _make_progress() -> Progress:
    """Return a polished Rich Progress instance for indexing operations."""
    return Progress(
        SpinnerColumn(spinner_name="dots", style="bold cyan"),
        TextColumn("[bold cyan]Indexing[/bold cyan]"),
        BarColumn(bar_width=None, complete_style="cyan", finished_style="green"),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TextColumn("[dim]•[/dim]"),
        TimeElapsedColumn(),
        TextColumn("[dim]eta[/dim]"),
        TimeRemainingColumn(),
        TextColumn("[dim]{task.fields[current_file]}[/dim]"),
        console=_console,
        transient=True,
        expand=True,
    )


def _run_index(
    indexer: "Any",
    files: list[Path],
    engine: "Any | None",
    label: str = "Indexing",
) -> tuple[int, int]:
    """Run parallel indexing with a live progress bar.  Returns (indexed, failed)."""
    total = len(files)

    with _make_progress() as progress:
        task = progress.add_task(label, total=total, current_file="")

        def _tick() -> None:
            progress.advance(task)

        indexed, failed = indexer.index_files_parallel(files, engine=engine, callback=_tick)

    return indexed, failed


def _auto_heal(project_root: Path) -> None:
    """Recreate .navcode/ and reindex from scratch."""
    from navcode.indexer import CodebaseIndexer
    from navcode.embeddings import EmbeddingsEngine
    from navcode.graph import CallGraph
    from navcode.watcher import CodebaseWatcher

    codenav_dir = project_root / ".navcode"
    codenav_dir.mkdir(exist_ok=True)

    # Re-add to .gitignore if needed
    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".navcode/" not in content:
            gitignore.write_text(content + "\n.navcode/\n")

    db_path = codenav_dir / "index.db"
    indexer = CodebaseIndexer(db_path)

    try:
        engine = EmbeddingsEngine()
    except Exception:
        engine = None

    files = _collect_files(project_root)
    indexed, failed = _run_index(indexer, files, engine)

    _console.print(
        f"[green]✓[/green] Indexed [bold]{indexed}[/bold] files"
        + (f" [yellow]({failed} failed)[/yellow]" if failed else "")
    )

    _console.print("[dim]Building call graph...[/dim]")
    graph = CallGraph(codenav_dir / "index.db")
    graph.save(codenav_dir / "graph.json")
    _console.print("[green]✓[/green] Graph built")

    watcher = CodebaseWatcher(project_root, indexer)
    watcher.start()
    _console.print("[green]✓[/green] Watcher started")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    claude:      bool = typer.Option(False, "--claude",      help="Initialise for Claude Code."),
    cursor:      bool = typer.Option(False, "--cursor",      help="Initialise for Cursor."),
    codex:       bool = typer.Option(False, "--codex",       help="Initialise for Codex."),
    copilot:     bool = typer.Option(False, "--copilot",     help="Initialise for GitHub Copilot."),
    bob:         bool = typer.Option(False, "--bob",         help="Initialise for IBM Bob."),
    kimi:        bool = typer.Option(False, "--kimi",        help="Initialise for Kimi."),
    antigravity: bool = typer.Option(False, "--antigravity", help="Initialise for Antigravity."),
    windsurf:    bool = typer.Option(False, "--windsurf",    help="Initialise for Windsurf."),
    continuee:   bool = typer.Option(False, "--continue",    help="Initialise for Continue."),
    auto:        bool = typer.Option(False, "--auto",        help="Auto-detect and initialise all agents."),
) -> None:
    """Initialize navcode in this project for selected agents."""
    from navcode.adapters import ALL_ADAPTERS
    from navcode.indexer import CodebaseIndexer
    from navcode.watcher import CodebaseWatcher
    from navcode.graph import CallGraph

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"
    codenav_dir.mkdir(exist_ok=True)

    # Update .gitignore
    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".navcode/" not in content:
            gitignore.write_text(content + "\n.navcode/\n")
    else:
        gitignore.write_text(".navcode/\n")

    _console.print("[bold green]navcode init[/bold green]\n")

    # Index codebase
    indexer = CodebaseIndexer(codenav_dir / "index.db")
    from navcode.embeddings import EmbeddingsEngine
    try:
        engine = EmbeddingsEngine()
    except Exception:
        engine = None
        _console.print("[yellow]⚠ Embeddings unavailable — FTS5 only[/yellow]")

    files = _collect_files(project_root)
    _console.print(f"[dim]Found {len(files)} files to index[/dim]")
    indexed, failed = _run_index(indexer, files, engine)

    _console.print(
        f"[green]✓[/green] Indexed [bold]{indexed}[/bold] files"
        + (f" [yellow]({failed} failed)[/yellow]" if failed else "")
    )

    # Build graph
    _console.print("[dim]Building call graph...[/dim]")
    graph = CallGraph(codenav_dir / "index.db")
    graph.save(codenav_dir / "graph.json")
    _console.print("[green]✓[/green] Call graph built")

    # Start watcher
    watcher = CodebaseWatcher(project_root, indexer)
    watcher.start()
    _console.print("[green]✓[/green] File watcher started")

    # Determine which agents to install
    selected: dict = {}
    flags: dict[str, bool] = {
        "claude":      claude,
        "cursor":      cursor,
        "codex":       codex,
        "copilot":     copilot,
        "bob":         bob,
        "kimi":        kimi,
        "antigravity": antigravity,
        "windsurf":    windsurf,
        "continue":    continuee,
    }

    if auto:
        _console.print("\nScanning for installed agents...")
        for name, AdapterClass in ALL_ADAPTERS.items():
            adapter = AdapterClass(project_root)
            detected = adapter.is_detected()
            status = "[green]✓[/green]" if detected else "[dim]✗[/dim]"
            _console.print(f"  {status} {AdapterClass.NAME}")
            if detected:
                selected[name] = AdapterClass
    else:
        for name, enabled in flags.items():
            if enabled:
                selected[name] = ALL_ADAPTERS[name]

    if not selected:
        _console.print(
            "\n[yellow]No agents selected.[/yellow] "
            "Use --claude, --cursor, --auto etc."
        )
        raise typer.Exit()

    # Install each selected adapter
    _console.print("\nInstalling for selected agents...\n")
    for name, AdapterClass in selected.items():
        adapter = AdapterClass(project_root)
        try:
            adapter.install()
            _console.print(f"[bold]\\[{AdapterClass.NAME}][/bold]")
            _console.print("  [green]✓[/green] Installed\n")
        except Exception as e:
            _console.print(f"[red]✗ {AdapterClass.NAME}: {e}[/red]\n")

    _console.print(
        "[bold green]Done.[/bold green] "
        "Run [bold]navcode status[/bold] to verify."
    )


@app.command()
def status() -> None:
    """Show navcode index health and watcher status."""
    from navcode.indexer import CodebaseIndexer
    from navcode.watcher import CodebaseWatcher
    from rich.table import Table

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"

    if not codenav_dir.exists():
        _console.print("[red]✗ navcode not initialized.[/red]")
        _console.print("Run: [bold]navcode init --auto[/bold]")
        raise typer.Exit(1)

    db_path = codenav_dir / "index.db"
    indexer = CodebaseIndexer(db_path)
    s = indexer.get_stats()

    watcher = CodebaseWatcher(project_root, indexer)
    running = watcher.is_running()

    table = Table(title="navcode status")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Initialized", "✓ yes")
    table.add_row("Watcher", "✓ running" if running else "✗ stopped")
    table.add_row("Indexed files", str(s.get("file_count", 0)))
    table.add_row("Total symbols", str(s.get("symbol_count", 0)))
    table.add_row("DB size", f"{s.get('db_size_kb', 0)} KB")
    table.add_row(
        "Graph",
        "✓ built" if (codenav_dir / "graph.json").exists() else "✗ not built",
    )
    table.add_row(
        "Embeddings model",
        "✓ ready"
        if (Path.home() / ".navcode" / "models" / "model_quantized.onnx").exists()
        else "✗ missing",
    )

    _console.print(table)


@app.command()
def reindex() -> None:
    """Force full reindex of the codebase."""
    from navcode.indexer import CodebaseIndexer
    from navcode.embeddings import EmbeddingsEngine
    from navcode.graph import CallGraph

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"

    if not codenav_dir.exists():
        _console.print("[red]✗ navcode not initialized.[/red]")
        raise typer.Exit(1)

    _console.print("[bold]Reindexing codebase...[/bold]\n")

    db_path = codenav_dir / "index.db"
    indexer = CodebaseIndexer(db_path)

    try:
        engine = EmbeddingsEngine()
    except Exception:
        engine = None
        _console.print("[yellow]⚠ Embeddings unavailable — FTS5 only[/yellow]")

    files = _collect_files(project_root)
    _console.print(f"[dim]Found {len(files)} files to index[/dim]")
    indexed, failed = _run_index(indexer, files, engine)

    _console.print(
        f"[green]✓[/green] Indexed [bold]{indexed}[/bold] files"
        + (f" [yellow]({failed} failed)[/yellow]" if failed else "")
    )

    # Rebuild graph
    _console.print("[dim]Rebuilding call graph...[/dim]")
    graph = CallGraph(codenav_dir / "index.db")
    graph.save(codenav_dir / "graph.json")
    _console.print("[green]✓[/green] Graph rebuilt")
    _console.print("[bold green]Reindex complete.[/bold green]")


@app.command()
def logs(
    tail: int = typer.Option(50, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """Show navcode activity logs."""
    project_root = Path.cwd()
    log_path = project_root / ".navcode" / "navcode.log"

    if not log_path.exists():
        _console.print("[yellow]No logs found yet.[/yellow]")
        raise typer.Exit()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    recent = lines[-tail:]

    for line in recent:
        if "ERROR" in line:
            _console.print(f"[red]{line}[/red]")
        elif "WARNING" in line:
            _console.print(f"[yellow]{line}[/yellow]")
        elif "SUCCESS" in line or "✓" in line:
            _console.print(f"[green]{line}[/green]")
        else:
            _console.print(line)


@app.command()
def stats() -> None:
    """Show token savings and usage statistics."""
    from navcode.indexer import CodebaseIndexer
    from rich.table import Table

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"

    if not codenav_dir.exists():
        _console.print("[red]✗ navcode not initialized.[/red]")
        raise typer.Exit(1)

    db_path = codenav_dir / "index.db"
    indexer = CodebaseIndexer(db_path)
    s = indexer.get_stats()

    # Token savings estimate
    file_count = s.get("file_count", 0)
    symbol_count = s.get("symbol_count", 0)
    avg_file_tokens = 2000
    total_raw = file_count * avg_file_tokens
    avg_context_tokens = 4000
    saved = max(0, total_raw - avg_context_tokens)
    reduction = round((saved / total_raw * 100) if total_raw else 0, 1)

    table = Table(title="navcode stats")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Indexed files", str(file_count))
    table.add_row("Total symbols", str(symbol_count))
    table.add_row("DB size", f"{s.get('db_size_kb', 0)} KB")
    table.add_row("Est. raw tokens", f"~{total_raw:,}")
    table.add_row("Est. context tokens", f"~{avg_context_tokens:,}")
    table.add_row("Est. tokens saved", f"~{saved:,}")
    table.add_row("Est. reduction", f"{reduction}%")

    _console.print(table)
    _console.print("\n[dim]Estimates based on avg 2000 tokens/file[/dim]")


@app.command()
def install(
    auto: bool = typer.Option(True, "--auto/--no-auto", help="Auto-detect installed agents."),
) -> None:
    """Fresh-machine setup: download model then index this project.

    Equivalent to running navcode init --auto on a clean install.
    Run this once after pip install navcode.
    """
    from navcode._bootstrap import ensure_model, is_model_ready

    _console.print("[bold cyan]navcode install[/bold cyan]\n")

    # Step 1 — ensure model
    if not is_model_ready():
        _console.print("[bold]Step 1/2[/bold] Downloading embedding model...")
        ensure_model()
    else:
        _console.print("[green]✓[/green] Embedding model already present")

    # Step 2 — delegate to init with --auto
    _console.print("\n[bold]Step 2/2[/bold] Initialising project index...\n")
    ctx = typer.get_current_context()
    ctx.invoke(init, auto=auto)


@app.command()
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    keep_model: bool = typer.Option(
        False, "--keep-model", help="Keep ~/.navcode/ model cache, only remove project index."
    ),
) -> None:
    """Remove navcode data: project index (.navcode/) and optionally the model cache (~/.navcode/).

    After uninstalling, running any navcode command will auto-restore everything.
    To fully remove navcode from your system run: pip uninstall navcode
    """
    import shutil

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"
    navcode_home = Path.home() / ".navcode"

    # --- summarise what will be deleted ---
    targets: list[tuple[str, Path]] = []
    if codenav_dir.exists():
        targets.append(("Project index", codenav_dir))
    if not keep_model and navcode_home.exists():
        targets.append(("Model cache  ", navcode_home))

    if not targets:
        _console.print("[yellow]Nothing to remove — navcode data not found.[/yellow]")
        raise typer.Exit()

    _console.print("[bold]The following will be deleted:[/bold]\n")
    for label, path in targets:
        _console.print(f"  [red]✗[/red] {label}  [dim]{path}[/dim]")

    _console.print()

    if not yes:
        confirm = typer.confirm("Continue?", default=False)
        if not confirm:
            _console.print("[dim]Aborted.[/dim]")
            raise typer.Exit()

    # --- delete ---
    for label, path in targets:
        shutil.rmtree(path, ignore_errors=True)
        _console.print(f"[green]✓[/green] Removed {path}")

    # --- clean .gitignore ---
    gitignore = project_root / ".gitignore"
    if gitignore.exists() and codenav_dir in [p for _, p in targets]:
        text = gitignore.read_text(encoding="utf-8")
        cleaned = "\n".join(
            line for line in text.splitlines() if line.strip() != ".navcode/"
        ).strip() + "\n"
        if cleaned != text:
            gitignore.write_text(cleaned, encoding="utf-8")
            _console.print("[green]✓[/green] Removed .navcode/ from .gitignore")

    _console.print(
        "\n[bold green]Done.[/bold green] "
        "Run [bold]navcode install[/bold] to set up again, "
        "or [bold]pip uninstall navcode[/bold] to remove the tool entirely."
    )


@app.command()
def mcp_serve(
    root: Path = typer.Option(Path.cwd(), help="Project root"),
) -> None:
    """Start navcode MCP server for agent connections."""
    from navcode.mcp_server import serve

    _console.print("[green]Starting navcode MCP server...[/green]")
    serve(project_root=root)


if __name__ == "__main__":
    app()
