"""File-system watcher for navcode.

Monitors a project root for file changes and notifies the indexer.
The watcher runs as a completely separate background process (daemon) so
it survives after the ``navcode init`` command exits.

Public helpers
--------------
start_daemon(root)   – Launch the watcher daemon process and return its PID.
stop_daemon(root)    – Kill the running daemon and remove the PID file.
is_daemon_running(root) – Return True if the PID file exists and the process is alive.

The actual long-running loop lives in :mod:`navcode._watcher_daemon` which is
invoked as ``python -m navcode._watcher_daemon <root>``.

The :class:`CodebaseWatcher` class is kept for use *inside* the daemon process
itself (and for tests).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
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
        ".navcode",
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

PID_FILE_NAME = ".navcode/watcher.pid"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pid_path(root: Path) -> Path:
    return root.resolve() / PID_FILE_NAME


def _read_pid(root: Path) -> int | None:
    try:
        return int(_pid_path(root).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _is_ignored(path: str) -> bool:
    """Return True if *path* should be skipped by the watcher."""
    parts = Path(path).parts
    for part in parts:
        if part in IGNORED_DIRS or part.endswith(".egg-info"):
            return True
    suffix = Path(path).suffix
    return suffix in IGNORED_SUFFIXES


# ---------------------------------------------------------------------------
# Public daemon management API
# ---------------------------------------------------------------------------


def is_daemon_running(root: Path) -> bool:
    """Return True if the watcher daemon recorded in the PID file is alive."""
    pid = _read_pid(root)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)  # signal 0 = existence check, no signal sent
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def start_daemon(root: Path) -> int:
    """Launch the watcher as a detached background process and return its PID.

    On Windows the ``DETACHED_PROCESS`` creation flag is used so the child
    is completely decoupled from the parent console.  On POSIX
    ``start_new_session=True`` achieves the same result.

    The daemon writes its own PID to ``.navcode/watcher.pid`` once it is
    ready, so callers should not read the PID file immediately; use
    :func:`is_daemon_running` to poll liveness instead.
    """
    root = root.resolve()

    # Ensure the .navcode directory exists so the daemon can write its PID.
    (root / ".navcode").mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, "-m", "navcode._watcher_daemon", str(root)]

    if sys.platform == "win32":
        # DETACHED_PROCESS (0x00000008) + CREATE_NEW_PROCESS_GROUP (0x00000200)
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        proc = subprocess.Popen(
            cmd,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            start_new_session=True,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return proc.pid


def stop_daemon(root: Path) -> bool:
    """Kill the running watcher daemon.

    Returns True if a process was killed, False if no daemon was running.
    The PID file is removed regardless.
    """
    root = root.resolve()
    pid = _read_pid(root)
    killed = False

    if pid is not None:
        try:
            if sys.platform == "win32":
                subprocess.call(
                    ["taskkill", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                os.kill(pid, signal.SIGTERM)
            killed = True
        except (ProcessLookupError, OSError):
            pass  # process already gone

    pid_file = _pid_path(root)
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass

    return killed


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
# CodebaseWatcher — used inside the daemon process
# ---------------------------------------------------------------------------


class CodebaseWatcher:
    """In-process file-system watcher (used by the daemon).

    For background daemon management from the CLI use :func:`start_daemon`,
    :func:`stop_daemon`, and :func:`is_daemon_running` instead.

    Example::

        watcher = CodebaseWatcher(root=Path("."), indexer=my_indexer)
        watcher.start()   # returns immediately; watcher runs in background thread
        ...
        watcher.stop()
    """

    def __init__(self, root: Path, indexer: "CodebaseIndexer") -> None:
        self._root = root.resolve()
        self._indexer = indexer
        self._observer: Observer | None = None
        self._thread: threading.Thread | None = None
        self._pid_file = _pid_path(root)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background watcher thread and write the PID file."""
        logger.info("Starting watcher for {}", self._root)
        self._initial_scan()

        self._observer = Observer()
        handler = _NavcodeEventHandler(self._indexer)
        self._observer.schedule(handler, str(self._root), recursive=True)

        self._thread = threading.Thread(
            target=self._run_observer,
            name="navcode-watcher",
            daemon=False,  # keep the process alive
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

    def join(self) -> None:
        """Block until the observer thread exits (used by the daemon)."""
        if self._thread is not None:
            self._thread.join()

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

    def _write_pid(self) -> None:
        self._pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def _remove_pid(self) -> None:
        try:
            self._pid_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove PID file: {}", exc)
