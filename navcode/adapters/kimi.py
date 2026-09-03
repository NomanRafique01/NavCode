"""Kimi Code adapter."""

from pathlib import Path

from navcode.adapters.base import BaseAdapter


class KimiAdapter(BaseAdapter):

    NAME = "Kimi Code"
    BINARY = "kimi"
    CONFIG_DIR = "~/.kimi"
    PROJECT_DIR = "KIMI.md"
    PROCESS_NAME = None
    INSTRUCTION_FILE = "KIMI.md"

    def install(self) -> None:
        self._write_instruction_file(
            self.project_root / "KIMI.md",
            self._instruction_content(),
        )
        self._inject_mcp_config(
            Path.home() / ".kimi" / "mcp.json"
        )

    def is_detected(self) -> bool:
        return (
            self._detect_binary()
            or self._detect_config_dir()
            or self._detect_project_dir()
        )
