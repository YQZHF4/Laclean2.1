"""Point-level rectangle selection, cropping, and reversible edit commands."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from laclean.core.point_cloud import PointCloudData
from laclean.core.scene import SceneNode


class PointCloudEditingError(RuntimeError):
    """User-facing point-cloud selection or crop error."""


@dataclass(slots=True)
class RectangleSelection:
    mask: NDArray[np.bool_]
    selected_count: int
    total_count: int


@dataclass(slots=True)
class CroppedPointCloud:
    data: PointCloudData
    input_count: int
    selected_count: int
    kept_count: int
    mode: str


def select_points_in_screen_rectangle(
    data: PointCloudData,
    rectangle: tuple[int, int, int, int],
    view_projection: object,
    viewport_size: tuple[int, int],
    model_transform: object | None = None,
    *,
    chunk_size: int = 250_000,
) -> RectangleSelection:
    """Select every point projected inside a screen rectangle, ignoring occlusion."""

    x1, y1, x2, y2 = rectangle
    left, right = sorted((float(x1), float(x2)))
    top, bottom = sorted((float(y1), float(y2)))
    width, height = viewport_size
    if right - left < 2 or bottom - top < 2:
        raise PointCloudEditingError("框选矩形太小，请重新拖动。")
    if width <= 0 or height <= 0:
        raise PointCloudEditingError("三维视图尺寸无效。")

    vp = _matrix4(view_projection, "视图投影矩阵")
    model = np.eye(4, dtype=np.float32)
    if model_transform is not None:
        model = _matrix4(model_transform, "点云变换矩阵")
    combined = np.asarray(vp @ model, dtype=np.float32)
    mask = np.zeros(data.point_count, dtype=np.bool_)

    for start in range(0, data.point_count, max(1, int(chunk_size))):
        stop = min(start + max(1, int(chunk_size)), data.point_count)
        points = np.asarray(data.points[start:stop], dtype=np.float32)
        # Affine multiplication without allocating an N×4 homogeneous input.
        clip = points @ combined[:, :3].T
        clip += combined[:, 3]
        w = clip[:, 3]
        valid = np.isfinite(clip).all(axis=1) & (np.abs(w) > 1.0e-12)
        inverse_w = np.zeros_like(w)
        np.divide(1.0, w, out=inverse_w, where=valid)
        ndc_x = clip[:, 0] * inverse_w
        ndc_y = clip[:, 1] * inverse_w
        ndc_z = clip[:, 2] * inverse_w

        # The depth check only excludes points outside the camera clipping range.
        # No z-buffer/visibility test is performed, so points hidden behind the
        # surface remain selected (the requested through-selection behavior).
        valid &= (ndc_z >= -1.000001) & (ndc_z <= 1.000001)
        screen_x = (ndc_x + 1.0) * (0.5 * float(width))
        screen_y = (1.0 - ndc_y) * (0.5 * float(height))
        mask[start:stop] = (
            valid
            & (screen_x >= left)
            & (screen_x <= right)
            & (screen_y >= top)
            & (screen_y <= bottom)
        )

    return RectangleSelection(mask, int(np.count_nonzero(mask)), data.point_count)


def crop_point_cloud(
    data: PointCloudData, selection: RectangleSelection, *, keep_selected: bool
) -> CroppedPointCloud:
    if selection.total_count != data.point_count or len(selection.mask) != data.point_count:
        raise PointCloudEditingError("框选结果与当前点云不匹配，请重新框选。")
    keep_mask = selection.mask if keep_selected else ~selection.mask
    kept_count = int(np.count_nonzero(keep_mask))
    if kept_count == 0:
        action = "保留框内" if keep_selected else "删除框内"
        raise PointCloudEditingError(f"“{action}”会得到空点云，请重新框选。")

    colors = (
        np.ascontiguousarray(data.colors[keep_mask]) if data.colors is not None else None
    )
    normals = (
        np.ascontiguousarray(data.normals[keep_mask]) if data.normals is not None else None
    )
    result = PointCloudData(
        node_id=data.node_id,
        name=data.name,
        asset_path=data.asset_path,
        points=np.ascontiguousarray(data.points[keep_mask]),
        colors=colors,
        normals=normals,
        unit=data.unit,
        invalid_points_removed=data.invalid_points_removed,
    )
    return CroppedPointCloud(
        data=result,
        input_count=data.point_count,
        selected_count=selection.selected_count,
        kept_count=kept_count,
        mode="keep" if keep_selected else "delete",
    )


CLOUD_EDIT_METADATA_KEYS = (
    "asset",
    "original_asset",
    "point_count",
    "display_point_count",
    "has_colors",
    "has_normals",
    "bounds_min",
    "bounds_max",
    "memory_bytes",
    "processing_history",
    "crop_history",
)


@dataclass(slots=True)
class PointCloudEditState:
    data: PointCloudData
    metadata: dict[str, Any]

    @classmethod
    def capture(cls, node: SceneNode, data: PointCloudData) -> "PointCloudEditState":
        return cls(
            data=data,
            metadata={
                key: deepcopy(node.metadata[key])
                for key in CLOUD_EDIT_METADATA_KEYS
                if key in node.metadata
            },
        )


@dataclass(slots=True)
class PointCloudEditCommand:
    node_id: UUID
    text: str
    before: PointCloudEditState
    after: PointCloudEditState


class EditCommandHistory:
    """Small application-level undo stack for immutable point-cloud states."""

    def __init__(self, limit: int = 20, max_memory_bytes: int = 768 * 1024 * 1024) -> None:
        self.limit = max(1, int(limit))
        self.max_memory_bytes = max(1, int(max_memory_bytes))
        self._undo: list[PointCloudEditCommand] = []
        self._redo: list[PointCloudEditCommand] = []

    @property
    def undo_text(self) -> str:
        return self._undo[-1].text if self._undo else ""

    @property
    def redo_text(self) -> str:
        return self._redo[-1].text if self._redo else ""

    @property
    def memory_bytes(self) -> int:
        unique_data: dict[int, PointCloudData] = {}
        for command in (*self._undo, *self._redo):
            unique_data[id(command.before.data)] = command.before.data
            unique_data[id(command.after.data)] = command.after.data
        return sum(data.memory_bytes for data in unique_data.values())

    def push(self, command: PointCloudEditCommand) -> int:
        self._undo.append(command)
        self._redo.clear()
        removed = 0
        if len(self._undo) > self.limit:
            del self._undo[0]
            removed += 1
        # Keep the newest command even when a single before/after pair exceeds
        # the budget; otherwise Ctrl+Z would silently become unavailable.
        while len(self._undo) > 1 and self.memory_bytes > self.max_memory_bytes:
            del self._undo[0]
            removed += 1
        return removed

    def undo(self) -> PointCloudEditCommand | None:
        if not self._undo:
            return None
        command = self._undo.pop()
        self._redo.append(command)
        return command

    def redo(self) -> PointCloudEditCommand | None:
        if not self._redo:
            return None
        command = self._redo.pop()
        self._undo.append(command)
        return command

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


def apply_edit_state(node: SceneNode, state: PointCloudEditState) -> None:
    for key in CLOUD_EDIT_METADATA_KEYS:
        node.metadata.pop(key, None)
    node.metadata.update(deepcopy(state.metadata))


def metadata_for_cropped_data(
    node: SceneNode,
    cropped: CroppedPointCloud,
    relative_asset: str,
    applied_at: str,
) -> dict[str, Any]:
    metadata = deepcopy(node.metadata)
    metadata.setdefault("original_asset", metadata.get("asset"))
    metadata["asset"] = relative_asset
    metadata["point_count"] = cropped.data.point_count
    metadata["display_point_count"] = len(cropped.data.display_arrays()[0])
    metadata["has_colors"] = cropped.data.has_colors
    metadata["has_normals"] = cropped.data.has_normals
    metadata["bounds_min"] = cropped.data.bounds_min.astype(float).tolist()
    metadata["bounds_max"] = cropped.data.bounds_max.astype(float).tolist()
    metadata["memory_bytes"] = cropped.data.memory_bytes
    history = metadata.setdefault("crop_history", [])
    if not isinstance(history, list):
        history = []
        metadata["crop_history"] = history
    history.append(
        {
            "applied_at": applied_at,
            "mode": cropped.mode,
            "input_count": cropped.input_count,
            "selected_count": cropped.selected_count,
            "output_count": cropped.kept_count,
            "asset": relative_asset,
        }
    )
    return {key: metadata[key] for key in CLOUD_EDIT_METADATA_KEYS if key in metadata}


def _matrix4(value: object, label: str) -> NDArray[np.float64]:
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise PointCloudEditingError(f"{label}无效。") from exc
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise PointCloudEditingError(f"{label}必须是有限的 4×4 矩阵。")
    return matrix
