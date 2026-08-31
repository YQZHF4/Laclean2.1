"""Rotating application log and top-level exception hook."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Callable

from PyQt5.QtWidgets import QMessageBox, QWidget

from laclean.core.error_handling import LOGGER_NAME, user_error_message


def default_log_directory() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Laclean Studio" / "logs"
    return Path.home() / ".laclean" / "logs"


def configure_logging(log_directory: str | Path | None = None) -> Path | None:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if any(getattr(handler, "_laclean_handler", False) for handler in logger.handlers):
        handler = next(
            handler
            for handler in logger.handlers
            if getattr(handler, "_laclean_handler", False)
        )
        return Path(handler.baseFilename) if hasattr(handler, "baseFilename") else None

    directory = Path(log_directory) if log_directory is not None else default_log_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / "laclean.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
        log_path = None
    else:
        log_path = Path(handler.baseFilename)
    handler._laclean_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"
        )
    )
    logger.addHandler(handler)
    logger.info("Laclean Studio logging initialized")
    return log_path


def install_exception_hook(parent_provider: Callable[[], QWidget | None]) -> None:
    previous_hook = sys.excepthook

    def handle(
        exception_type: type[BaseException],
        error: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            previous_hook(exception_type, error, traceback)
            return
        logging.getLogger(LOGGER_NAME).critical(
            "Unhandled UI exception", exc_info=(exception_type, error, traceback)
        )
        try:
            QMessageBox.critical(
                parent_provider(),
                "未处理的程序异常",
                user_error_message("程序运行", error)
                + "\n\n详细信息已写入 Laclean 日志。",
            )
        except Exception:
            previous_hook(exception_type, error, traceback)

    sys.excepthook = handle
