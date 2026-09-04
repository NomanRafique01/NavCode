"""Typer CLI entry point for navcode."""

import sys
import io
from pathlib import Path
from typing import Any, Optional

import typer
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.padding import Padding
from rich.text import Text
from rich.rule import Rule
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
# Agent metadata  (name → border color, emoji)
# ---------------------------------------------------------------------------

_AGENT_META: dict[str, tuple[str, str]] = {
    "claude":      ("cyan",  "🤖"),
    "cursor":      ("cyan",  "⚡"),
    "bob":         ("cyan",  "🔵"),
    "codex":       ("cyan",  "🟠"),
    "copilot":     ("cyan",  "🐙"),
    "kimi":        ("cyan",  "🌙"),
    "windsurf":    ("cyan",  "🏄"),
    "antigravity": ("cyan",  "🚀"),
    "continue":    ("cyan",  "▶️ "),
}

_AGENTS = list(_AGENT_META.keys())

# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------

_BANNER_COLORS = ["bright_cyan"] * 6


def _print_banner() -> None:
    """Print the big ASCII art banner in bright_cyan."""
    lines = [
        "  ███╗   ██╗ █████╗ ██╗   ██╗ ██████╗ ██████╗ ██████╗ ███████╗",
        "  ████╗  ██║██╔══██╗██║   ██║██╔════╝██╔═══██╗██╔══██╗██╔════╝",
        "  ██╔██╗ ██║███████║██║   ██║██║     ██║   ██║██║  ██║█████╗  ",
        "  ██║╚██╗██║██╔══██║╚██╗ ██╔╝██║     ██║   ██║██║  ██║██╔══╝  ",
        "  ██║ ╚████║██║  ██║ ╚████╔╝ ╚██████╗╚██████╔╝██████╔╝███████╗",
        "  ╚═╝  ╚═══╝╚═╝  ╚═╝  ╚═══╝   ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝",
    ]

    # pad last line to match others
    max_len = max(len(l) for l in lines)
    lines = [l.ljust(max_len) for l in lines]

    _console.print()
    for line in lines:
        _console.print(f"[bold bright_cyan]{line}[/bold bright_cyan]")
    _console.print(
        f"\n[dim cyan]  Codebase intelligence layer for AI coding agents  "
        f"·  v{__version__}[/dim cyan]\n",
        justify="left",
    )
    _divider()
    


def _divider(label: str = "") -> None:
    """Print a cyan rule line, optionally with a centred label."""
    if label:
        _console.print(Rule(f"[bold cyan] {label} [/bold cyan]", style="cyan"))
    else:
        _console.print(Rule(style="cyan"))


def _ok(msg: str) -> None:
    """Bright-cyan checkmark line."""
    _console.print(f"[bold bright_cyan]  ✓[/bold bright_cyan]  [bright_cyan]{msg}[/bright_cyan]")


def _note(msg: str) -> None:
    """Soft cyan informational line — not an error, not a warning."""
    _console.print(f"[bold cyan]  ℹ[/bold cyan]  [cyan]{msg}[/cyan]")


def _warn(msg: str) -> None:
    """Yellow warning line."""
    _console.print(f"[bold yellow]  ⚠[/bold yellow]  [yellow]{msg}[/yellow]")


def _info(msg: str) -> None:
    """Dim cyan tip / note."""
    _console.print(f"[dim cyan]  {msg}[/dim cyan]")


def _path(p: "str | Path") -> str:
    """Return a Rich-markup string that renders the path in cyan."""
    return f"[bold cyan]{p}[/bold cyan]"


def _cmd(c: str) -> str:
    """Return a Rich-markup string that renders the command in bold cyan on dark background."""
    return f"[bold cyan on grey7]  {c}  [/bold cyan on grey7]"


def _agent_panel(key: str, body: str, *, subtitle: str = "") -> Panel:
    """Build a Rich Panel for an agent with cyan border."""
    _, emoji = _AGENT_META.get(key, ("cyan", "•"))
    from navcode.adapters import ALL_ADAPTERS
    display_name = ALL_ADAPTERS[key].NAME if key in ALL_ADAPTERS else key.title()
    title = Text(f" {emoji}  {display_name} ", style="bold cyan")
    inner = Padding(body, (1, 2))
    return Panel(
        inner,
        title=title,
        subtitle=Text(f" {subtitle} ", style="dim cyan") if subtitle else None,
        border_style="cyan",
        expand=True,
    )


