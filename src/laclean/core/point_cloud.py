"""In-memory point-cloud data shared by algorithms and renderers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import numpy as np
from numpy.typing import NDArray


def _display_point_limit() -> int:
    try:
        value = int(os.environ.get("LACLEAN_DISPLAY_POINT_LIMIT", "180000"))
    except ValueError:
        value = 180_000
    return min(1_000_000, max(10_000, value))


DEFAULT_DISPLAY_POINT_LIMIT = _display_point_limit()


@dataclass(slots=True)
class PointCloudData:
    node_id: UUID
    name: str
    asset_path: Path
    points: NDArray[np.float32]
    colors: NDArray[np.uint8] | None = None
    normals: NDArray[np.float32] | None = None
    unit: str = "mm"
    invalid_points_removed: int = 0

    @property
    def point_count(self) -> int:
        return int(self.points.shape[0])

    @property
    def has_colors(self) -> bool:
        return self.colors is not None and len(self.colors) == self.point_count

    @property
    def has_normals(self) -> bool:
        return self.normals is not None and len(self.normals) == self.point_count

    @property
    def memory_bytes(self) -> int:
        """Memory owned by point attributes, excluding small Python object overhead."""

        return int(
            self.points.nbytes
            + (self.colors.nbytes if self.colors is not None else 0)
            + (self.normals.nbytes if self.normals is not None else 0)
        )

    @property
    def display_point_limit(self) -> int:
        """Adaptive OCC budget; pythonocc vertex upload is Python-call bound."""

        if self.point_count >= 10_000_000:
            return min(DEFAULT_DISPLAY_POINT_LIMIT, 100_000)
        if self.point_count >= 3_000_000:
            return min(DEFAULT_DISPLAY_POINT_LIMIT, 140_000)
        return DEFAULT_DISPLAY_POINT_LIMIT

    @property
    def bounds_min(self) -> NDArray[np.float32]:
        return self.points.min(axis=0)

    @property
    def bounds_max(self) -> NDArray[np.float32]:
        return self.points.max(axis=0)

    def display_arrays(
        self, max_points: int | None = None
    ) -> tuple[NDArray[np.float32], NDArray[np.uint8] | None]:
        """Return an evenly-strided display proxy without changing source data."""

        if max_points is None:
            max_points = self.display_point_limit
        max_points = max(1, int(max_points))
        if self.point_count <= max_points:
            return self.points, self.colors
        step = max(1, (self.point_count + max_points - 1) // max_points)
        colors = self.colors[::step] if self.colors is not None else None
        return self.points[::step], colors
