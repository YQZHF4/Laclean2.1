import errno
import shutil

import pytest

from laclean.core.error_handling import (
    ensure_free_disk_space,
    format_bytes,
    user_error_message,
)


def test_common_resource_errors_have_actionable_messages() -> None:
    assert "内存不足" in user_error_message("处理点云", MemoryError())
    assert "磁盘剩余空间不足" in user_error_message(
        "保存点云", OSError(errno.ENOSPC, "disk full")
    )
    assert "访问权限" in user_error_message("读取项目", PermissionError())
    assert user_error_message("导入点云", RuntimeError("相机数据损坏")) == "相机数据损坏"


def test_disk_preflight_rejects_insufficient_space(tmp_path, monkeypatch) -> None:
    usage = shutil._ntuple_diskusage(total=1000, used=900, free=100)
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: usage)

    with pytest.raises(OSError) as error:
        ensure_free_disk_space(tmp_path, 200, reserve_bytes=0)

    assert error.value.errno == errno.ENOSPC


def test_format_bytes_is_readable() -> None:
    assert format_bytes(512) == "512 B"
    assert format_bytes(5 * 1024 * 1024) == "5.0 MB"
