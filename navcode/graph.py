"""Call-graph and import-graph construction for navcode.

Reads the indexed symbol table from the SQLite database and builds two
directed graphs using networkx:

* ``call_graph``   — nodes are function names, edges are call relationships.
* ``import_graph`` — nodes are file paths, edges are import relationships.

Both graphs can be serialised to / deserialised from
``<root>/.navcode/graph.json`` using the networkx node-link format.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import networkx as nx
except ImportError as _nx_err:  # pragma: no cover
    raise ImportError(
        "networkx is required for graph features. "
        "Install it with: pip install networkx"
    ) from _nx_err


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _all_symbols(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT path, symbol_name, symbol_type, line_start, line_end, content "
        "FROM symbols"
    ).fetchall()


# Regex: match   import foo, from foo import bar, from .foo import bar
_IMPORT_RE = re.compile(
    r"""
    (?:from\s+(\.{0,3}[\w.]*)\s+import\s+[\w,\s*]+)
    |
    (?:import\s+([\w.]+))
    """,
    re.VERBOSE,
)


def _resolve_import(importer: str, raw: str, known_files: set[str]) -> str | None:
    """Try to map a raw import string to a known file path.

    Args:
        importer:    POSIX path of the importing file (e.g. ``navcode/cli.py``).
        raw:         The raw module string from the import statement
                     (e.g. ``navcode.indexer`` or ``.utils``).
        known_files: Set of all indexed file paths.

    Returns:
        Matched file path string, or ``None`` if unresolvable.
    """
    if not raw:
        return None

    # Normalise dots → slashes
    dots = len(raw) - len(raw.lstrip("."))
    module_part = raw.lstrip(".")

    if dots:
        # Relative import — resolve from importer directory
        base = Path(importer).parent
        for _ in range(dots - 1):
            base = base.parent
        candidate_base = (base / module_part.replace(".", "/")).as_posix() if module_part else base.as_posix()
    else:
        candidate_base = module_part.replace(".", "/")

    # Try direct .py and __init__.py
    for suffix in (".py", "/__init__.py", ".ts", ".js", ".tsx", ".jsx"):
        candidate = candidate_base + suffix
        if candidate in known_files:
            return candidate
        # Also try without leading path component (absolute from root)
        parts = candidate.split("/")
        for i in range(len(parts)):
            short = "/".join(parts[i:])
            if short in known_files:
                return short

    return None


# ---------------------------------------------------------------------------
# CallGraph
# ---------------------------------------------------------------------------


class CallGraph:
    """Dual directed-graph model of a codebase.

    Attributes:
        call_graph:   :class:`networkx.DiGraph` of function → function call edges.
        import_graph: :class:`networkx.DiGraph` of file → file import edges.

    Example::

        cg = CallGraph(db_path=Path(".navcode/index.db"))
        print(cg.get_hotspot_files())
    """

    def __init__(self, db_path: Path) -> None:
        """Build both graphs by reading the indexer's SQLite database.

        Args:
            db_path: Path to the ``.navcode/index.db`` file produced by
                :class:`~navcode.indexer.CodebaseIndexer`.
        """
        if not db_path.exists():
            raise FileNotFoundError(
                f"Index database not found at {db_path}. "
                "Run 'navcode init' to build the index first."
            )

        t0 = time.perf_counter()
        self._conn = _open_db(db_path)
        self.call_graph: nx.DiGraph = nx.DiGraph()
        self.import_graph: nx.DiGraph = nx.DiGraph()

        rows = _all_symbols(self._conn)
        self._symbols: list[dict[str, Any]] = [dict(r) for r in rows]

        self.build_import_graph()
        self.build_call_graph()

        elapsed = time.perf_counter() - t0
        logger.info(
            "CallGraph built in {:.3f}s  "
            "(import_edges={}, call_edges={}, nodes_call={}, nodes_import={})",
            elapsed,
            self.import_graph.number_of_edges(),
            self.call_graph.number_of_edges(),
            self.call_graph.number_of_nodes(),
            self.import_graph.number_of_nodes(),
        )

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build_import_graph(self) -> None:
        """Populate :attr:`import_graph` from ``import`` symbols in the DB."""
        self.import_graph.clear()

        known_files: set[str] = {s["path"] for s in self._symbols}
        # seed all known files as nodes even if they have no edges
        for f in known_files:
            self.import_graph.add_node(f)

        import_symbols = [s for s in self._symbols if s["symbol_type"] == "import"]
        for sym in import_symbols:
            importer = sym["path"]
            content: str = sym["content"] or ""
            for match in _IMPORT_RE.finditer(content):
                raw = match.group(1) or match.group(2) or ""
                raw = raw.strip()
                if not raw:
                    continue
                target = _resolve_import(importer, raw, known_files)
                if target and target != importer:
                    self.import_graph.add_edge(importer, target, raw_import=raw)

    def build_call_graph(self) -> None:
        """Populate :attr:`call_graph` from function-body content in the DB."""
        self.call_graph.clear()

        # Collect all known function names → their metadata
        func_symbols: list[dict[str, Any]] = [
            s for s in self._symbols
            if s["symbol_type"] in ("function", "method", "chunk")
        ]
        # name → list of symbol dicts (same name can exist in multiple files)
        name_index: dict[str, list[dict[str, Any]]] = {}
        for sym in func_symbols:
            name = sym["symbol_name"].split(":")[-1].split("/")[-1]
            name_index.setdefault(name, []).append(sym)

        # Seed nodes
        for sym in func_symbols:
            node_id = f"{sym['path']}::{sym['symbol_name']}"
            self.call_graph.add_node(
                node_id,
                symbol_name=sym["symbol_name"],
                file_path=sym["path"],
                line_start=sym["line_start"],
            )

        # Build a fast set of bare function names for scanning
        known_names = set(name_index.keys())

        # Simple word-boundary scan for calls inside content
        _call_pattern = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in known_names if len(n) > 2) + r")\s*\("
        ) if known_names else None

        if _call_pattern is None:
            return

        for caller_sym in func_symbols:
            caller_id = f"{caller_sym['path']}::{caller_sym['symbol_name']}"
            content: str = caller_sym["content"] or ""
            for m in _call_pattern.finditer(content):
                callee_name = m.group(1)
                if callee_name == caller_sym["symbol_name"].split(":")[-1].split("/")[-1]:
                    continue  # skip self-references
                for callee_sym in name_index.get(callee_name, []):
                    callee_id = f"{callee_sym['path']}::{callee_sym['symbol_name']}"
                    if caller_id == callee_id:
                        continue
                    self.call_graph.add_edge(
                        caller_id,
                        callee_id,
                        caller_file=caller_sym["path"],
                        callee_file=callee_sym["path"],
                        line=caller_sym["line_start"],
                    )

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_callers(self, function_name: str) -> list[dict[str, Any]]:
        """Return all functions that call *function_name*.

        Args:
            function_name: Bare function or method name.

        Returns:
            List of ``{function_name, file_path, line_start}`` dicts.
        """
        results: list[dict[str, Any]] = []
        for node, data in self.call_graph.nodes(data=True):
            if data.get("symbol_name", "").split(":")[-1].split("/")[-1] == function_name:
                for pred in self.call_graph.predecessors(node):
                    pd = self.call_graph.nodes[pred]
                    results.append(
                        {
                            "function_name": pd.get("symbol_name", pred),
                            "file_path": pd.get("file_path", ""),
                            "line_start": pd.get("line_start", 0),
                        }
                    )
        return results

    def get_callees(self, function_name: str) -> list[dict[str, Any]]:
        """Return all functions called by *function_name*.

        Args:
            function_name: Bare function or method name.

        Returns:
            List of ``{function_name, file_path, line_start}`` dicts.
        """
        results: list[dict[str, Any]] = []
        for node, data in self.call_graph.nodes(data=True):
            if data.get("symbol_name", "").split(":")[-1].split("/")[-1] == function_name:
                for succ in self.call_graph.successors(node):
                    sd = self.call_graph.nodes[succ]
                    results.append(
                        {
                            "function_name": sd.get("symbol_name", succ),
                            "file_path": sd.get("file_path", ""),
                            "line_start": sd.get("line_start", 0),
                        }
                    )
        return results

    def get_file_deps(self, file_path: str) -> list[str]:
        """Return files that *file_path* imports.

        Args:
            file_path: Source file path (as stored in the index).

        Returns:
            List of imported file path strings.
        """
        if file_path not in self.import_graph:
            return []
        return list(self.import_graph.successors(file_path))

    def get_file_dependents(self, file_path: str) -> list[str]:
        """Return files that import *file_path*.

        Args:
            file_path: Source file path.

        Returns:
            List of file path strings that depend on *file_path*.
        """
        if file_path not in self.import_graph:
            return []
        return list(self.import_graph.predecessors(file_path))

    def get_related_files(self, file_path: str, depth: int = 2) -> list[str]:
        """Return files reachable within *depth* hops in both directions.

        Performs BFS on the undirected view of the import graph so that
        both importers and importees are discovered.

        Args:
            file_path: Starting file.
            depth: Maximum hop count.

        Returns:
            List of related file paths (excluding *file_path* itself).
        """
        if file_path not in self.import_graph:
            return []
        undirected = self.import_graph.to_undirected()
        reachable = nx.single_source_shortest_path_length(
            undirected, file_path, cutoff=depth
        )
        return [f for f in reachable if f != file_path]

    def get_entry_points(self) -> list[str]:
        """Return files with no incoming import edges (entry points / mains).

        Returns:
            List of file path strings.
        """
        return [
            n for n in self.import_graph.nodes()
            if self.import_graph.in_degree(n) == 0
        ]

    def get_hotspot_files(self, top_n: int = 10) -> list[dict[str, Any]]:
        """Return the most-imported files.

        Args:
            top_n: How many files to return.

        Returns:
            List of ``{file_path, dependent_count}`` dicts sorted descending.
        """
        scored = [
            {"file_path": n, "dependent_count": self.import_graph.in_degree(n)}
            for n in self.import_graph.nodes()
        ]
        scored.sort(key=lambda x: x["dependent_count"], reverse=True)
        return scored[:top_n]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Serialise both graphs to *path* as JSON (node-link format).

        Args:
            path: Destination file (e.g. ``Path(".navcode/graph.json")``).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "call_graph": nx.node_link_data(self.call_graph),
            "import_graph": nx.node_link_data(self.import_graph),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.debug("CallGraph saved to {}", path)

    def load(self, path: Path) -> None:
        """Deserialise both graphs from a JSON file written by :meth:`save`.

        Args:
            path: Source file.
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        self.call_graph = nx.node_link_graph(data["call_graph"], directed=True)
        self.import_graph = nx.node_link_graph(data["import_graph"], directed=True)
        logger.debug(
            "CallGraph loaded from {} (import_edges={}, call_edges={})",
            path,
            self.import_graph.number_of_edges(),
            self.call_graph.number_of_edges(),
        )
