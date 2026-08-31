"""Open3D-backed point-cloud processing and project asset persistence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import numpy as np
import open3d as o3d

from laclean.core.point_cloud import PointCloudData
from laclean.core.error_handling import ensure_free_disk_space
from laclean.core.point_cloud_processing import (
    PointCloudProcessingError,
    PointCloudProcessingOptions,
    PointCloudProcessingSummary,
    ProcessingStepSummary,
)


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
        cloud = self._to_open3d(data)
        original_count = data.point_count
        steps: list[ProcessingStepSummary] = []

        if options.voxel_enabled:
            before = len(cloud.points)
            cloud = cloud.voxel_down_sample(float(options.voxel_size))
            self._ensure_not_empty(cloud, "体素降采样")
            steps.append(
                ProcessingStepSummary(
                    "体素降采样",
                    before,
                    len(cloud.points),
                    f"体素 {options.voxel_size:g} {data.unit}",
                )
            )

        if options.statistical_enabled:
            before = len(cloud.points)
            cloud, _ = cloud.remove_statistical_outlier(
                nb_neighbors=int(options.statistical_neighbors),
                std_ratio=float(options.statistical_std_ratio),
            )
            self._ensure_not_empty(cloud, "统计离群点滤波")
            steps.append(
                ProcessingStepSummary(
                    "统计离群点滤波",
                    before,
                    len(cloud.points),
                    f"邻点 {options.statistical_neighbors}，标准差 {options.statistical_std_ratio:g}",
                )
            )

        if options.radius_enabled:
            before = len(cloud.points)
            cloud, _ = cloud.remove_radius_outlier(
                nb_points=int(options.radius_neighbors),
                radius=float(options.radius),
            )
            self._ensure_not_empty(cloud, "半径离群点滤波")
            steps.append(
                ProcessingStepSummary(
                    "半径离群点滤波",
                    before,
                    len(cloud.points),
                    f"半径 {options.radius:g} {data.unit}，最少邻点 {options.radius_neighbors}",
                )
            )

        if options.normals_enabled:
            before = len(cloud.points)
            cloud.estimate_normals(
                search_param=o3d.geometry.KDTreeSearchParamHybrid(
                    radius=float(options.normal_radius),
                    max_nn=int(options.normal_max_neighbors),
                )
            )
            cloud.normalize_normals()
            steps.append(
                ProcessingStepSummary(
                    "法线估计",
                    before,
                    len(cloud.points),
                    f"半径 {options.normal_radius:g} {data.unit}，最大邻点 {options.normal_max_neighbors}",
                )
            )

        result_data = self._from_open3d(cloud, data)
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
            self._write_binary_ply(temporary_path, data)
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
    def _write_binary_ply(
        path: Path, data: PointCloudData, *, chunk_size: int = 250_000
    ) -> None:
        """Stream a compact binary PLY without creating Open3D float64 copies."""

        fields: list[tuple[str, str]] = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
        header_properties = ["property float x", "property float y", "property float z"]
        if data.has_normals:
            fields.extend((("nx", "<f4"), ("ny", "<f4"), ("nz", "<f4")))
            header_properties.extend(
                ("property float nx", "property float ny", "property float nz")
            )
        if data.has_colors:
            fields.extend((("red", "u1"), ("green", "u1"), ("blue", "u1")))
            header_properties.extend(
                ("property uchar red", "property uchar green", "property uchar blue")
            )
        dtype = np.dtype(fields, align=False)
        header = (
            "ply\n"
            "format binary_little_endian 1.0\n"
            "comment generated by Laclean Studio\n"
            f"element vertex {data.point_count}\n"
            + "\n".join(header_properties)
            + "\nend_header\n"
        ).encode("ascii")

        with path.open("wb") as stream:
            stream.write(header)
            size = max(1, int(chunk_size))
            for start in range(0, data.point_count, size):
                stop = min(start + size, data.point_count)
                records = np.empty(stop - start, dtype=dtype)
                points = data.points[start:stop]
                records["x"], records["y"], records["z"] = points.T
                if data.has_normals:
                    normals = data.normals[start:stop]
                    records["nx"], records["ny"], records["nz"] = normals.T
                if data.has_colors:
                    colors = data.colors[start:stop]
                    records["red"], records["green"], records["blue"] = colors.T
                stream.write(records.tobytes(order="C"))
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _ensure_not_empty(cloud: o3d.geometry.PointCloud, step_name: str) -> None:
        if len(cloud.points) == 0:
            raise PointCloudProcessingError(
                f"{step_name}移除了全部点，请放宽参数后重试。"
            )

    @staticmethod
    def _to_open3d(data: PointCloudData) -> o3d.geometry.PointCloud:
        cloud = o3d.geometry.PointCloud()
        cloud.points = o3d.utility.Vector3dVector(
            np.ascontiguousarray(data.points, dtype=np.float64)
        )
        if data.has_colors:
            cloud.colors = o3d.utility.Vector3dVector(
                np.ascontiguousarray(data.colors, dtype=np.float64) / 255.0
            )
        if data.has_normals:
            cloud.normals = o3d.utility.Vector3dVector(
                np.ascontiguousarray(data.normals, dtype=np.float64)
            )
        return cloud

    @staticmethod
    def _from_open3d(
        cloud: o3d.geometry.PointCloud, source: PointCloudData
    ) -> PointCloudData:
        points = np.ascontiguousarray(np.asarray(cloud.points), dtype=np.float32)
        colors = None
        if cloud.has_colors():
            colors = np.ascontiguousarray(
                np.rint(np.clip(np.asarray(cloud.colors), 0.0, 1.0) * 255.0),
                dtype=np.uint8,
            )
        normals = None
        if cloud.has_normals():
            normals = np.ascontiguousarray(np.asarray(cloud.normals), dtype=np.float32)
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
