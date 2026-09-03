"""Antigravity adapter."""

from pathlib import Path

from navcode.adapters.base import BaseAdapter


class AntigravityAdapter(BaseAdapter):

    NAME = "Antigravity"
    BINARY = "antigravity"
    CONFIG_DIR = "~/.antigravity"
    PROJECT_DIR = ".antigravity"
    PROCESS_NAME = "antigravity"
    INSTRUCTION_FILE = ".antigravity/instructions.md"

    def install(self) -> None:
        self._write_instruction_file(
            self.project_root / ".antigravity" / "instructions.md",
            self._instruction_content(),
        )
        self._inject_mcp_config(
            Path.home() / ".antigravity" / "mcp.json"
        )

    def is_detected(self) -> bool:
        return (
            self._detect_binary()
            or self._detect_config_dir()
            or self._detect_project_dir()
        )
