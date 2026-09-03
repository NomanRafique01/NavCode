"""Continue adapter."""

from pathlib import Path

from navcode.adapters.base import BaseAdapter


class ContinueAdapter(BaseAdapter):

    NAME = "Continue"
    BINARY = "continue"
    CONFIG_DIR = "~/.continue"
    PROJECT_DIR = ".continue"
    PROCESS_NAME = None
    INSTRUCTION_FILE = ".continue/navcode.md"

    def install(self) -> None:
        self._write_instruction_file(
            self.project_root / ".continue" / "navcode.md",
            self._instruction_content(),
        )
        self._inject_mcp_config(
            Path.home() / ".continue" / "config.json"
        )

    def is_detected(self) -> bool:
        return (
            self._detect_binary()
            or self._detect_config_dir()
            or self._detect_project_dir()
        )
