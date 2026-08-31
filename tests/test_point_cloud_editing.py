from pathlib import Path
from uuid import uuid4

import numpy as np

from laclean.core.point_cloud import PointCloudData
from laclean.core.point_cloud_editing import (
    EditCommandHistory,
    PointCloudEditCommand,
    PointCloudEditState,
    RectangleSelection,
    crop_point_cloud,
    select_points_in_screen_rectangle,
)
from laclean.core.scene import NodeKind, SceneNode


def _data(points) -> PointCloudData:
    points = np.asarray(points, dtype=np.float32)
    count = len(points)
    return PointCloudData(
        node_id=uuid4(),
        name="crop-sample",
        asset_path=Path("source.ply"),
        points=points,
        colors=np.arange(count * 3, dtype=np.uint8).reshape(count, 3),
        normals=np.tile(np.array([[0, 0, 1]], dtype=np.float32), (count, 1)),
    )


def test_rectangle_selection_is_screen_space_and_through_depth() -> None:
    data = _data(
        [
            [0.0, 0.0, -0.5],
            [0.0, 0.0, 0.5],
            [-0.5, 0.5, 0.0],
            [0.9, 0.9, 0.0],
            [0.0, 0.0, 2.0],
        ]
    )

    selection = select_points_in_screen_rectangle(
        data,
        (20, 20, 80, 80),
        np.eye(4),
        (100, 100),
        np.eye(4),
        chunk_size=2,
    )

    assert selection.mask.tolist() == [True, True, True, False, False]
    assert selection.selected_count == 3
    assert selection.total_count == 5


def test_rectangle_selection_respects_point_cloud_transform() -> None:
    data = _data([[0.0, 0.0, 0.0]])
    transform = np.eye(4)
    transform[0, 3] = 0.8

    selection = select_points_in_screen_rectangle(
        data,
        (80, 40, 100, 60),
        np.eye(4),
        (100, 100),
        transform,
    )

    assert selection.selected_count == 1


def test_keep_and_delete_crop_all_point_attributes() -> None:
    data = _data([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]])
    selection = RectangleSelection(
        np.array([False, True, True, False]), selected_count=2, total_count=4
    )

    kept = crop_point_cloud(data, selection, keep_selected=True)
    deleted = crop_point_cloud(data, selection, keep_selected=False)

    assert kept.data.points[:, 0].tolist() == [1.0, 2.0]
    assert deleted.data.points[:, 0].tolist() == [0.0, 3.0]
    assert np.array_equal(kept.data.colors, data.colors[1:3])
    assert np.array_equal(deleted.data.normals, data.normals[[0, 3]])
    assert kept.input_count == 4
    assert kept.selected_count == 2
    assert kept.kept_count == 2
    assert data.point_count == 4


def test_command_history_clears_redo_branch_after_new_edit() -> None:
    data = _data([[0, 0, 0]])
    node = SceneNode("cloud", NodeKind.POINT_CLOUD, node_id=data.node_id)
    state = PointCloudEditState.capture(node, data)
    first = PointCloudEditCommand(node.node_id, "first", state, state)
    second = PointCloudEditCommand(node.node_id, "second", state, state)
    history = EditCommandHistory(limit=2)

    history.push(first)
    assert history.undo() is first
    assert history.redo_text == "first"
    history.push(second)

    assert history.redo() is None
    assert history.undo_text == "second"


def test_command_history_prunes_old_states_by_memory_budget() -> None:
    data0 = _data([[0, 0, 0]])
    data1 = _data([[1, 0, 0]])
    data2 = _data([[2, 0, 0]])
    node = SceneNode("cloud", NodeKind.POINT_CLOUD, node_id=data0.node_id)
    state0 = PointCloudEditState.capture(node, data0)
    state1 = PointCloudEditState.capture(node, data1)
    state2 = PointCloudEditState.capture(node, data2)
    history = EditCommandHistory(limit=20, max_memory_bytes=60)

    assert history.push(PointCloudEditCommand(node.node_id, "first", state0, state1)) == 0
    removed = history.push(
        PointCloudEditCommand(node.node_id, "second", state1, state2)
    )

    assert removed == 1
    assert history.undo_text == "second"
    assert history.memory_bytes <= 60


def test_million_point_rectangle_selection_uses_chunked_full_data() -> None:
    from time import perf_counter

    count = 1_000_000
    points = np.zeros((count, 3), dtype=np.float32)
    points[:, 0] = np.linspace(-1.0, 1.0, count, dtype=np.float32)
    data = PointCloudData(
        node_id=uuid4(),
        name="million-points",
        asset_path=Path("large.ply"),
        points=points,
    )

    started = perf_counter()
    selection = select_points_in_screen_rectangle(
        data,
        (0, 0, 1000, 1000),
        np.eye(4),
        (1000, 1000),
        chunk_size=100_000,
    )
    elapsed = perf_counter() - started

    assert selection.selected_count == count
    assert selection.mask.nbytes == count
    assert elapsed < 5.0


def test_large_cloud_uses_adaptive_zero_copy_display_proxy() -> None:
    count = 1_000_000
    points = np.zeros((count, 3), dtype=np.float32)
    data = PointCloudData(
        node_id=uuid4(),
        name="display-proxy",
        asset_path=Path("large.ply"),
        points=points,
    )

    display_points, _ = data.display_arrays()

    assert len(display_points) <= data.display_point_limit
    assert np.shares_memory(display_points, data.points)
    assert data.memory_bytes == points.nbytes
