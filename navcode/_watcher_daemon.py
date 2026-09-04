"""navcode background watcher daemon.

This module is the entry point for the long-running watcher process.
It is invoked by :func:`navcode.watcher.start_daemon` as::

    python -m navcode._watcher_daemon <project_root>

The process:
1. Configures a file logger under ``.navcode/navcode.log``.
2. Writes its own PID to ``.navcode/watcher.pid``.
3. Runs the watchdog observer loop indefinitely, updating the index on
   every file change.
4. Cleans up the PID file on exit (SIGTERM / KeyboardInterrupt).
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from loguru import logger


def _setup_logging(codenav_dir: Path) -> None:
    logger.remove()  # silence stderr in the background process
    log_file = codenav_dir / "navcode.log"
    logger.add(
        str(log_file),
        rotation="5 MB",
        retention=3,
        level="DEBUG",
        enqueue=True,
    )


def main(root: Path) -> None:
    from navcode.indexer import CodebaseIndexer
    from navcode.watcher import CodebaseWatcher

    root = root.resolve()
    codenav_dir = root / ".navcode"
    codenav_dir.mkdir(parents=True, exist_ok=True)

    _setup_logging(codenav_dir)
    logger.info("Watcher daemon starting for {}", root)

    indexer = CodebaseIndexer(root)
    watcher = CodebaseWatcher(root, indexer)

    # Graceful shutdown on SIGTERM (POSIX) or CTRL_BREAK (Windows via SIGBREAK).
    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Watcher daemon received signal {}, shutting down…", signum)
        watcher.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    if hasattr(signal, "SIGBREAK"):  # Windows only
        signal.signal(signal.SIGBREAK, _shutdown)  # type: ignore[attr-defined]

    try:
        watcher.start()
        # Block the main thread so the process stays alive.
        watcher.join()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        logger.info("Watcher daemon exited cleanly")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m navcode._watcher_daemon <project_root>", file=sys.stderr)
        sys.exit(1)

    main(Path(sys.argv[1]))
