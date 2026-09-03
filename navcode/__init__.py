from navcode._bootstrap import ensure_model
from loguru import logger
from pathlib import Path

__version__ = "0.1.0"

ensure_model()


def _setup_logging() -> None:
    log_dir = Path.cwd() / ".codenav"
    if log_dir.exists():
        logger.add(
            log_dir / "navcode.log",
            rotation="5 MB",
            retention="7 days",
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        )


_setup_logging()
