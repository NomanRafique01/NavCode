"""Codex CLI adapter."""

from pathlib import Path

from navcode.adapters.base import BaseAdapter


class CodexAdapter(BaseAdapter):

    NAME = "Codex CLI"
    BINARY = "codex"
    CONFIG_DIR = "~/.codex"
    PROJECT_DIR = "AGENTS.md"
    PROCESS_NAME = None
    INSTRUCTION_FILE = "AGENTS.md"

    def install(self) -> None:
        # 1. Write AGENTS.md
        self._write_instruction_file(
            self.project_root / "AGENTS.md",
            self._instruction_content(),
        )
        # 2. Inject MCP into ~/.codex/config.json
        self._inject_mcp_config(
            Path.home() / ".codex" / "config.json"
        )

    def is_detected(self) -> bool:
        return (
            self._detect_binary()
            or self._detect_config_dir()
            or self._detect_project_dir()
        )
