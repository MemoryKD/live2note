"""Logging configuration using rich."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console(stderr=True)

_root_configured = False


def setup_logging(verbose: bool = False, log_file: Path | None = None) -> None:
    """Configure root logger with rich console output and optional file handler."""
    global _root_configured
    level = logging.DEBUG if verbose else logging.INFO

    handlers: list[logging.Handler] = [
        RichHandler(
            console=console,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
        )
    ]

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
        force=True,
    )
    _root_configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"live2note.{name}")


def get_task_logger(task_id: str, log_dir: Path) -> logging.Logger:
    """Return a logger that writes to both console and task log file."""
    logger = logging.getLogger(f"live2note.task.{task_id}")
    if not logger.handlers:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(
            log_dir / "task.log", encoding="utf-8"
        )
        fh.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        logger.addHandler(fh)
        logger.setLevel(logging.DEBUG)
    return logger
