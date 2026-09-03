"""Windsurf adapter."""

from navcode.adapters.base import BaseAdapter


class WindsurfAdapter(BaseAdapter):

    NAME = "Windsurf"
    BINARY = "windsurf"
    CONFIG_DIR = "~/.codeium/windsurf"
    PROJECT_DIR = ".windsurf"
    PROCESS_NAME = "windsurf"
    INSTRUCTION_FILE = ".windsurf/rules/navcode.md"

    def install(self) -> None:
        self._write_instruction_file(
            self.project_root / ".windsurf" / "rules" / "navcode.md",
            self._instruction_content(),
        )
        self._inject_mcp_config(
            self.project_root / ".windsurf" / "mcp.json"
        )

    def is_detected(self) -> bool:
        return (
            self._detect_binary()
            or self._detect_config_dir()
            or self._detect_project_dir()
        )
