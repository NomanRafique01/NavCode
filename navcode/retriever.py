"""Context retriever — the core query interface for navcode.

Takes a free-text task description and returns a :class:`ContextResult`
that contains exactly the right code context for an AI agent to work with,
sized and filtered by the task's implied scope.

Pipeline
--------
1. Classify the task (``TaskClassifier``) → scope + retrieval config
2. Hybrid search (FTS5 + semantic) via ``CodebaseIndexer``
3. Expand result set via ``CallGraph`` (callers + deps)
4. Enforce per-scope limits (files / symbols / tokens)
5. Group and rank by file, sort symbols by line number
6. Return a structured :class:`ContextResult`

Example::

    retriever = ContextRetriever(project_root=Path("."))
    result = retriever.get_context("fix the crash in parse_tokens()")
    print(retriever.format_for_agent(result))
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from navcode.classifier import ScopeLevel, TaskClassifier
from navcode.graph import CallGraph
from navcode.indexer import CodebaseIndexer


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SymbolContext:
    """A single code symbol (chunk / function / class) with relevance metadata."""

    name: str
    symbol_type: str
    line_start: int
    line_end: int
    content: str
    score: float


@dataclass
class FileContext:
    """All relevant symbols within one source file."""

    path: str
    language: str
    symbols: list[SymbolContext]
    relevance_score: float  # average symbol score for this file


@dataclass
class ContextResult:
    """Complete retrieval result returned to the agent."""

    task: str
    scope: str
    files: list[FileContext]
    total_tokens: int
    retrieval_config: dict[str, Any]
    explanation: str


# ---------------------------------------------------------------------------
# Token helper
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Rough word-count–based token estimate (words × 1.3).

    Args:
        text: Any string.

    Returns:
        Estimated token count (integer).
    """
    return int(len(text.split()) * 1.3)


# ---------------------------------------------------------------------------
# ContextRetriever
# ---------------------------------------------------------------------------