# ---------------------------------------------------------------------------
# Version flag
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        _console.print(
            f"[bold bright_cyan]navcode[/bold bright_cyan] "
            f"[bold cyan]{__version__}[/bold cyan]"
        )
        raise typer.Exit()


def _setup_logging() -> None:
    """Activate file logging into .navcode/navcode.log if the dir exists."""
    logger.remove()  # silence default stderr handler — only log to file
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
        _warn("navcode model missing — re-downloading...")
        ensure_model()

    # Step 2 — heal .navcode/ if deleted
    # Skip for commands that manage the dirs themselves
    if ctx.invoked_subcommand in ("init", "install", "uninstall"):
        return

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"
    if not codenav_dir.exists():
        _warn(".navcode/ missing — running auto-reindex...")
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


def _make_progress(total: int) -> "tuple[Progress, Any]":
    """Create and return a single Rich Progress bar pre-loaded with one task."""
    progress = Progress(
        SpinnerColumn(spinner_name="dots", style="bold cyan"),
        TextColumn("[bold cyan]{task.description}[/bold cyan]"),
        BarColumn(bar_width=None, complete_style="bright_cyan", finished_style="bright_cyan"),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TextColumn("[dim cyan]•[/dim cyan]"),
        TimeElapsedColumn(),
        TextColumn("[dim cyan]eta[/dim cyan]"),
        TimeRemainingColumn(),
        console=_console,
        transient=False,
        expand=True,
    )
    task = progress.add_task("Initialising", total=total)
    return progress, task


