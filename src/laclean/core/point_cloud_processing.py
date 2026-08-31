"""Configuration and result models for the basic point-cloud pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class PointCloudProcessingError(RuntimeError):
    """User-facing processing configuration or execution error."""


@dataclass(frozen=True, slots=True)
class PointCloudProcessingOptions:
    """Ordered, serializable settings for the first processing pipeline."""

    voxel_enabled: bool = False
    voxel_size: float = 0.5
    statistical_enabled: bool = True
    statistical_neighbors: int = 20
    statistical_std_ratio: float = 2.0
    radius_enabled: bool = False
    radius_neighbors: int = 8
    radius: float = 2.0
    normals_enabled: bool = False
    normal_radius: float = 3.0
    normal_max_neighbors: int = 30

    @property
    def has_enabled_step(self) -> bool:
        return any(
            (
                self.voxel_enabled,
                self.statistical_enabled,
                self.radius_enabled,
                self.normals_enabled,
            )
        )

    def validate(self) -> None:
        if not self.has_enabled_step:
            raise PointCloudProcessingError("请至少启用一种点云处理算法。")
        if self.voxel_enabled and self.voxel_size <= 0:
            raise PointCloudProcessingError("体素尺寸必须大于 0。")
        if self.statistical_enabled:
            if self.statistical_neighbors < 2:
                raise PointCloudProcessingError("统计滤波的邻域点数不能小于 2。")
            if self.statistical_std_ratio <= 0:
                raise PointCloudProcessingError("统计滤波的标准差倍数必须大于 0。")
        if self.radius_enabled:
            if self.radius_neighbors < 1:
                raise PointCloudProcessingError("半径滤波的最少邻点数不能小于 1。")
            if self.radius <= 0:
                raise PointCloudProcessingError("半径滤波的搜索半径必须大于 0。")
        if self.normals_enabled:
            if self.normal_radius <= 0:
                raise PointCloudProcessingError("法线估计的搜索半径必须大于 0。")
            if self.normal_max_neighbors < 3:
                raise PointCloudProcessingError("法线估计的最大邻点数不能小于 3。")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProcessingStepSummary:
    name: str
    input_count: int
    output_count: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PointCloudProcessingSummary:
    input_count: int
    output_count: int
    elapsed_seconds: float
    steps: tuple[ProcessingStepSummary, ...]

    @property
    def removed_count(self) -> int:
        return self.input_count - self.output_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_count": self.input_count,
            "output_count": self.output_count,
            "removed_count": self.removed_count,
            "elapsed_seconds": self.elapsed_seconds,
            "steps": [step.to_dict() for step in self.steps],
        }
