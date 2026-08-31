"""PCL-backed point-cloud processing and project asset persistence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import numpy as np
import pcl

from laclean.core.point_cloud import PointCloudData
from laclean.core.error_handling import ensure_free_disk_space
from laclean.core.point_cloud_processing import (
    PointCloudProcessingError,
    PointCloudProcessingOptions,
    PointCloudProcessingSummary,
    ProcessingStepSummary,
)
from laclean.services.point_cloud_io import write_binary_ply


@dataclass(slots=True)
class ProcessedPointCloud:
    data: PointCloudData
    options: PointCloudProcessingOptions
    summary: PointCloudProcessingSummary


@dataclass(frozen=True, slots=True)
class PersistedPointCloud:
    relative_asset: str
    asset_path: Path


class PointCloudProcessingService:
    """Runs an ordered pipeline without modifying the input data object."""

    def process(
        self, data: PointCloudData, options: PointCloudProcessingOptions
    ) -> ProcessedPointCloud:
        options.validate()
        if data.point_count == 0:
            raise PointCloudProcessingError("点云为空，无法处理。")

        started = perf_counter()
        cloud = self._to_pcl(data)
        original_count = data.point_count
        steps: list[ProcessingStepSummary] = []

        if options.voxel_enabled:
            before = cloud.size
            voxel = cloud.make_voxel_grid_filter()
            leaf_size = float(options.voxel_size)
            voxel.set_leaf_size(leaf_size, leaf_size, leaf_size)
            cloud = voxel.filter()
            self._ensure_not_empty(cloud, "体素降采样")
            steps.append(
                ProcessingStepSummary(
                    "体素降采样",
                    before,
                    cloud.size,
                    f"体素 {options.voxel_size:g} {data.unit}",
                )
            )

        if options.statistical_enabled:
            before = cloud.size
            statistical = cloud.make_statistical_outlier_filter()
            statistical.set_mean_k(int(options.statistical_neighbors))
            statistical.set_std_dev_mul_thresh(float(options.statistical_std_ratio))
            cloud = statistical.filter()
            self._ensure_not_empty(cloud, "统计离群点滤波")
            steps.append(
                ProcessingStepSummary(
                    "统计离群点滤波",
                    before,
                    cloud.size,
                    f"邻点 {options.statistical_neighbors}，标准差 {options.statistical_std_ratio:g}",
                )
            )

        if options.radius_enabled:
            before = cloud.size
            filtered_points = _radius_outlier_filter(
                np.ascontiguousarray(cloud.to_array()[:, :3], dtype=np.float32),
                radius=float(options.radius),
                min_neighbors=int(options.radius_neighbors),
            )
            cloud = pcl.PointCloud(filtered_points)
            self._ensure_not_empty(cloud, "半径离群点滤波")
            steps.append(
                ProcessingStepSummary(
                    "半径离群点滤波",
                    before,
                    cloud.size,
                    f"半径 {options.radius:g} {data.unit}，最少邻点 {options.radius_neighbors}",
                )
            )

        normals = None
        if options.normals_enabled:
            before = cloud.size
            estimator = cloud.make_NormalEstimation()
            estimator.set_RadiusSearch(float(options.normal_radius))
            normals_array = np.asarray(estimator.compute().to_array(), dtype=np.float32)
            normals = np.ascontiguousarray(normals_array[:, :3], dtype=np.float32)
            lengths = np.linalg.norm(normals, axis=1)
            valid = lengths > 0
            normals[valid] /= lengths[valid, None]
            steps.append(
                ProcessingStepSummary(
                    "法线估计",
                    before,
                    cloud.size,
                    f"半径 {options.normal_radius:g} {data.unit}，最大邻点 {options.normal_max_neighbors}",
                )
            )

        result_data = self._from_pcl(cloud, data, normals=normals)
        summary = PointCloudProcessingSummary(
            input_count=original_count,
            output_count=result_data.point_count,
            elapsed_seconds=perf_counter() - started,
            steps=tuple(steps),
        )
        return ProcessedPointCloud(result_data, options, summary)

    def persist(
        self,
        data: PointCloudData,
        project_file_path: str | Path,
        *,
        filename_prefix: str = "processed",
    ) -> PersistedPointCloud:
        """Atomically write the applied result while retaining the imported source."""

        project_directory = Path(project_file_path).expanduser().resolve().parent
        asset_directory = project_directory / "assets" / "pointclouds" / str(data.node_id)
        safe_prefix = "cropped" if filename_prefix == "cropped" else "processed"
        file_name = f"{safe_prefix}_{uuid4().hex[:12]}.ply"
        asset_path = asset_directory / file_name
        temporary_path = asset_directory / f".{file_name}.pending.ply"
        try:
            asset_directory.mkdir(parents=True, exist_ok=True)
            estimated_size = data.point_count * (
                12 + (12 if data.has_normals else 0) + (3 if data.has_colors else 0)
            ) + 1024
            ensure_free_disk_space(asset_directory, estimated_size)
            write_binary_ply(temporary_path, data)
            with temporary_path.open("ab") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, asset_path)
        except (MemoryError, PermissionError):
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            if exc.errno == 28 or getattr(exc, "winerror", None) == 112:
                raise
            raise PointCloudProcessingError(f"保存处理后的点云失败：{exc}") from exc
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            raise PointCloudProcessingError(f"保存处理后的点云失败：{exc}") from exc

        return PersistedPointCloud(
            relative_asset=asset_path.relative_to(project_directory).as_posix(),
            asset_path=asset_path,
        )

    @staticmethod
    def _ensure_not_empty(cloud, step_name: str) -> None:
        if cloud.size == 0:
            raise PointCloudProcessingError(
                f"{step_name}移除了全部点，请放宽参数后重试。"
            )

    @staticmethod
    def _to_pcl(data: PointCloudData):
        return pcl.PointCloud(np.ascontiguousarray(data.points, dtype=np.float32))

    @staticmethod
    def _from_pcl(
        cloud, source: PointCloudData, *, normals: np.ndarray | None = None
    ) -> PointCloudData:
        points = np.ascontiguousarray(cloud.to_array()[:, :3], dtype=np.float32)
        colors = _nearest_source_colors(source.points, source.colors, points)
        return PointCloudData(
            node_id=source.node_id,
            name=source.name,
            asset_path=source.asset_path,
            points=points,
            colors=colors,
            normals=normals,
            unit=source.unit,
            invalid_points_removed=source.invalid_points_removed,
        )


def _nearest_source_colors(
    source_points: np.ndarray,
    source_colors: np.ndarray | None,
    result_points: np.ndarray,
    *,
    chunk_size: int = 25_000,
) -> np.ndarray | None:
    if source_colors is None or len(result_points) == 0:
        return None
    if len(source_points) * len(result_points) > 20_000_000:
        mean_color = np.rint(source_colors.astype(np.float32).mean(axis=0)).astype(np.uint8)
        return np.tile(mean_color, (len(result_points), 1))
    colors = np.empty((len(result_points), 3), dtype=np.uint8)
    source = np.ascontiguousarray(source_points, dtype=np.float32)
    for start in range(0, len(result_points), chunk_size):
        stop = min(start + chunk_size, len(result_points))
        delta = result_points[start:stop, None, :] - source[None, :, :]
        nearest = np.einsum("ijk,ijk->ij", delta, delta).argmin(axis=1)
        colors[start:stop] = source_colors[nearest]
    return colors


def _radius_outlier_filter(
    points: np.ndarray,
    *,
    radius: float,
    min_neighbors: int,
    max_pairs_per_chunk: int = 10_000_000,
) -> np.ndarray:
    radius_squared = np.float32(radius * radius)
    keep = np.zeros(len(points), dtype=bool)
    chunk_size = max(1, min(len(points), max_pairs_per_chunk // max(1, len(points))))
    for start in range(0, len(points), chunk_size):
        stop = min(start + chunk_size, len(points))
        delta = points[start:stop, None, :] - points[None, :, :]
        distances = np.einsum("ijk,ijk->ij", delta, delta)
        neighbor_counts = np.count_nonzero(distances <= radius_squared, axis=1) - 1
        keep[start:stop] = neighbor_counts >= min_neighbors
    return np.ascontiguousarray(points[keep], dtype=np.float32)
