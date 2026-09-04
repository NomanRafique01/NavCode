"""SQLite FTS5-backed codebase indexer for navcode.

Maintains three tables:
- ``files``      — one row per indexed source file (metadata).
- ``symbols``    — FTS5 virtual table of code chunks extracted from each file.
- ``embeddings`` — BLOB storage of float32 embedding vectors per symbol row.

The indexer performs basic 50-line chunking.  Proper AST-level symbol
extraction will be handled by ``parser.py`` in a later feature branch.
"""

from __future__ import annotations

import sqlite3
import concurrent.futures
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from loguru import logger

if TYPE_CHECKING:
    from navcode.embeddings import EmbeddingsEngine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_RELATIVE_PATH = ".navcode/index.db"
CHUNK_LINES = 50

# Extensions that are definitely binary — skip without reading
_BINARY_SUFFIXES: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".svg",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".avi", ".mov", ".mkv", ".webm",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".whl", ".egg",
    ".pyc", ".pyo", ".class",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".db", ".sqlite", ".sqlite3",
    ".bin", ".dat", ".o", ".a",
})

# Directory names to always skip
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".navcode", "__pycache__", "node_modules",
    ".venv", "venv", "env", "dist", "build",
    ".egg-info", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".cache",
})

# Parallel workers for file I/O (CPU-bound parsing stays single-threaded via DB lock)
_IO_WORKERS = 8

# Map file extension → language tag
_EXT_LANGUAGE: dict[str, str] = {
    # Python
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    # JavaScript
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    # TypeScript
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    # JSX / TSX
    ".jsx": "jsx",
    ".tsx": "tsx",
    # Java
    ".java": "java",
    # C
    ".c": "c",
    # C++ (note: .h/.hpp resolved to cpp; plain .h falls to c at parser level)
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".h": "c",
    # C#
    ".cs": "csharp",
    # Go
    ".go": "go",
    # Rust
    ".rs": "rust",
    # Ruby
    ".rb": "ruby",
    ".rake": "ruby",
    ".gemspec": "ruby",
    # PHP
    ".php": "php",
    ".phtml": "php",
    # Swift
    ".swift": "swift",
    # Kotlin
    ".kt": "kotlin",
    ".kts": "kotlin",
    # Scala
    ".scala": "scala",
    ".sc": "scala",
    # Haskell
    ".hs": "haskell",
    ".lhs": "haskell",
    # Lua
    ".lua": "lua",
    # R
    ".r": "r",
    ".R": "r",
    # Bash / shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "bash",
    # HTML
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    # CSS / preprocessors
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".less": "css",
    # JSON
    ".json": "json",
    ".jsonc": "json",
    # YAML
    ".yaml": "yaml",
    ".yml": "yaml",
    # TOML
    ".toml": "toml",
    # Markdown
    ".md": "markdown",
    ".mdx": "markdown",
    ".markdown": "markdown",
    # SQL
    ".sql": "sql",
    # Dockerfile handled separately (no extension)
    ".dockerfile": "dockerfile",
    # Regex
    ".regex": "regex",
    # XML / SVG
    ".xml": "xml",
    ".svg": "xml",
    # Plain text / logs / env
    ".txt": "text",
    ".log": "text",
    ".env": "text",
    # Config / INI
    ".ini": "config",
    ".cfg": "config",
    ".conf": "config",
    ".properties": "config",
}