def _run_index(
    indexer: "Any",
    files: list[Path],
    engine: "Any | None",
    progress: "Any",
    task: "Any",
) -> tuple[int, int]:
    """Run parallel indexing, advancing *task* on the shared *progress* bar."""

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

    # CodebaseIndexer takes the project root; it builds the db path internally.
    indexer = CodebaseIndexer(project_root)

    try:
        engine = EmbeddingsEngine()
    except Exception:
        engine = None

    files = _collect_files(project_root)
    # +1 step for graph building
    progress, task = _make_progress(len(files) + 1)
    with progress:
        progress.update(task, description="Indexing")
        indexed, failed = _run_index(indexer, files, engine, progress, task)
        progress.update(task, description="Building graph")
        graph = CallGraph(codenav_dir / "index.db")
        graph.save(codenav_dir / "graph.json")
        progress.advance(task)

    _ok(f"Indexed [bold]{indexed}[/bold] files" + (f"  [bold red]({failed} failed)[/bold red]" if failed else ""))
    _ok("Call graph built")

    watcher = CodebaseWatcher(project_root, indexer)
    watcher.start()
    _ok("Watcher started")


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
    from navcode.graph import CallGraph

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"
    db_path = codenav_dir / "index.db"

    # True only when both the folder AND the database are present
    already_indexed = codenav_dir.exists() and db_path.exists()

    if already_indexed:
        _note("navcode already initialised — skipping re-index.")
        return

    _print_banner()

    codenav_dir.mkdir(exist_ok=True)

    # Update .gitignore
    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".navcode/" not in content:
            gitignore.write_text(content + "\n.navcode/\n")
    else:
        gitignore.write_text(".navcode/\n")

    # CodebaseIndexer takes the project root; it resolves the db path internally.
    indexer = CodebaseIndexer(project_root)

    if False:
        pass
    else:
        _divider("Indexing Codebase")

        from navcode.embeddings import EmbeddingsEngine
        try:
            engine = EmbeddingsEngine()
        except Exception:
            engine = None
            _warn("Embeddings unavailable — falling back to FTS5 only")

        files = _collect_files(project_root)
        _info(f"Found {len(files)} files to index")

        # Single unified progress bar: one step per file + one step for graph build
        progress, task = _make_progress(len(files) + 1)
        with progress:
            progress.update(task, description="Indexing")
            indexed, failed = _run_index(indexer, files, engine, progress, task)
            progress.update(task, description="Building graph")
            graph = CallGraph(codenav_dir / "index.db")
            graph.save(codenav_dir / "graph.json")
            progress.advance(task)

        _ok(
            f"Indexed [bold]{indexed}[/bold] files"
            + (f"  [bold red]({failed} failed)[/bold red]" if failed else "")
        )
        _ok("Call graph built")

    # Start background watcher daemon (detached process, survives after init exits)
    from navcode.watcher import is_daemon_running, start_daemon
    if is_daemon_running(project_root):
        _note("Watcher already running — skipping.")
    else:
        start_daemon(project_root)
        _ok("File watcher started")

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

    _divider("Agent Detection")

    if auto:
        _info("Scanning for installed agents...")
        _console.print()
        for name, AdapterClass in ALL_ADAPTERS.items():
            adapter = AdapterClass(project_root)
            detected = adapter.is_detected()
            _, emoji = _AGENT_META.get(name, ("cyan", "•"))
            status = f"[bold bright_cyan]✓  detected[/bold bright_cyan]" if detected else "[dim white]✗  not found[/dim white]"
            _console.print(f"  {emoji}  [bold cyan]{AdapterClass.NAME:<20}[/bold cyan]  {status}")
            if detected:
                selected[name] = AdapterClass
        _console.print()
    else:
        for name, enabled in flags.items():
            if enabled:
                selected[name] = ALL_ADAPTERS[name]

    if not selected:
        _console.print()
        _warn("No agents selected.")
        _info("Use --claude, --cursor, --auto etc. to select agents.")
        _console.print(f"\n  Run: {_cmd('navcode init --auto')}\n")
        raise typer.Exit()

    # Install each selected adapter
    _divider("Installing Agents")
    _console.print()

    for name, AdapterClass in selected.items():
        adapter = AdapterClass(project_root)
        try:
            adapter.install()
            body = (
                f"[bold bright_cyan]✓  Installed successfully[/bold bright_cyan]\n\n"
                f"[dim cyan]navcode MCP tools and instruction file are now active.[/dim cyan]"
            )
            _console.print(_agent_panel(name, body, subtitle="installed"))
            _console.print()
        except Exception as e:
            _console.print(
                Panel(
                    Padding(f"[bold red]✗  {e}[/bold red]", (1, 2)),
                    title=f"[bold red] {AdapterClass.NAME} [/bold red]",
                    border_style="red",
                )
            )
            _console.print()

    _divider()
    _ok("All done!")
    _console.print(
        f"\n  Run {_cmd('navcode status')} to verify your setup.\n"
    )


@app.command()
def watch() -> None:
    """Start the background file watcher (if not already running)."""
    from navcode.watcher import is_daemon_running, start_daemon

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"

    if not codenav_dir.exists():
        _warn("navcode not initialized in this directory.")
        _console.print(f"\n  Run: {_cmd('navcode init --auto')}\n")
        raise typer.Exit(1)

    if is_daemon_running(project_root):
        _note("Watcher is already running.")
        return

    start_daemon(project_root)
    _ok("File watcher started.")


@app.command()
def unwatch() -> None:
    """Stop the background file watcher."""
    from navcode.watcher import stop_daemon

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"

    if not codenav_dir.exists():
        _warn("navcode not initialized in this directory.")
        _console.print(f"\n  Run: {_cmd('navcode init --auto')}\n")
        raise typer.Exit(1)

    killed = stop_daemon(project_root)
    if killed:
        _ok("File watcher stopped.")
    else:
        _note("Watcher was not running.")