class ContextRetriever:
    """Orchestrates classification, search, graph expansion, and formatting.

    Args:
        project_root: Root directory of the project being indexed.  The
            database is expected at ``<root>/.navcode/index.db``.
    """

    def __init__(self, project_root: Path) -> None:
        t0 = time.perf_counter()

        self._root = project_root.resolve()
        db_path = self._root / ".navcode" / "index.db"
        graph_path = self._root / ".navcode" / "graph.json"

        self.indexer = CodebaseIndexer(self._root)
        self.classifier = TaskClassifier()

        # Embeddings — optional; warn and continue if unavailable
        self._engine_available = False
        try:
            from navcode.embeddings import EmbeddingsEngine  # lazy import
            self.engine = EmbeddingsEngine()
            self._engine_available = True
        except Exception as exc:  # noqa: BLE001
            self.engine = None  # type: ignore[assignment]
            logger.warning("EmbeddingsEngine unavailable — semantic search disabled: {}", exc)

        # Call/import graph
        self._graph_available = False
        try:
            self.graph = CallGraph(db_path)
            if graph_path.exists():
                self.graph.load(graph_path)
            self._graph_available = True
        except Exception as exc:  # noqa: BLE001
            self.graph = None  # type: ignore[assignment]
            logger.warning("CallGraph unavailable — graph expansion disabled: {}", exc)

        elapsed = time.perf_counter() - t0
        logger.info(
            "ContextRetriever ready in {:.3f}s  "
            "(embeddings={}, graph={})",
            elapsed,
            self._engine_available,
            self._graph_available,
        )

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def get_context(self, task: str) -> ContextResult:
        """Return a :class:`ContextResult` tailored to *task*.

        Args:
            task: Free-text task description from the agent.

        Returns:
            :class:`ContextResult` with ranked files and symbols.
        """
        # ── Step 1: classify ──────────────────────────────────────────
        explanation_data = self.classifier.explain(task)
        scope: ScopeLevel = explanation_data["scope"]
        config: dict[str, Any] = explanation_data["retrieval_config"]
        reasoning: str = explanation_data["reasoning"]

        # ── Step 2: hybrid search ─────────────────────────────────────
        try:
            raw_results: list[dict[str, Any]] = self.indexer.hybrid_search(
                task, limit=config["max_symbols"] * 2
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("hybrid_search failed, falling back to FTS5: {}", exc)
            try:
                raw_results = self.indexer.search(task, limit=config["max_symbols"] * 2)
                # FTS5 results don't carry combined_score — synthesise one
                for r in raw_results:
                    r.setdefault("combined_score", 0.5)
                    r.setdefault("language", "unknown")
            except Exception as exc2:  # noqa: BLE001
                logger.warning("FTS5 search also failed: {}", exc2)
                raw_results = []

        if not raw_results:
            return ContextResult(
                task=task,
                scope=scope.name.lower(),
                files=[],
                total_tokens=0,
                retrieval_config=config,
                explanation=f"No results found. {reasoning}",
            )

        # ── Step 3: graph expansion ───────────────────────────────────
        # Collect extra file paths to load symbols from
        extra_files: set[str] = set()

        if self._graph_available and self.graph is not None:
            if config.get("use_callers"):
                for r in raw_results:
                    sym_bare = r["symbol_name"].split(":")[-1].split("/")[-1]
                    try:
                        for caller in self.graph.get_callers(sym_bare):
                            fp = caller.get("file_path", "")
                            if fp:
                                extra_files.add(fp)
                    except Exception:  # noqa: BLE001
                        pass

            if config.get("use_deps"):
                seen_files = {r["path"] for r in raw_results}
                depth = config.get("search_depth", 1)
                for fpath in list(seen_files):
                    try:
                        for related in self.graph.get_related_files(fpath, depth=depth):
                            extra_files.add(related)
                    except Exception:  # noqa: BLE001
                        pass

        # Load symbols for expanded files (score 0.0 — graph-inferred, not searched)
        expanded_symbols: list[dict[str, Any]] = []
        for fpath in extra_files:
            # Only expand if file isn't already well-covered
            already_covered = sum(1 for r in raw_results if r["path"] == fpath)
            if already_covered >= 3:
                continue
            try:
                file_syms = self.indexer.get_file_symbols(Path(fpath))
                for sym in file_syms:
                    row = dict(sym)
                    row.setdefault("combined_score", 0.0)
                    row.setdefault("language", "unknown")
                    expanded_symbols.append(row)
            except Exception:  # noqa: BLE001
                pass

        all_results = raw_results + expanded_symbols

        # ── Step 4: enforce limits ────────────────────────────────────
        max_files = config["max_files"]
        max_symbols = config["max_symbols"]
        max_tokens = config["max_tokens"]

        # Rank unique files by best combined_score among their symbols
        file_best_score: dict[str, float] = {}
        for r in all_results:
            fp = r["path"]
            sc = r.get("combined_score", 0.0)
            if sc > file_best_score.get(fp, -1.0):
                file_best_score[fp] = sc

        top_files: list[str] = sorted(
            file_best_score, key=lambda f: file_best_score[f], reverse=True
        )[:max_files]
        top_file_set = set(top_files)

        # Filter results to top files, then cap symbol count
        filtered = [r for r in all_results if r["path"] in top_file_set]
        # Sort by score desc before capping so we keep the best symbols
        filtered.sort(key=lambda r: r.get("combined_score", 0.0), reverse=True)
        filtered = filtered[:max_symbols]

        # Token cap — drop lowest-scored symbols until under budget
        total_tok = sum(estimate_tokens(r.get("content", "")) for r in filtered)
        while total_tok > max_tokens and filtered:
            dropped = filtered.pop()  # lowest score (list is sorted desc)
            total_tok -= estimate_tokens(dropped.get("content", ""))

        # ── Step 5: group by file ─────────────────────────────────────
        file_map: dict[str, list[dict[str, Any]]] = {}
        for r in filtered:
            file_map.setdefault(r["path"], []).append(r)

        file_contexts: list[FileContext] = []
        for fpath, syms in file_map.items():
            # Sort symbols by line_start within each file
            syms.sort(key=lambda s: s.get("line_start", 0))

            scores = [s.get("combined_score", 0.0) for s in syms]
            avg_score = sum(scores) / len(scores) if scores else 0.0

            language = syms[0].get("language", "unknown") if syms else "unknown"

            symbol_contexts = [
                SymbolContext(
                    name=s.get("symbol_name", ""),
                    symbol_type=s.get("symbol_type", "chunk"),
                    line_start=s.get("line_start", 0),
                    line_end=s.get("line_end", 0),
                    content=s.get("content", ""),
                    score=s.get("combined_score", 0.0),
                )
                for s in syms
            ]

            file_contexts.append(
                FileContext(
                    path=fpath,
                    language=language,
                    symbols=symbol_contexts,
                    relevance_score=avg_score,
                )
            )

        # ── Step 6: sort files by avg relevance ───────────────────────
        file_contexts.sort(key=lambda fc: fc.relevance_score, reverse=True)

        # ── Step 7: final token count ─────────────────────────────────
        final_tokens = sum(
            estimate_tokens(sym.content)
            for fc in file_contexts
            for sym in fc.symbols
        )

        return ContextResult(
            task=task,
            scope=scope.name.lower(),
            files=file_contexts,
            total_tokens=final_tokens,
            retrieval_config=config,
            explanation=reasoning,
        )

    # ------------------------------------------------------------------
    # Secondary API
    # ------------------------------------------------------------------

    def expand_context(self, file_path: str, reason: str) -> FileContext:
        """Return *all* symbols for *file_path* as a :class:`FileContext`.

        Use this when the agent needs full file content beyond what
        :meth:`get_context` returned.

        Args:
            file_path: Path as stored in the index (relative POSIX string).
            reason: Human-readable reason for the expansion (logged).

        Returns:
            :class:`FileContext` with every symbol in the file.
        """
        logger.info("expand_context: {} — reason: {}", file_path, reason)

        try:
            rows = self.indexer.get_file_symbols(Path(file_path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("expand_context failed for {}: {}", file_path, exc)
            return FileContext(path=file_path, language="unknown", symbols=[], relevance_score=0.0)

        if not rows:
            return FileContext(path=file_path, language="unknown", symbols=[], relevance_score=0.0)

        # get_file_symbols returns sqlite3.Row objects; coerce to dict
        dicts = [dict(r) for r in rows]
        language = dicts[0].get("language", "unknown") if dicts else "unknown"

        symbols = [
            SymbolContext(
                name=r.get("symbol_name", ""),
                symbol_type=r.get("symbol_type", "chunk"),
                line_start=r.get("line_start", 0),
                line_end=r.get("line_end", 0),
                content=r.get("content", ""),
                score=1.0,  # explicit expansion — treat as fully relevant
            )
            for r in dicts
        ]

        return FileContext(
            path=file_path,
            language=language,
            symbols=symbols,
            relevance_score=1.0,
        )

    def get_structure(self) -> dict[str, Any]:
        """Return a lightweight project-structure map for architectural tasks.

        Returns:
            Dict with keys ``entry_points``, ``hotspot_files``,
            ``language_breakdown``, ``total_files``, ``total_symbols``,
            ``total_tokens_estimate``.
        """
        entry_points: list[str] = []
        hotspot_files: list[dict[str, Any]] = []
        if self._graph_available and self.graph is not None:
            try:
                entry_points = self.graph.get_entry_points()
            except Exception:  # noqa: BLE001
                pass
            try:
                hotspot_files = self.graph.get_hotspot_files()
            except Exception:  # noqa: BLE001
                pass

        # Language breakdown from files table
        language_breakdown: dict[str, int] = {}
        total_files = 0
        total_symbols = 0
        total_tokens_estimate = 0
        try:
            stats = self.indexer.get_stats()
            total_files = stats["file_count"]
            total_symbols = stats["symbol_count"]

            rows = self.indexer._conn.execute(
                "SELECT language, COUNT(*) FROM files GROUP BY language"
            ).fetchall()
            for lang, count in rows:
                language_breakdown[lang] = count

            # Rough token estimate from all symbol content lengths
            (raw_chars,) = self.indexer._conn.execute(
                "SELECT COALESCE(SUM(LENGTH(content)), 0) FROM symbols"
            ).fetchone()
            # ~4 chars per token
            total_tokens_estimate = int(raw_chars / 4)
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_structure stats query failed: {}", exc)

        return {
            "entry_points": entry_points,
            "hotspot_files": hotspot_files,
            "language_breakdown": language_breakdown,
            "total_files": total_files,
            "total_symbols": total_symbols,
            "total_tokens_estimate": total_tokens_estimate,
        }

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_for_agent(result: ContextResult) -> str:
        """Render *result* as a markdown string ready for an agent context window.

        Args:
            result: A :class:`ContextResult` from :meth:`get_context`.

        Returns:
            Multi-line markdown string.
        """
        lines: list[str] = [
            f"# navcode context — {result.scope} scope",
            "",
            f"**Task:** {result.task}",
            f"**Reasoning:** {result.explanation}",
            f"**Estimated tokens:** {result.total_tokens:,}",
            "",
        ]

        if not result.files:
            lines.append("_No relevant context found._")
            return "\n".join(lines)

        for fc in result.files:
            score_pct = f"{fc.relevance_score:.2f}"
            lines.append(f"## File: `{fc.path}` (relevance: {score_pct})")
            lines.append(f"**Language:** {fc.language}")
            lines.append("")

            for sym in fc.symbols:
                lines.append(
                    f"### {sym.symbol_type}: `{sym.name}` "
                    f"(lines {sym.line_start}–{sym.line_end})"
                )
                lines.append("")
                lines.append("```")
                lines.append(sym.content.rstrip())
                lines.append("```")
                lines.append("")

        return "\n".join(lines)
