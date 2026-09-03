"""File-system watcher for navcode.

Monitors a project root for file changes and notifies the indexer.
Runs on a background daemon thread using the watchdog library.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

if TYPE_CHECKING:
    from navcode.indexer import CodebaseIndexer

# ---------------------------------------------------------------------------
# Paths / patterns that are always ignored
# ---------------------------------------------------------------------------

IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".codenav",
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".egg-info",
    }
)

IGNORED_SUFFIXES: frozenset[str] = frozenset({".pyc", ".pyo"})

PID_FILE_NAME = ".codenav/watcher.pid"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_ignored(path: str) -> bool:
    """Return True if *path* should be skipped by the watcher."""
    parts = Path(path).parts
    for part in parts:
        if part in IGNORED_DIRS or part.endswith(".egg-info"):
            return True
    suffix = Path(path).suffix
    return suffix in IGNORED_SUFFIXES


# ---------------------------------------------------------------------------
# Watchdog event handler
# ---------------------------------------------------------------------------


class _NavcodeEventHandler(FileSystemEventHandler):
    """Watchdog event handler that forwards changes to the indexer."""

    def __init__(self, indexer: "CodebaseIndexer") -> None:
        """Initialise with a reference to the indexer."""
        super().__init__()
        self._indexer = indexer

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        """Index a newly created file."""
        if event.is_directory or _is_ignored(event.src_path):
            return
        logger.debug("File created: {}", event.src_path)
        self._indexer.index_file(Path(event.src_path))

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        """Re-index a modified file."""
        if event.is_directory or _is_ignored(event.src_path):
            return
        logger.debug("File modified: {}", event.src_path)
        self._indexer.index_file(Path(event.src_path))

    def on_deleted(self, event: FileDeletedEvent) -> None:  # type: ignore[override]
        """Remove a deleted file from the index."""
        if event.is_directory or _is_ignored(event.src_path):
            return
        logger.debug("File deleted: {}", event.src_path)
        self._indexer.remove_file(Path(event.src_path))

    def on_moved(self, event: FileMovedEvent) -> None:  # type: ignore[override]
        """Handle a file rename/move: remove old path, index new path."""
        if event.is_directory:
            return
        if not _is_ignored(event.src_path):
            logger.debug("File moved (src): {}", event.src_path)
            self._indexer.remove_file(Path(event.src_path))
        if not _is_ignored(event.dest_path):
            logger.debug("File moved (dest): {}", event.dest_path)
            self._indexer.index_file(Path(event.dest_path))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class CodebaseWatcher:
    """Background file-system watcher for a project directory.

    Uses watchdog to monitor *root* for changes and delegates all
    indexing operations to the supplied :class:`~navcode.indexer.CodebaseIndexer`.

    Example::

        watcher = CodebaseWatcher(root=Path("."), indexer=my_indexer)
        watcher.start()   # returns immediately; watcher runs in background
        ...
        watcher.stop()
    """

    def __init__(self, root: Path, indexer: "CodebaseIndexer") -> None:
        """Initialise the watcher.

        Args:
            root: Project root directory to watch recursively.
            indexer: Indexer instance that will handle file events.
        """
        self._root = root.resolve()
        self._indexer = indexer
        self._observer: Observer | None = None
        self._thread: threading.Thread | None = None
        self._pid_file = self._root / PID_FILE_NAME

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background watcher thread.

        Performs an initial full scan of *root*, then starts watchdog
        to process incremental changes.  The watcher PID is written to
        ``.codenav/watcher.pid`` so external processes can check liveness.
        """
        if self.is_running():
            logger.warning("Watcher already running (PID {})", self._read_pid())
            return

        logger.info("Starting watcher for {}", self._root)
        self._initial_scan()

        self._observer = Observer()
        handler = _NavcodeEventHandler(self._indexer)
        self._observer.schedule(handler, str(self._root), recursive=True)

        self._thread = threading.Thread(
            target=self._run_observer,
            name="navcode-watcher",
            daemon=True,
        )
        self._thread.start()
        self._write_pid()
        logger.info("Watcher started (PID {})", os.getpid())

    def stop(self) -> None:
        """Stop the background watcher and clean up the PID file."""
        if self._observer is not None:
            logger.info("Stopping watcher…")
            self._observer.stop()
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._observer = None
            self._thread = None

        self._remove_pid()
        logger.info("Watcher stopped")

    def is_running(self) -> bool:
        """Return True if a watcher process recorded in the PID file is alive.

        Checks the PID stored in ``.codenav/watcher.pid``; returns False if
        the file is absent, unreadable, or the PID is no longer active.
        """
        pid = self._read_pid()
        if pid is None:
            return False
        try:
            os.kill(pid, 0)  # signal 0 = existence check, no signal sent
            return True
        except (ProcessLookupError, PermissionError):
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _initial_scan(self) -> None:
        """Walk *root* and index every non-ignored file."""
        logger.info("Initial scan of {}", self._root)
        count = 0
        for file_path in self._root.rglob("*"):
            if file_path.is_file() and not _is_ignored(str(file_path)):
                self._indexer.index_file(file_path)
                count += 1
        logger.info("Initial scan complete — {} files indexed", count)

    def _run_observer(self) -> None:
        """Target for the background thread: start and join the observer."""
        assert self._observer is not None
        self._observer.start()
        try:
            self._observer.join()
        except Exception as exc:  # pragma: no cover
            logger.error("Watcher observer error: {}", exc)

    def _pid_path(self) -> Path:
        return self._pid_file

    def _write_pid(self) -> None:
        self._pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def _remove_pid(self) -> None:
        try:
            self._pid_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove PID file: {}", exc)

    def _read_pid(self) -> int | None:
        try:
            return int(self._pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
