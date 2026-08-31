from pathlib import Path

import numpy as np
import pytest

from laclean.core.scene import NodeKind, SceneNode
from laclean.services.point_cloud_service import PointCloudError, PointCloudService
from laclean.services.project_service import ProjectService


PLY_CONTENT = """ply
format ascii 1.0
element vertex 5
property float x
property float y
property float z
property uchar red
property uchar green
property uchar blue
end_header
0 0 0 255 0 0
10 0 0 0 255 0
0 20 0 0 0 255
0 0 30 255 255 0
10 20 30 255 255 255
"""


def _write_sample_cloud(path: Path) -> None:
    path.write_text(PLY_CONTENT, encoding="ascii")


def test_import_copies_cloud_and_extracts_properties(tmp_path) -> None:
    project = ProjectService().create_project("点云项目", tmp_path)
    source = tmp_path / "彩色样本.ply"
    _write_sample_cloud(source)

    result = PointCloudService().import_to_project(source, project.file_path)

    assert result.node.kind is NodeKind.POINT_CLOUD
    assert result.node.name == "彩色样本"
    assert result.data.point_count == 5
    assert result.data.has_colors is True
    assert result.data.has_normals is False
    assert np.allclose(result.data.bounds_min, [0, 0, 0])
    assert np.allclose(result.data.bounds_max, [10, 20, 30])
    assert result.node.metadata["point_count"] == 5
    assert result.node.metadata["unit"] == "mm"

    copied = tmp_path / "点云项目" / result.node.metadata["asset"]
    assert copied.is_file()
    assert copied.read_bytes() == source.read_bytes()

    restored = PointCloudService().load_project_asset(result.node, project.file_path)
    assert restored.node_id == result.node.node_id
    assert np.array_equal(restored.points, result.data.points)
    assert np.array_equal(restored.colors, result.data.colors)


def test_project_asset_cannot_escape_project_directory(tmp_path) -> None:
    project = ProjectService().create_project("安全项目", tmp_path)
    outside = tmp_path / "outside.ply"
    _write_sample_cloud(outside)
    node = SceneNode(
        "越界点云",
        NodeKind.POINT_CLOUD,
        metadata={"asset": "../outside.ply"},
    )

    with pytest.raises(PointCloudError, match="越出了项目目录"):
        PointCloudService().load_project_asset(node, project.file_path)


def test_display_proxy_keeps_full_data(tmp_path) -> None:
    project = ProjectService().create_project("代理项目", tmp_path)
    source = tmp_path / "sample.ply"
    _write_sample_cloud(source)
    data = PointCloudService().import_to_project(source, project.file_path).data

    display_points, display_colors = data.display_arrays(max_points=3)
    assert len(display_points) <= 3
    assert len(display_colors) == len(display_points)
    assert data.point_count == 5


def test_corrupt_and_all_invalid_point_clouds_are_rejected(tmp_path) -> None:
    project = ProjectService().create_project("异常点云", tmp_path)
    corrupt = tmp_path / "corrupt.ply"
    corrupt.write_bytes(b"this is not a ply file")

    with pytest.raises(PointCloudError, match="没有可用的三维点|读取点云失败"):
        PointCloudService().import_to_project(corrupt, project.file_path)

    invalid = tmp_path / "invalid.xyz"
    invalid.write_text("nan nan nan\ninf 0 0\n", encoding="ascii")
    with pytest.raises(PointCloudError, match="全部为无效数值|没有可用的三维点"):
        PointCloudService().import_to_project(invalid, project.file_path)
