"""Claude Code adapter."""

from pathlib import Path

from navcode.adapters.base import BaseAdapter


class ClaudeAdapter(BaseAdapter):

    NAME = "Claude Code"
    BINARY = "claude"
    CONFIG_DIR = "~/.claude"
    PROJECT_DIR = "CLAUDE.md"
    PROCESS_NAME = None
    INSTRUCTION_FILE = "CLAUDE.md"

    def install(self) -> None:
        # 1. Write CLAUDE.md to project root
        self._write_instruction_file(
            self.project_root / "CLAUDE.md",
            self._instruction_content(),
        )
        # 2. Inject MCP into ~/.claude/mcp.json
        self._inject_mcp_config(
            Path.home() / ".claude" / "mcp.json"
        )

    def is_detected(self) -> bool:
        return (
            self._detect_binary()
            or self._detect_config_dir()
            or self._detect_project_dir()
        )