@app.command()
def status() -> None:
    """Show navcode index health and watcher status."""
    from navcode.indexer import CodebaseIndexer
    from navcode.watcher import is_daemon_running
    from rich.table import Table

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"

    if not codenav_dir.exists():
        _warn("navcode not initialized in this directory.")
        _console.print(f"\n  Run: {_cmd('navcode init --auto')}\n")
        raise typer.Exit(1)

    indexer = CodebaseIndexer(project_root)
    s = indexer.get_stats()
    db_size_kb = round((codenav_dir / "index.db").stat().st_size / 1024) if (codenav_dir / "index.db").exists() else 0

    running = is_daemon_running(project_root)

    _divider("Project Status")
    _console.print()

    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
        show_lines=True,
        expand=False,
    )
    table.add_column("Property", style="bold cyan", min_width=22)
    table.add_column("Value", style="white", min_width=20)

    table.add_row("Initialized", "[bold bright_cyan]✓  yes[/bold bright_cyan]")
    table.add_row(
        "Watcher",
        "[bold bright_cyan]✓  running[/bold bright_cyan]" if running else "[bold red]✗  stopped[/bold red]",
    )
    table.add_row("Indexed files",  f"[bold white]{s.get('file_count', 0)}[/bold white]")
    table.add_row("Total symbols",  f"[bold white]{s.get('symbol_count', 0)}[/bold white]")
    table.add_row("DB size",        f"[bold white]{db_size_kb} KB[/bold white]")
    table.add_row(
        "Graph",
        "[bold bright_cyan]✓  built[/bold bright_cyan]"
        if (codenav_dir / "graph.json").exists()
        else "[bold red]✗  not built[/bold red]",
    )
    table.add_row(
        "Embeddings model",
        "[bold bright_cyan]✓  ready[/bold bright_cyan]"
        if (Path.home() / ".navcode" / "models" / "model_quantized.onnx").exists()
        else "[bold red]✗  missing[/bold red]",
    )

    _console.print(table)
    _console.print()
    _divider()
    _console.print()


@app.command()
def reindex() -> None:
    """Force full reindex of the codebase."""
    from navcode.indexer import CodebaseIndexer
    from navcode.embeddings import EmbeddingsEngine
    from navcode.graph import CallGraph

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"

    if not codenav_dir.exists():
        _warn("navcode not initialized.")
        _console.print(f"\n  Run: {_cmd('navcode init --auto')}\n")
        raise typer.Exit(1)

    _divider("Reindexing Codebase")
    _console.print()

    indexer = CodebaseIndexer(project_root)

    try:
        engine = EmbeddingsEngine()
    except Exception:
        engine = None
        _warn("Embeddings unavailable — FTS5 only")

    files = _collect_files(project_root)
    _info(f"Found {len(files)} files to index")

    progress, task = _make_progress(len(files) + 1)
    with progress:
        progress.update(task, description="Indexing")
        indexed, failed = _run_index(indexer, files, engine, progress, task)
        progress.update(task, description="Building graph")
        graph = CallGraph(codenav_dir / "index.db")
        graph.save(codenav_dir / "graph.json")
        progress.advance(task)

    _ok(
        f"Indexed [bold]{indexed}[/bold] files"
        + (f"  [bold red]({failed} failed)[/bold red]" if failed else "")
    )
    _ok("Graph rebuilt")

    _console.print()
    _divider()
    _ok("Reindex complete!")
    _console.print()


