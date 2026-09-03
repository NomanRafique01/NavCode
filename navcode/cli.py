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
    claude: bool = typer.Option(False, "--claude", help="Initialise for Claude Code."),
    cursor: bool = typer.Option(False, "--cursor", help="Initialise for Cursor."),
    codex: bool = typer.Option(False, "--codex", help="Initialise for Codex."),
    copilot: bool = typer.Option(False, "--copilot", help="Initialise for GitHub Copilot."),
    bob: bool = typer.Option(False, "--bob", help="Initialise for IBM Bob."),
    kimi: bool = typer.Option(False, "--kimi", help="Initialise for Kimi."),
    antigravity: bool = typer.Option(False, "--antigravity", help="Initialise for Antigravity."),
    windsurf: bool = typer.Option(False, "--windsurf", help="Initialise for Windsurf."),
    continue_: bool = typer.Option(False, "--continue", help="Initialise for Continue."),
    auto: bool = typer.Option(False, "--auto", help="Auto-detect and initialise all agents."),
) -> None:
    """Index the current codebase and configure it for the chosen AI agent(s)."""
    if auto:
        for agent in _AGENTS:
            _console.print(
                Panel(
                    f"[yellow]navcode init --{agent}[/yellow] coming soon",
                    title=f"[bold]{agent}[/bold]",
                    border_style="dim",
                )
            )
        return

    flags: dict[str, bool] = {
        "claude": claude,
        "cursor": cursor,
        "codex": codex,
        "copilot": copilot,
        "bob": bob,
        "kimi": kimi,
        "antigravity": antigravity,
        "windsurf": windsurf,
        "continue": continue_,
    }
    selected = [name for name, enabled in flags.items() if enabled]

    if not selected:
        _console.print(
            Panel(
                "Specify an agent flag, e.g. [cyan]navcode init --claude[/cyan], "
                "or use [cyan]--auto[/cyan] to detect all agents.",
                title="[bold yellow]navcode init[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    for agent in selected:
        _console.print(
            Panel(
                f"[yellow]navcode init --{agent}[/yellow] coming soon",
                title=f"[bold]{agent}[/bold]",
                border_style="dim",
            )
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