# Special bare filenames → language (no extension)
_BARE_FILENAMES: dict[str, str] = {
    "dockerfile": "dockerfile",
    "Dockerfile": "dockerfile",
    "makefile": "bash",
    "Makefile": "bash",
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

_DDL_EMBEDDINGS = """
CREATE TABLE IF NOT EXISTS embeddings (
    id           INTEGER PRIMARY KEY,
    symbol_rowid INTEGER UNIQUE,
    embedding    BLOB NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def detect_language(path: Path) -> str:
    """Return a language tag for *path* based on its extension or bare filename.

    Checks the bare filename first (e.g. ``Dockerfile``), then falls back to
    the file extension.  Extension lookup is case-insensitive.

    Args:
        path: Source file path.

    Returns:
        A lowercase language string (e.g. ``"python"``) or ``"unknown"``.
    """
    # Bare filename check first (Dockerfile, Makefile, …)
    if path.name in _BARE_FILENAMES:
        return _BARE_FILENAMES[path.name]
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

    Opens (or creates) the index database at ``<root>/.navcode/index.db``
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
                ``<root>/.navcode/index.db``.
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

    @staticmethod
    def should_skip(path: Path) -> bool:
        """Return True if *path* should be excluded from indexing.

        Skips binary files by extension and paths inside ignored directories.
        """
        # Skip known binary extensions immediately
        if path.suffix.lower() in _BINARY_SUFFIXES:
            return True
        # Skip if any directory component is in the ignore list
        for part in path.parts:
            if part in _SKIP_DIRS or part.endswith(".egg-info"):
                return True
        return False

    def index_files_parallel(
        self,
        paths: list[Path],
        engine: "EmbeddingsEngine | None" = None,
        callback: "Any | None" = None,
    ) -> tuple[int, int]:
        """Index *paths* using a thread pool for fast parallel I/O.

        Reads are done concurrently; DB writes are serialised with a lock
        so SQLite stays consistent.

        Args:
            paths: List of file paths to index.
            engine: Optional embeddings engine (applied after DB write).
            callback: Optional zero-argument callable invoked after each file
                is processed (used to tick a progress bar).

        Returns:
            ``(indexed, failed)`` counts.
        """
        db_lock = threading.Lock()
        indexed = 0
        failed = 0
        counters_lock = threading.Lock()

        def _process(path: Path) -> None:
            nonlocal indexed, failed
            try:
                if self.should_skip(path):
                    return
                self._index_file_inner(path, engine, db_lock)
                with counters_lock:
                    indexed += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to index {}: {}", path, exc)
                with counters_lock:
                    failed += 1
            finally:
                if callback is not None:
                    callback()

        with concurrent.futures.ThreadPoolExecutor(max_workers=_IO_WORKERS) as pool:
            list(pool.map(_process, paths))

        return indexed, failed

    def index_file(self, path: Path, engine: "EmbeddingsEngine | None" = None) -> None:
        """Parse and index *path*, replacing any existing entry.

        Reads the file, detects its language, chunks it into 50-line
        blocks, and upserts the metadata + symbol rows.  If *engine* is
        provided, vector embeddings are stored alongside each symbol.

        Args:
            path: Absolute or relative path to the file to index.
            engine: Optional :class:`~navcode.embeddings.EmbeddingsEngine`
                instance.  When supplied, embeddings are computed and stored
                for every symbol.  Failures are logged and never propagate.
        """
        if self.should_skip(path):
            return
        self._index_file_inner(path, engine, threading.Lock())

    def _index_file_inner(
        self,
        path: Path,
        engine: "EmbeddingsEngine | None",
        db_lock: threading.Lock,
    ) -> None:
        """Core index logic shared by index_file and index_files_parallel."""
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

        symbol_rows_data = [
            (rel, f"{rel}:{line_start}-{line_end}", "chunk", line_start, line_end, content)
            for line_start, line_end, content in chunks
        ]

        # Serialise all DB writes with the caller-supplied lock so threads
        # don't interleave transactions on the single SQLite connection.
        with db_lock:
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

                # Remove stale symbols (and their embeddings) then re-insert
                self._conn.execute(
                    """
                    DELETE FROM embeddings
                    WHERE symbol_rowid IN (
                        SELECT rowid FROM symbols WHERE path = ?
                    )
                    """,
                    (rel,),
                )
                self._conn.execute("DELETE FROM symbols WHERE path = ?", (rel,))
                self._conn.executemany(
                    """
                    INSERT INTO symbols (path, symbol_name, symbol_type, line_start, line_end, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    symbol_rows_data,
                )

        # Embed symbols if an engine was supplied (outside lock — compute-heavy)
        if engine is not None:
            symbols_rows = self.get_file_symbols(path)
            for row in symbols_rows:
                symbol_name = row["symbol_name"]
                symbol_type = row["symbol_type"]
                content = row["content"]
                with db_lock:
                    cur = self._conn.execute(
                        "SELECT rowid FROM symbols WHERE path = ? AND symbol_name = ? LIMIT 1",
                        (rel, symbol_name),
                    )
                    result = cur.fetchone()
                if result is None:
                    continue
                symbol_rowid = result[0]
                embed_text = f"{symbol_name} {symbol_type} {content}"
                try:
                    embedding = engine.embed(embed_text)
                    self.store_embedding(symbol_rowid, embedding, _lock=db_lock)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Embedding failed for {} ({}): {}", rel, symbol_name, exc)

        logger.trace("Indexed {} ({} chunks, lang={})", rel, len(chunks), language)

    def remove_file(self, path: Path) -> None:
        """Remove *path* and all its symbols from the index.

        Args:
            path: File to remove (absolute or relative).
        """
        rel = self._rel(path.resolve())
        with self._conn:
            self._conn.execute(
                """
                DELETE FROM embeddings
                WHERE symbol_rowid IN (
                    SELECT rowid FROM symbols WHERE path = ?
                )
                """,
                (rel,),
            )
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

    def store_embedding(
        self,
        symbol_rowid: int,
        embedding: np.ndarray,
        _lock: "threading.Lock | None" = None,
    ) -> None:
        """Persist *embedding* for a symbol identified by its rowid.

        Args:
            symbol_rowid: ``rowid`` of the corresponding symbols row.
            embedding: Float32 array of shape ``(384,)``.
            _lock: Optional lock already held by the caller (e.g. from
                ``index_files_parallel``).  When provided the write is done
                inside that lock and no new transaction context is opened,
                avoiding nested-transaction errors on the shared connection.
        """
        blob = embedding.astype(np.float32).tobytes()
        sql = """
            INSERT INTO embeddings (symbol_rowid, embedding)
            VALUES (?, ?)
            ON CONFLICT(symbol_rowid) DO UPDATE SET embedding = excluded.embedding
        """
        if _lock is not None:
            # Caller already serialises DB access via this lock; execute
            # directly so we don't start a second transaction on the same conn.
            with _lock:
                self._conn.execute(sql, (symbol_rowid, blob))
                self._conn.commit()
        else:
            with self._conn:
                self._conn.execute(sql, (symbol_rowid, blob))

    def get_all_embeddings(self) -> tuple[np.ndarray, list[int]]:
        """Load all stored embeddings into memory.

        Returns:
            A tuple ``(matrix, rowids)`` where *matrix* has shape
            ``(N, 384)`` float32 and *rowids* is the corresponding list of
            symbol rowids.  Returns an empty matrix and list when no
            embeddings exist.
        """
        cur = self._conn.execute("SELECT symbol_rowid, embedding FROM embeddings")
        rows = cur.fetchall()
        if not rows:
            return np.empty((0, 384), dtype=np.float32), []
        rowids = [int(r[0]) for r in rows]
        matrix = np.vstack(
            [np.frombuffer(r[1], dtype=np.float32) for r in rows]
        ).astype(np.float32)
        return matrix, rowids

    def semantic_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Semantic similarity search over all stored embeddings.

        Embeds *query* with :class:`~navcode.embeddings.EmbeddingsEngine`,
        scores it against every stored vector, and returns the top results.

        Falls back gracefully when embeddings are unavailable.

        Args:
            query: Natural-language or code query string.
            limit: Maximum number of results.

        Returns:
            List of result dicts with keys ``path``, ``symbol_name``,
            ``symbol_type``, ``line_start``, ``line_end``, ``content``,
            ``language``, ``score``.
        """
        from navcode.embeddings import EmbeddingsEngine  # lazy import

        try:
            engine = EmbeddingsEngine()
        except Exception as exc:  # noqa: BLE001
            logger.warning("EmbeddingsEngine unavailable for semantic_search: {}", exc)
            return []

        matrix, rowids = self.get_all_embeddings()
        if len(rowids) == 0:
            return []

        query_vec = engine.embed(query)
        top = EmbeddingsEngine.top_k(query_vec, matrix, k=limit)

        results: list[dict[str, Any]] = []
        for idx, score in top:
            rowid = rowids[idx]
            row = self._conn.execute(
                """
                SELECT s.path, s.symbol_name, s.symbol_type,
                       s.line_start, s.line_end, s.content,
                       f.language
                FROM symbols AS s
                JOIN files   AS f ON f.path = s.path
                WHERE s.rowid = ?
                """,
                (rowid,),
            ).fetchone()
            if row is None:
                continue
            results.append(
                {
                    "path": row[0],
                    "symbol_name": row[1],
                    "symbol_type": row[2],
                    "line_start": row[3],
                    "line_end": row[4],
                    "content": row[5],
                    "language": row[6],
                    "score": score,
                }
            )
        return results

    def hybrid_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Combined semantic + FTS5 search.

        Runs both searches, normalises their scores, then merges by
        deduplicating on ``(path, line_start)``.  Semantic results are
        weighted 0.7 and FTS5 results are weighted 0.3.

        Args:
            query: Search query.
            limit: Maximum number of results to return.

        Returns:
            List of result dicts (same shape as :meth:`search`) sorted by
            combined score descending.
        """
        # Semantic results (may be empty if model unavailable)
        sem_results = self.semantic_search(query, limit=limit * 2)

        # FTS5 results — guard against invalid FTS5 query syntax
        try:
            fts_results_raw = self.search(query, limit=limit * 2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FTS5 search failed in hybrid_search: {}", exc)
            fts_results_raw = []

        # Normalise FTS5 rank: rank is negative (lower = better), convert to 0-1
        if fts_results_raw:
            ranks = [abs(r["rank"]) for r in fts_results_raw]
            max_rank = max(ranks) or 1.0
            for r in fts_results_raw:
                r["fts_score"] = 1.0 - abs(r["rank"]) / max_rank
        else:
            for r in fts_results_raw:
                r["fts_score"] = 0.0

        # Build merged dict keyed by (path, line_start)
        merged: dict[tuple[str, int], dict[str, Any]] = {}

        for r in sem_results:
            key = (r["path"], r["line_start"])
            merged[key] = {**r, "combined_score": r["score"] * 0.7}

        for r in fts_results_raw:
            key = (r["path"], r["line_start"])
            fts_contrib = r["fts_score"] * 0.3
            if key in merged:
                merged[key]["combined_score"] += fts_contrib
            else:
                merged[key] = {
                    "path": r["path"],
                    "symbol_name": r["symbol_name"],
                    "symbol_type": r["symbol_type"],
                    "line_start": r["line_start"],
                    "line_end": r["line_end"],
                    "content": r["content"],
                    "language": r.get("language", "unknown"),
                    "score": fts_contrib,
                    "combined_score": fts_contrib,
                }

        sorted_results = sorted(
            merged.values(), key=lambda x: x["combined_score"], reverse=True
        )
        return sorted_results[:limit]

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
        """Open the SQLite connection with WAL + performance PRAGMAs."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-32768")   # 32 MB page cache
        conn.execute("PRAGMA mmap_size=268435456") # 256 MB mmap
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self) -> None:
        """Create tables if they do not yet exist."""
        with self._conn:
            self._conn.execute(_DDL_FILES)
            self._conn.execute(_DDL_SYMBOLS)
            self._conn.execute(_DDL_EMBEDDINGS)

    def _rel(self, abs_path: Path) -> str:
        """Return *abs_path* relative to project root as a POSIX string.

        Falls back to the absolute POSIX string if *abs_path* is outside root.
        """
        try:
            return abs_path.relative_to(self._root).as_posix()
        except ValueError:
            return abs_path.as_posix()
