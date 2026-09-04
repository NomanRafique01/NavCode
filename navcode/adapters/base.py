"""Abstract base class for all navcode agent adapters."""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseAdapter(ABC):

    # Override these in every adapter
    NAME: str = ""
    BINARY: str = ""
    CONFIG_DIR: str = ""
    PROJECT_DIR: str = ""
    PROCESS_NAME: str | None = None
    INSTRUCTION_FILE: str = ""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.codenav_dir = project_root / ".navcode"

    @abstractmethod
    def install(self) -> None:
        """Create all required files for this agent."""
        pass

    @abstractmethod
    def is_detected(self) -> bool:
        """Return True if this agent is installed on the system."""
        pass

    def _write_instruction_file(self, path: Path, content: str) -> None:
        """Write instruction file, create parent dirs if needed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _inject_mcp_config(self, config_path: Path) -> None:
        """Inject navcode MCP entry into agent JSON config."""
        import json

        config_path.parent.mkdir(parents=True, exist_ok=True)

        existing = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                pass

        existing.setdefault("mcpServers", {})
        existing["mcpServers"]["navcode"] = {
            "command": "navcode",
            "args": ["mcp-serve"],
            "cwd": str(self.project_root),
        }
        config_path.write_text(
            json.dumps(existing, indent=2),
            encoding="utf-8",
        )

    def _detect_binary(self) -> bool:
        import shutil

        return shutil.which(self.BINARY) is not None

    def _detect_config_dir(self) -> bool:
        return Path.home().joinpath(
            self.CONFIG_DIR.lstrip("~/")
        ).exists()

    def _detect_project_dir(self) -> bool:
        return (self.project_root / self.PROJECT_DIR).exists()

    def _instruction_content(self) -> str:
        return f"""# navcode — Active

## Rules for {self.NAME}

NEVER use read_file or list_directory to explore the codebase.
ALWAYS start every task with navcode_get_context(task=<your task>).
Work ONLY within files and symbols navcode returns.
If you need more: call navcode_expand_context(file_path, reason).

## Available MCP Tools

| Tool | When to use |
|---|---|
| navcode_get_context(task) | FIRST call — always |
| navcode_expand_context(file, reason) | Need more from one file |
| navcode_get_callers(function) | Understand blast radius |
| navcode_get_deps(file) | See what a file imports |
| navcode_search(query) | Find where something is defined |
| navcode_get_structure() | Architectural overview |
| navcode_stats() | Index health check |

## Why
navcode has pre-indexed this codebase.
Using it saves 80-90% tokens vs raw file reads.

Built by Nythris Studio
"""
