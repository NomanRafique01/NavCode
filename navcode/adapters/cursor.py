"""Cursor adapter."""

from pathlib import Path

from navcode.adapters.base import BaseAdapter


class CursorAdapter(BaseAdapter):

    NAME = "Cursor"
    BINARY = "cursor"
    CONFIG_DIR = "~/.cursor"
    PROJECT_DIR = ".cursor"
    PROCESS_NAME = "cursor"
    INSTRUCTION_FILE = ".cursor/rules/navcode.md"

    def install(self) -> None:
        # 1. Write .cursor/rules/navcode.md
        self._write_instruction_file(
            self.project_root / ".cursor" / "rules" / "navcode.md",
            self._instruction_content(),
        )
        # 2. Inject MCP into .cursor/mcp.json
        self._inject_mcp_config(
            self.project_root / ".cursor" / "mcp.json"
        )

    def is_detected(self) -> bool:
        return (
            self._detect_binary()
            or self._detect_config_dir()
            or self._detect_project_dir()
        )
