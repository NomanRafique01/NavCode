"""Typer CLI entry point for navcode."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from navcode import __version__

app = typer.Typer(
    name="navcode",
    help="Codebase intelligence layer for AI coding agents — 80-90% token reduction.",
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


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        help="Show navcode version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """navcode — codebase intelligence layer for AI coding agents."""


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
    codenav_dir = project_root / ".codenav"
    codenav_dir.mkdir(exist_ok=True)

    # Update .gitignore
    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".codenav/" not in content:
            gitignore.write_text(content + "\n.codenav/\n")
    else:
        gitignore.write_text(".codenav/\n")

    _console.print("[bold green]navcode init[/bold green]\n")

    # Index codebase
    _console.print("Indexing codebase...")
    indexer = CodebaseIndexer(codenav_dir / "index.db")
    from navcode.parser import ASTParser
    from navcode.embeddings import EmbeddingsEngine
    try:
        engine = EmbeddingsEngine()
    except Exception:
        engine = None
        _console.print("[yellow]⚠ Embeddings unavailable — using FTS5 only[/yellow]")

    parser = ASTParser()
    files = list(project_root.rglob("*"))
    indexed = 0
    for f in files:
        if f.is_file():
            try:
                indexer.index_file(f, engine)
                indexed += 1
            except Exception:
                pass
    _console.print(f"[green]✓[/green] Indexed {indexed} files")

    # Build graph
    _console.print("Building call graph...")
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
    codenav_dir = project_root / ".codenav"

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
    from rich.progress import Progress

    project_root = Path.cwd()
    codenav_dir = project_root / ".codenav"

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

    files = [f for f in project_root.rglob("*") if f.is_file()]

    indexed = 0
    failed = 0

    with Progress() as progress:
        task = progress.add_task("Indexing...", total=len(files))
        for f in files:
            try:
                indexer.index_file(f, engine)
                indexed += 1
            except Exception:
                failed += 1
            progress.advance(task)

    # Rebuild graph
    _console.print("Rebuilding call graph...")
    graph = CallGraph(codenav_dir / "index.db")
    graph.save(codenav_dir / "graph.json")

    _console.print(f"\n[green]✓[/green] Indexed: {indexed} files")
    if failed:
        _console.print(f"[yellow]⚠ Skipped: {failed} files[/yellow]")
    _console.print("[green]✓[/green] Graph rebuilt")
    _console.print("[bold green]Reindex complete.[/bold green]")


@app.command()
def logs(
    tail: int = typer.Option(50, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """Show navcode activity logs."""
    project_root = Path.cwd()
    log_path = project_root / ".codenav" / "navcode.log"

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
    codenav_dir = project_root / ".codenav"

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
def mcp_serve(
    root: Path = typer.Option(Path.cwd(), help="Project root"),
) -> None:
    """Start navcode MCP server for agent connections."""
    from navcode.mcp_server import serve

    _console.print("[green]Starting navcode MCP server...[/green]")
    serve(project_root=root)


if __name__ == "__main__":
    app()
