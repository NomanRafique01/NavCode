"""SQLite FTS5-backed codebase indexer for navcode.

Maintains two tables:
- ``files``   — one row per indexed source file (metadata).
- ``symbols`` — FTS5 virtual table of code chunks extracted from each file.

The indexer performs basic 50-line chunking.  Proper AST-level symbol
extraction will be handled by ``parser.py`` in a later feature branch.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_RELATIVE_PATH = ".codenav/index.db"
CHUNK_LINES = 50

# Map file extension → language tag
_EXT_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "javascript",
    ".jsx": "javascript",
    ".tsx": "javascript",
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".cs": "csharp",
}

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL_FILES = """
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    path          TEXT    UNIQUE NOT NULL,
    language      TEXT    NOT NULL DEFAULT 'unknown',
    last_modified REAL    NOT NULL DEFAULT 0,
    size          INTEGER NOT NULL DEFAULT 0
);
"""

_DDL_SYMBOLS = """
CREATE VIRTUAL TABLE IF NOT EXISTS symbols USING fts5(
    path,
    symbol_name,
    symbol_type,
    line_start UNINDEXED,
    line_end   UNINDEXED,
    content,
    tokenize = 'porter unicode61'
);
"""


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def detect_language(path: Path) -> str:
    """Return a language tag for *path* based on its file extension.

    Args:
        path: Source file path.

    Returns:
        A lowercase language string (e.g. ``"python"``) or ``"unknown"``.
    """
    return _EXT_LANGUAGE.get(path.suffix.lower(), "unknown")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_file(lines: list[str], chunk_size: int = CHUNK_LINES) -> list[tuple[int, int, str]]:
    """Split *lines* into fixed-size blocks.

    Args:
        lines: All lines of the source file.
        chunk_size: Number of lines per chunk.

    Returns:
        List of ``(line_start, line_end, content)`` tuples (1-based line numbers).
    """
    chunks: list[tuple[int, int, str]] = []
    total = len(lines)
    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total)
        content = "".join(lines[start:end])
        chunks.append((start + 1, end, content))
    return chunks


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------


class CodebaseIndexer:
    """SQLite FTS5 indexer for a project codebase.

    Opens (or creates) the index database at ``<root>/.codenav/index.db``
    and provides methods to add, remove, and query indexed files.

    Example::

        indexer = CodebaseIndexer(root=Path("."))
        indexer.index_file(Path("navcode/cli.py"))
        results = indexer.search("typer app")
    """

    def __init__(self, root: Path) -> None:
        """Initialise the indexer.

        Args:
            root: Project root.  The database is stored at
                ``<root>/.codenav/index.db``.
        """
        self._root = root.resolve()
        self._db_path = self._root / DB_RELATIVE_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._connect()
        self._migrate()
        logger.debug("Indexer initialised (db={})", self._db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_file(self, path: Path) -> None:
        """Parse and index *path*, replacing any existing entry.

        Reads the file, detects its language, chunks it into 50-line
        blocks, and upserts the metadata + symbol rows.

        Args:
            path: Absolute or relative path to the file to index.
        """
        path = path.resolve()
        rel = self._rel(path)

        try:
            stat = path.stat()
        except OSError as exc:
            logger.warning("Cannot stat {} — skipping: {}", rel, exc)
            return

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read {} — skipping: {}", rel, exc)
            return

        language = detect_language(path)
        lines = text.splitlines(keepends=True)
        chunks = _chunk_file(lines)

        with self._conn:
            # Upsert file row
            self._conn.execute(
                """
                INSERT INTO files (path, language, last_modified, size)
                VALUES (:path, :lang, :mtime, :size)
                ON CONFLICT(path) DO UPDATE SET
                    language      = excluded.language,
                    last_modified = excluded.last_modified,
                    size          = excluded.size
                """,
                {
                    "path": rel,
                    "lang": language,
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                },
            )

            # Remove stale symbols then re-insert
            self._conn.execute("DELETE FROM symbols WHERE path = ?", (rel,))
            self._conn.executemany(
                """
                INSERT INTO symbols (path, symbol_name, symbol_type, line_start, line_end, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (rel, f"{rel}:{line_start}-{line_end}", "chunk", line_start, line_end, content)
                    for line_start, line_end, content in chunks
                ],
            )

        logger.debug("Indexed {} ({} chunks, lang={})", rel, len(chunks), language)

    def remove_file(self, path: Path) -> None:
        """Remove *path* and all its symbols from the index.

        Args:
            path: File to remove (absolute or relative).
        """
        rel = self._rel(path.resolve())
        with self._conn:
            self._conn.execute("DELETE FROM symbols WHERE path = ?", (rel,))
            self._conn.execute("DELETE FROM files WHERE path = ?", (rel,))
        logger.debug("Removed {} from index", rel)

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search across all indexed symbols.

        Args:
            query: FTS5 query string (plain text or FTS5 syntax).
            limit: Maximum number of results to return.

        Returns:
            List of result dicts with keys ``path``, ``symbol_name``,
            ``symbol_type``, ``line_start``, ``line_end``, ``content``,
            ``rank``.
        """
        cur = self._conn.execute(
            """
            SELECT path, symbol_name, symbol_type, line_start, line_end,
                   content, rank
            FROM symbols
            WHERE symbols MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_file_symbols(self, path: Path) -> list[dict[str, Any]]:
        """Return all symbol rows for *path*.

        Args:
            path: Source file (absolute or relative).

        Returns:
            List of row dicts ordered by ``line_start``.
        """
        rel = self._rel(path.resolve())
        cur = self._conn.execute(
            """
            SELECT path, symbol_name, symbol_type, line_start, line_end, content
            FROM symbols
            WHERE path = ?
            ORDER BY line_start
            """,
            (rel,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def is_indexed(self, path: Path) -> bool:
        """Return True if *path* has an entry in the files table.

        Args:
            path: File to check.
        """
        rel = self._rel(path.resolve())
        row = self._conn.execute(
            "SELECT 1 FROM files WHERE path = ? LIMIT 1", (rel,)
        ).fetchone()
        return row is not None

    def get_stats(self) -> dict[str, Any]:
        """Return a summary dict with ``file_count`` and ``symbol_count``.

        Returns:
            Dict with integer keys ``file_count`` and ``symbol_count``.
        """
        (file_count,) = self._conn.execute("SELECT COUNT(*) FROM files").fetchone()
        (symbol_count,) = self._conn.execute("SELECT COUNT(*) FROM symbols").fetchone()
        return {"file_count": file_count, "symbol_count": symbol_count}

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
        logger.debug("Indexer connection closed")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the SQLite connection with WAL mode for concurrent access."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self) -> None:
        """Create tables if they do not yet exist."""
        with self._conn:
            self._conn.execute(_DDL_FILES)
            self._conn.execute(_DDL_SYMBOLS)

    def _rel(self, abs_path: Path) -> str:
        """Return *abs_path* relative to project root as a POSIX string.

        Falls back to the absolute POSIX string if *abs_path* is outside root.
        """
        try:
            return abs_path.relative_to(self._root).as_posix()
        except ValueError:
            return abs_path.as_posix()
