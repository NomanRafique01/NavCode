"""Allow `python -m navcode` invocation.

On first run this module also ensures the navcode script directory is on PATH
so subsequent calls work as plain `navcode` without `python -m`.
"""
from __future__ import annotations

import os
import sys
import sysconfig
import subprocess
from pathlib import Path


def _scripts_dir() -> Path:
    """Return the Scripts/bin directory where pip installs console scripts."""
    # Prefer user scripts dir (pip install --user) then system scripts
    user_scripts = Path(sysconfig.get_path("scripts", scheme="nt_user" if sys.platform == "win32" else "posix_user"))
    system_scripts = Path(sysconfig.get_path("scripts"))

    # Pick whichever one actually has the navcode executable
    exe_name = "navcode.exe" if sys.platform == "win32" else "navcode"
    if (user_scripts / exe_name).exists():
        return user_scripts
    if (system_scripts / exe_name).exists():
        return system_scripts
    return user_scripts  # fallback


def _ensure_on_path() -> None:
    """Add the navcode scripts directory to PATH for this session and permanently."""
    scripts = _scripts_dir()
    scripts_str = str(scripts)

    # Already on PATH in this session — nothing to do
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if scripts_str in path_dirs:
        return

    # Patch for the current process so the rest of this session works
    os.environ["PATH"] = scripts_str + os.pathsep + os.environ.get("PATH", "")

    # Persist permanently depending on platform
    if sys.platform == "win32":
        _persist_windows(scripts_str)
    else:
        _persist_unix(scripts)


def _persist_windows(scripts_str: str) -> None:
    """Append scripts_str to the User PATH in the Windows registry (no admin needed)."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
        try:
            current, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current = ""

        if scripts_str.lower() not in current.lower():
            new_path = current.rstrip(";") + ";" + scripts_str if current else scripts_str
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
            winreg.CloseKey(key)

            # Broadcast WM_SETTINGCHANGE so Explorer/new terminals pick it up immediately
            try:
                import ctypes
                HWND_BROADCAST = 0xFFFF
                WM_SETTINGCHANGE = 0x001A
                ctypes.windll.user32.SendMessageTimeoutW(
                    HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None
                )
            except Exception:
                pass

            from rich.console import Console
            Console().print(
                f"\n[bold green]✓[/bold green] Added [cyan]{scripts_str}[/cyan] to your PATH.\n"
                "  [dim]Open a new terminal and run[/dim] [bold]navcode --version[/bold] [dim]to confirm.[/dim]\n"
            )
    except Exception:
        pass  # Silent — PATH patching is best-effort


def _persist_unix(scripts: Path) -> None:
    """Append export PATH line to the user's shell rc file."""
    export_line = f'\nexport PATH="{scripts}:$PATH"  # added by navcode\n'

    # Detect shell and target the right rc file
    shell = os.environ.get("SHELL", "")
    home = Path.home()
    candidates: list[Path] = []

    if "zsh" in shell:
        candidates = [home / ".zshrc", home / ".zprofile"]
    elif "bash" in shell:
        candidates = [home / ".bashrc", home / ".bash_profile", home / ".profile"]
    else:
        candidates = [home / ".profile"]

    for rc in candidates:
        try:
            if rc.exists():
                content = rc.read_text()
            else:
                content = ""
            if str(scripts) not in content:
                rc.write_text(content + export_line)
                from rich.console import Console
                Console().print(
                    f"\n[bold green]✓[/bold green] Added [cyan]{scripts}[/cyan] to [dim]{rc}[/dim].\n"
                    "  Run [bold]source {rc}[/bold] or open a new terminal, then use [bold]navcode[/bold] directly.\n"
                )
            break
        except Exception:
            continue


# ── Run PATH self-heal then launch CLI ──────────────────────────────────────

_ensure_on_path()

from navcode.cli import app  # noqa: E402

app()
