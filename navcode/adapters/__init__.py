"""navcode agent adapters — one per supported AI coding agent."""

from navcode.adapters.claude import ClaudeAdapter
from navcode.adapters.cursor import CursorAdapter
from navcode.adapters.codex import CodexAdapter
from navcode.adapters.copilot import CopilotAdapter
from navcode.adapters.bob import BobAdapter
from navcode.adapters.kimi import KimiAdapter
from navcode.adapters.antigravity import AntigravityAdapter
from navcode.adapters.windsurf import WindsurfAdapter
from navcode.adapters.continue_ import ContinueAdapter

ALL_ADAPTERS = {
    "claude":      ClaudeAdapter,
    "cursor":      CursorAdapter,
    "codex":       CodexAdapter,
    "copilot":     CopilotAdapter,
    "bob":         BobAdapter,
    "kimi":        KimiAdapter,
    "antigravity": AntigravityAdapter,
    "windsurf":    WindsurfAdapter,
    "continue":    ContinueAdapter,
}

__all__ = [
    "ClaudeAdapter",
    "CursorAdapter",
    "CodexAdapter",
    "CopilotAdapter",
    "BobAdapter",
    "KimiAdapter",
    "AntigravityAdapter",
    "WindsurfAdapter",
    "ContinueAdapter",
    "ALL_ADAPTERS",
]