@app.command()
def logs(
    tail: int = typer.Option(50, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """Show navcode activity logs."""
    project_root = Path.cwd()
    log_path = project_root / ".navcode" / "navcode.log"

    _divider(f"Last {tail} Log Lines")
    _console.print()

    if not log_path.exists():
        _warn("No logs found yet.")
        raise typer.Exit()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    recent = lines[-tail:]

    for line in recent:
        if "ERROR" in line:
            _console.print(f"[bold red]{line}[/bold red]")
        elif "WARNING" in line:
            _console.print(f"[bold yellow]{line}[/bold yellow]")
        elif "SUCCESS" in line or "✓" in line:
            _console.print(f"[bright_cyan]{line}[/bright_cyan]")
        else:
            _console.print(f"[dim white]{line}[/dim white]")

    _console.print()
    _divider()
    _console.print()


@app.command()
def stats() -> None:
    """Show token savings and usage statistics."""
    from navcode.indexer import CodebaseIndexer
    from rich.table import Table

    project_root = Path.cwd()
    codenav_dir = project_root / ".navcode"

    if not codenav_dir.exists():
        _warn("navcode not initialized.")
        _console.print(f"\n  Run: {_cmd('navcode init --auto')}\n")
        raise typer.Exit(1)

    indexer = CodebaseIndexer(project_root)
    s = indexer.get_stats()
    db_size_kb = round((codenav_dir / "index.db").stat().st_size / 1024) if (codenav_dir / "index.db").exists() else 0

    # Token savings estimate
    file_count = s.get("file_count", 0)
    symbol_count = s.get("symbol_count", 0)
    avg_file_tokens = 2000
    total_raw = file_count * avg_file_tokens
    avg_context_tokens = 4000
    saved = max(0, total_raw - avg_context_tokens)
    reduction = round((saved / total_raw * 100) if total_raw else 0, 1)

    _divider("Token Savings Report")
    _console.print()

    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
        show_lines=True,
        expand=False,
    )
    table.add_column("Metric", style="bold cyan", min_width=24)
    table.add_column("Value", style="white", min_width=16)

    table.add_row("Indexed files",        f"[bold white]{file_count}[/bold white]")
    table.add_row("Total symbols",        f"[bold white]{symbol_count}[/bold white]")
    table.add_row("DB size",              f"[bold white]{db_size_kb} KB[/bold white]")
    table.add_row("Est. raw tokens",      f"[bold red]~{total_raw:,}[/bold red]")
    table.add_row("Est. context tokens",  f"[bold yellow]~{avg_context_tokens:,}[/bold yellow]")
    table.add_row("Est. tokens saved",    f"[bold bright_cyan]~{saved:,}[/bold bright_cyan]")
    table.add_row("Est. reduction",       f"[bold bright_cyan]{reduction}%[/bold bright_cyan]")

    _console.print(table)
    _console.print()
    _info("Estimates based on avg 2 000 tokens/file")
    _console.print()
    _divider()
    _console.print()


@app.command()
def install(
    auto: bool = typer.Option(True, "--auto/--no-auto", help="Auto-detect installed agents."),
) -> None:
    """Fresh-machine setup: download model then index this project.

    Equivalent to running navcode init --auto on a clean install.
    Run this once after pip install navcode.
    """
    from navcode._bootstrap import ensure_model, is_model_ready

    _print_banner()
    _divider("Fresh Install")
    _console.print()

    # Step 1 — ensure model
    if not is_model_ready():
        _info("Step 1/2  Downloading embedding model...")
        ensure_model()
        _ok("Embedding model downloaded")
    else:
        _ok("Embedding model already present")

    # Step 2 — delegate to init with --auto
    _console.print()
    _info("Step 2/2  Initialising project index...")
    _console.print()
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
        _warn("Nothing to remove — navcode data not found.")
        raise typer.Exit()

    _divider("Uninstall")
    _console.print()
    _console.print("[bold red]  The following will be deleted:[/bold red]\n")
    for label, path in targets:
        _console.print(f"  [bold red]✗[/bold red]  [bold white]{label}[/bold white]  {_path(path)}")

    _console.print()

    if not yes:
        confirm = typer.confirm("Continue?", default=False)
        if not confirm:
            _info("Aborted.")
            raise typer.Exit()

    # --- delete ---
    for label, path in targets:
        shutil.rmtree(path, ignore_errors=True)
        _ok(f"Removed {_path(path)}")

    # --- clean .gitignore ---
    gitignore = project_root / ".gitignore"
    if gitignore.exists() and codenav_dir in [p for _, p in targets]:
        text = gitignore.read_text(encoding="utf-8")
        cleaned = "\n".join(
            line for line in text.splitlines() if line.strip() != ".navcode/"
        ).strip() + "\n"
        if cleaned != text:
            gitignore.write_text(cleaned, encoding="utf-8")
            _ok(f"Removed .navcode/ from {_path(gitignore)}")

    _console.print()
    _divider()
    _ok("Done.")
    _console.print(
        f"\n  Reinstall anytime:  {_cmd('navcode install')}"
        f"\n  Full removal:       {_cmd('pip uninstall navcode')}\n"
    )


@app.command()
def mcp_serve(
    root: Path = typer.Option(Path.cwd(), help="Project root"),
) -> None:
    """Start navcode MCP server for agent connections."""
    from navcode.mcp_server import serve

    _divider("MCP Server")
    _console.print()
    _ok(f"Starting navcode MCP server at {_path(root)}")
    _info("Waiting for agent connections...")
    _console.print()
    serve(project_root=root)


if __name__ == "__main__":
    app()
