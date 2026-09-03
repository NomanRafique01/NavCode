"""IBM Bob adapter."""

from pathlib import Path

from navcode.adapters.base import BaseAdapter


class BobAdapter(BaseAdapter):

    NAME = "IBM Bob"
    BINARY = "bob"
    CONFIG_DIR = "~/.bob"
    PROJECT_DIR = ".bob"
    PROCESS_NAME = "bob-agent"
    INSTRUCTION_FILE = ".bob/instructions.md"

    def install(self) -> None:
        # 1. Write .bob/instructions.md
        self._write_instruction_file(
            self.project_root / ".bob" / "instructions.md",
            self._instruction_content(),
        )
        # 2. Inject MCP into ~/.bob/mcp.json
        self._inject_mcp_config(
            Path.home() / ".bob" / "mcp.json"
        )

    def is_detected(self) -> bool:
        return (
            self._detect_binary()
            or self._detect_config_dir()
            or self._detect_project_dir()
        )
