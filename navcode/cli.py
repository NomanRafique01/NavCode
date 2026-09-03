"""Typer CLI entry point for navcode."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

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
    """Show the current navcode index status for this codebase."""
    _console.print(
        Panel("[yellow]navcode status[/yellow] coming soon", border_style="dim")
    )


@app.command()
def reindex() -> None:
    """Force a full re-index of the current codebase."""
    _console.print(
        Panel("[yellow]navcode reindex[/yellow] coming soon", border_style="dim")
    )


@app.command()
def logs() -> None:
    """Tail the navcode log stream."""
    _console.print(
        Panel("[yellow]navcode logs[/yellow] coming soon", border_style="dim")
    )


@app.command()
def stats() -> None:
    """Display token-reduction statistics for the current session."""
    _console.print(
        Panel("[yellow]navcode stats[/yellow] coming soon", border_style="dim")
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
