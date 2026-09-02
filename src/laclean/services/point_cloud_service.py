"""Point-cloud import, project asset copying, and metadata extraction."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np

from laclean.core.error_handling import ensure_free_disk_space
from laclean.core.point_cloud import PointCloudData
from laclean.core.scene import NodeKind, SceneNode
from laclean.services.point_cloud_io import PointCloudIOError, read_point_cloud_file


SUPPORTED_POINT_CLOUD_SUFFIXES = {
    ".pcd",
    ".ply",
    ".xyz",
    ".xyzn",
    ".xyzrgb",
    ".pts",
}


class PointCloudError(RuntimeError):
    """User-facing point-cloud import or load error."""


@dataclass(slots=True)
class ImportedPointCloud:
    node: SceneNode
    data: PointCloudData


class PointCloudService:
    def import_to_project(
        self, source_path: str | Path, project_file_path: str | Path
    ) -> ImportedPointCloud:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise PointCloudError(f"点云文件不存在：\n{source}")
        if source.suffix.lower() not in SUPPORTED_POINT_CLOUD_SUFFIXES:
            raise PointCloudError(f"不支持的点云格式：{source.suffix or '<无扩展名>'}")

        node_id = uuid4()
        project_directory = Path(project_file_path).expanduser().resolve().parent
        asset_directory = project_directory / "assets" / "pointclouds" / str(node_id)
        asset_file = asset_directory / source.name

        try:
            ensure_free_disk_space(project_directory, source.stat().st_size)
        except OSError as exc:
            raise PointCloudError(f"项目磁盘空间不足：{exc}") from exc
        data = self._read_point_cloud(source, node_id=node_id, name=source.stem)
        try:
            asset_directory.mkdir(parents=True, exist_ok=False)
            shutil.copy2(source, asset_file)
        except OSError as exc:
            if asset_directory.exists():
                shutil.rmtree(asset_directory, ignore_errors=True)
            raise PointCloudError(f"复制点云到项目目录失败：{exc}") from exc

        relative_asset = asset_file.relative_to(project_directory).as_posix()
        display_points, _ = data.display_arrays()
        bounds_min = data.bounds_min.astype(float).tolist()
        bounds_max = data.bounds_max.astype(float).tolist()
        node = SceneNode(
            name=source.stem,
            kind=NodeKind.POINT_CLOUD,
            node_id=node_id,
            metadata={
                "asset": relative_asset,
                "source_name": source.name,
                "point_count": data.point_count,
                "display_point_count": int(len(display_points)),
                "has_colors": data.has_colors,
                "has_normals": data.has_normals,
                "invalid_points_removed": data.invalid_points_removed,
                "memory_bytes": data.memory_bytes,
                "unit": "mm",
                "bounds_min": bounds_min,
                "bounds_max": bounds_max,
                "transform": np.eye(4, dtype=float).tolist(),
                "point_size": 9.0,
                "coordinate_mode": "local",
            },
        )
        data.asset_path = asset_file
        return ImportedPointCloud(node=node, data=data)

    def load_project_asset(
        self, node: SceneNode, project_file_path: str | Path
    ) -> PointCloudData:
        if node.kind is not NodeKind.POINT_CLOUD:
            raise PointCloudError(f"节点“{node.name}”不是点云节点。")
        raw_asset = node.metadata.get("asset")
        if not isinstance(raw_asset, str) or not raw_asset:
            raise PointCloudError(f"点云“{node.name}”缺少项目资产路径。")

        project_directory = Path(project_file_path).expanduser().resolve().parent
        asset_path = (project_directory / Path(raw_asset)).resolve()
        if not asset_path.is_relative_to(project_directory):
            raise PointCloudError(f"点云“{node.name}”的资产路径越出了项目目录。")
        if not asset_path.is_file():
            raise PointCloudError(f"点云资产不存在：\n{asset_path}")

        data = self._read_point_cloud(asset_path, node.node_id, node.name)
        data.unit = str(node.metadata.get("unit", "mm"))
        return data

    def _read_point_cloud(self, path: Path, node_id, name: str) -> PointCloudData:
        try:
            return read_point_cloud_file(path, node_id, name)
        except MemoryError:
            raise
        except PointCloudIOError as exc:
            raise PointCloudError(f"读取点云失败：{exc}") from exc
