"""Consistent logging and user-facing messages for unexpected failures."""

from __future__ import annotations

import errno
import logging
from pathlib import Path


LOGGER_NAME = "laclean"


def user_error_message(operation: str, error: BaseException) -> str:
    """Translate low-level failures into concise, actionable Chinese messages."""

    prefix = f"{operation}失败"
    if isinstance(error, MemoryError):
        return (
            f"{prefix}：可用内存不足。请关闭其他大型程序、减小点云规模，"
            "或先使用体素降采样。"
        )
    if isinstance(error, PermissionError):
        return f"{prefix}：没有文件访问权限。请检查项目目录是否只读或被其他程序占用。"
    if isinstance(error, OSError) and (
        error.errno == errno.ENOSPC or getattr(error, "winerror", None) == 112
    ):
        return f"{prefix}：磁盘剩余空间不足。请释放项目所在磁盘空间后重试。"

    detail = str(error).strip()
    if not detail:
        detail = type(error).__name__
    if detail.startswith(prefix) or detail.startswith(operation):
        return detail
    return detail


def log_exception(operation: str, error: BaseException) -> str:
    """Log the current exception traceback and return its user-facing message."""

    logging.getLogger(LOGGER_NAME).exception("%s failed", operation, exc_info=error)
    return user_error_message(operation, error)


def format_bytes(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def ensure_free_disk_space(
    target_directory: str | Path,
    required_bytes: int,
    *,
    reserve_bytes: int = 64 * 1024 * 1024,
) -> None:
    """Raise ENOSPC before a large copy/write leaves a partial project asset."""

    import shutil

    directory = Path(target_directory)
    probe = directory
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = int(shutil.disk_usage(probe).free)
    required = max(0, int(required_bytes)) + max(0, int(reserve_bytes))
    if free < required:
        raise OSError(
            errno.ENOSPC,
            f"磁盘可用空间 {format_bytes(free)}，至少需要 {format_bytes(required)}",
        )
