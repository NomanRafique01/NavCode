"""Task classifier for navcode.

Analyses a free-text task description from an agent and returns a
:class:`ScopeLevel` that controls how much codebase context to retrieve.
The classification is entirely rule-based (no ML model required).

Example::

    clf = TaskClassifier()
    result = clf.explain("fix the crash in parse_tokens()")
    # result["scope"] → ScopeLevel.SURGICAL
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Scope levels
# ---------------------------------------------------------------------------


class ScopeLevel(Enum):
    """Granularity of the code change implied by an agent task."""

    SURGICAL = 1       # single function / bug fix
    LOCAL = 2          # single file or module
    CONNECTED = 3      # multiple related modules
    ARCHITECTURAL = 4  # broad system-level change


# ---------------------------------------------------------------------------
# Keyword signal tables
# ---------------------------------------------------------------------------

# Each entry is a plain substring (lowercased) that votes for a scope level.
# The regex variant handles "function_name()" detection at SURGICAL level.

_SURGICAL_KEYWORDS: list[str] = [
    "fix",
    "bug",
    "error",
    "crash",
    "exception",
    "null",
    "undefined",
    "typo",
    "wrong value",
    "off by one",
    "return value",
    "this line",
    "this function",
    "this method",
]

_LOCAL_KEYWORDS: list[str] = [
    "this file",
    "this module",
    "this class",
    "refactor",
    "rename",
    "move",
    "clean up",
    "rewrite",
    "simplify",
    "this component",
    "add method",
    "add function",
    "add field",
]

_CONNECTED_KEYWORDS: list[str] = [
    "feature",
    "add support",
    "integrate",
    "connect",
    "wire up",
    "add endpoint",
    "new route",
    "new api",
    "rate limit",
    "middleware",
    "plugin",
    "extension",
    "across",
    "multiple files",
]

_ARCHITECTURAL_KEYWORDS: list[str] = [
    "migrate",
    "refactor entire",
    "redesign",
    "replace",
    "switch from",
    "move from",
    "all files",
    "entire codebase",
    "everywhere",
    "architecture",
    "restructure",
    "overhaul",
    "convert",
    "upgrade entire",
    "global",
]

# Regex: any token followed by () → surgical (specific function call reference)
_FUNC_CALL_RE = re.compile(r"\b\w+\(\)")

# ---------------------------------------------------------------------------
# Retrieval configs
# ---------------------------------------------------------------------------

_RETRIEVAL_CONFIGS: dict[ScopeLevel, dict[str, Any]] = {
    ScopeLevel.SURGICAL: {
        "max_files": 3,
        "max_symbols": 10,
        "max_tokens": 2000,
        "use_callers": True,
        "use_deps": False,
        "search_depth": 1,
    },
    ScopeLevel.LOCAL: {
        "max_files": 8,
        "max_symbols": 30,
        "max_tokens": 6000,
        "use_callers": True,
        "use_deps": True,
        "search_depth": 1,
    },
    ScopeLevel.CONNECTED: {
        "max_files": 20,
        "max_symbols": 80,
        "max_tokens": 15000,
        "use_callers": True,
        "use_deps": True,
        "search_depth": 2,
    },
    ScopeLevel.ARCHITECTURAL: {
        "max_files": 50,
        "max_symbols": 200,
        "max_tokens": 40000,
        "use_callers": True,
        "use_deps": True,
        "search_depth": 3,
    },
}


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class TaskClassifier:
    """Rule-based task scope classifier.

    Instantiation is lightweight — just loads the keyword tables.

    Example::

        clf = TaskClassifier()
        scope = clf.classify("fix the null pointer in get_user()")
        config = clf.get_retrieval_config(scope)
    """

    def __init__(self) -> None:
        # Pre-build (level → keyword_list) lookup for classify()
        self._keyword_map: dict[ScopeLevel, list[str]] = {
            ScopeLevel.SURGICAL: _SURGICAL_KEYWORDS,
            ScopeLevel.LOCAL: _LOCAL_KEYWORDS,
            ScopeLevel.CONNECTED: _CONNECTED_KEYWORDS,
            ScopeLevel.ARCHITECTURAL: _ARCHITECTURAL_KEYWORDS,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, task: str) -> ScopeLevel:
        """Return the :class:`ScopeLevel` appropriate for *task*.

        Rules (applied in order):

        1. If the task has fewer than 5 words → :attr:`~ScopeLevel.SURGICAL`.
        2. For each scope level collect matching keyword signals.
        3. Also treat a ``word()`` pattern as a SURGICAL signal.
        4. If signals match multiple levels → take the **highest** (most
           expensive) level.
        5. If no signals match → default to :attr:`~ScopeLevel.LOCAL`.

        Args:
            task: Free-text task description.

        Returns:
            :class:`ScopeLevel` enum member.
        """
        normalised = task.lower().strip()

        # Rule 1 — very short task → surgical
        if len(normalised.split()) < 5:
            return ScopeLevel.SURGICAL

        matched_levels: list[ScopeLevel] = []

        # Rule 2 — keyword matching
        for level, keywords in self._keyword_map.items():
            for kw in keywords:
                if kw in normalised:
                    matched_levels.append(level)
                    break  # one match per level is enough

        # Rule 3 — function-call pattern → surgical
        if _FUNC_CALL_RE.search(normalised):
            matched_levels.append(ScopeLevel.SURGICAL)

        if not matched_levels:
            return ScopeLevel.LOCAL

        # Rule 4 — highest (max enum value) wins
        return max(matched_levels, key=lambda l: l.value)

    def classify_with_config(self, task: str) -> tuple[ScopeLevel, dict[str, Any]]:
        """Classify *task* and return both the scope and its retrieval config.

        Convenience wrapper used by :class:`~navcode.retriever.ContextRetriever`.

        Args:
            task: Free-text task description.

        Returns:
            ``(scope, config)`` tuple.
        """
        scope = self.classify(task)
        return scope, self.get_retrieval_config(scope)

    @staticmethod
    def get_retrieval_config(scope: ScopeLevel) -> dict[str, Any]:
        """Return the retrieval parameter dict for *scope*.

        Args:
            scope: A :class:`ScopeLevel` value.

        Returns:
            Dict with keys ``max_files``, ``max_symbols``, ``max_tokens``,
            ``use_callers``, ``use_deps``, ``search_depth``.
        """
        return dict(_RETRIEVAL_CONFIGS[scope])

    def explain(self, task: str) -> dict[str, Any]:
        """Return a full classification breakdown for *task*.

        Args:
            task: Free-text task description.

        Returns:
            Dict with keys:

            * ``task`` — original task string
            * ``scope`` — :class:`ScopeLevel` member
            * ``scope_name`` — ``scope.name`` string
            * ``matched_signals`` — list of keyword strings that fired
            * ``retrieval_config`` — the retrieval parameter dict
            * ``reasoning`` — one-line human-readable explanation
        """
        normalised = task.lower().strip()
        word_count = len(normalised.split())

        matched_signals: list[str] = []
        matched_levels: list[ScopeLevel] = []

        # Short-task fast-path
        if word_count < 5:
            scope = ScopeLevel.SURGICAL
            matched_signals.append("<short task>")
            reasoning = f"Task is only {word_count} word(s) → surgical scope"
            return {
                "task": task,
                "scope": scope,
                "scope_name": scope.name,
                "matched_signals": matched_signals,
                "retrieval_config": self.get_retrieval_config(scope),
                "reasoning": reasoning,
            }

        # Keyword scan
        for level, keywords in self._keyword_map.items():
            for kw in keywords:
                if kw in normalised:
                    matched_signals.append(kw)
                    matched_levels.append(level)
                    break

        # Function-call pattern
        func_matches = _FUNC_CALL_RE.findall(normalised)
        if func_matches:
            matched_signals.extend(func_matches)
            matched_levels.append(ScopeLevel.SURGICAL)

        if not matched_levels:
            scope = ScopeLevel.LOCAL
            reasoning = "No keyword signals detected → defaulting to local scope"
        else:
            scope = max(matched_levels, key=lambda l: l.value)
            signal_summary = " and ".join(f"'{s}'" for s in matched_signals[:3])
            if len(matched_signals) > 3:
                signal_summary += f" (+{len(matched_signals) - 3} more)"
            reasoning = f"Detected {signal_summary} → {scope.name.lower()} scope"

        return {
            "task": task,
            "scope": scope,
            "scope_name": scope.name,
            "matched_signals": matched_signals,
            "retrieval_config": self.get_retrieval_config(scope),
            "reasoning": reasoning,
        }
