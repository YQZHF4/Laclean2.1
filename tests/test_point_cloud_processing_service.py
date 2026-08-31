from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from laclean.core.point_cloud import PointCloudData
from laclean.core.point_cloud_processing import (
    PointCloudProcessingError,
    PointCloudProcessingOptions,
)
from laclean.services.point_cloud_processing_service import (
    PointCloudProcessingService,
)
from laclean.services.point_cloud_service import PointCloudService
from laclean.services.project_service import ProjectService


def _cloud(tmp_path: Path, points: np.ndarray) -> PointCloudData:
    count = len(points)
    colors = np.tile(np.array([[40, 120, 220]], dtype=np.uint8), (count, 1))
    return PointCloudData(
        node_id=uuid4(),
        name="processing-sample",
        asset_path=tmp_path / "source.ply",
        points=np.asarray(points, dtype=np.float32),
        colors=colors,
    )


def test_processing_requires_at_least_one_enabled_step(tmp_path) -> None:
    data = _cloud(tmp_path, np.array([[0, 0, 0]], dtype=float))

    with pytest.raises(PointCloudProcessingError, match="至少启用"):
        PointCloudProcessingService().process(
            data,
            PointCloudProcessingOptions(
                statistical_enabled=False,
            ),
        )


def test_voxel_preview_is_non_destructive_and_preserves_color(tmp_path) -> None:
    points = np.array(
        [
            [0.00, 0.00, 0.00],
            [0.02, 0.01, 0.00],
            [1.00, 0.00, 0.00],
            [1.02, 0.01, 0.00],
        ]
    )
    data = _cloud(tmp_path, points)

    result = PointCloudProcessingService().process(
        data,
        PointCloudProcessingOptions(
            voxel_enabled=True,
            voxel_size=0.25,
            statistical_enabled=False,
        ),
    )

    assert data.point_count == 4
    assert result.data.point_count == 2
    assert result.data.has_colors is True
    assert result.summary.input_count == 4
    assert result.summary.output_count == 2
    assert result.summary.steps[0].name == "体素降采样"


def test_radius_filter_removes_isolated_point_and_estimates_normals(tmp_path) -> None:
    cluster = np.array(
        [[x, y, 0.0] for x in (0.0, 0.1, 0.2) for y in (0.0, 0.1, 0.2)]
    )
    points = np.vstack((cluster, [[10.0, 10.0, 10.0]]))
    data = _cloud(tmp_path, points)

    result = PointCloudProcessingService().process(
        data,
        PointCloudProcessingOptions(
            statistical_enabled=False,
            radius_enabled=True,
            radius_neighbors=2,
            radius=0.31,
            normals_enabled=True,
            normal_radius=0.4,
            normal_max_neighbors=20,
        ),
    )

    assert result.data.point_count == 9
    assert result.data.has_normals is True
    assert np.isfinite(result.data.normals).all()
    assert [step.name for step in result.summary.steps] == [
        "半径离群点滤波",
        "法线估计",
    ]


def test_applied_result_is_written_as_reloadable_project_asset(tmp_path) -> None:
    project = ProjectService().create_project("处理结果", tmp_path)
    data = _cloud(
        tmp_path,
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
    )

    persisted = PointCloudProcessingService().persist(data, project.file_path)
    assert persisted.asset_path.is_file()
    assert persisted.relative_asset.startswith(
        f"assets/pointclouds/{data.node_id}/processed_"
    )

    from laclean.core.scene import NodeKind, SceneNode

    node = SceneNode(
        data.name,
        NodeKind.POINT_CLOUD,
        node_id=data.node_id,
        metadata={"asset": persisted.relative_asset, "unit": "mm"},
    )
    restored = PointCloudService().load_project_asset(node, project.file_path)
    assert restored.point_count == data.point_count
    assert np.allclose(restored.points, data.points)
    assert np.array_equal(restored.colors, data.colors)


def test_streamed_binary_ply_preserves_normals_without_float64_source_copy(tmp_path) -> None:
    project = ProjectService().create_project("流式写入", tmp_path)
    points = np.arange(3000, dtype=np.float32).reshape(1000, 3) / 10.0
    data = _cloud(tmp_path, points)
    data.normals = np.tile(np.array([[0, 0, 1]], dtype=np.float32), (1000, 1))

    persisted = PointCloudProcessingService().persist(data, project.file_path)
    header = persisted.asset_path.read_bytes()[:256]
    assert b"format binary_little_endian 1.0" in header
    assert b"property float nx" in header

    from laclean.core.scene import NodeKind, SceneNode

    node = SceneNode(
        data.name,
        NodeKind.POINT_CLOUD,
        node_id=data.node_id,
        metadata={"asset": persisted.relative_asset, "unit": "mm"},
    )
    restored = PointCloudService().load_project_asset(node, project.file_path)
    assert np.allclose(restored.points, data.points)
    assert np.allclose(restored.normals, data.normals)
