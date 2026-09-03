"""GitHub Copilot adapter."""

from navcode.adapters.base import BaseAdapter


class CopilotAdapter(BaseAdapter):

    NAME = "GitHub Copilot"
    BINARY = "gh"
    CONFIG_DIR = "~/.config/gh"
    PROJECT_DIR = ".github"
    PROCESS_NAME = None
    INSTRUCTION_FILE = ".github/copilot-instructions.md"

    def install(self) -> None:
        # Write .github/copilot-instructions.md
        self._write_instruction_file(
            self.project_root / ".github" / "copilot-instructions.md",
            self._instruction_content(),
        )
        # No MCP config for Copilot yet

    def is_detected(self) -> bool:
        return self._detect_binary() or self._detect_project_dir()
