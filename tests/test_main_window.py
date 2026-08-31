import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LACLEAN_DISABLE_OCC", "1")

from laclean.app import create_application
from laclean.core.point_cloud import PointCloudData
from laclean.core.cad_model import CadModelData
from laclean.core.point_cloud_editing import PointCloudEditState, RectangleSelection
from laclean.core.scene import NodeKind, SceneNode
from laclean.core.transforms import matrix_from_pose, pose_from_matrix
from laclean.ui.main_window import MainWindow
from laclean.services.cad_model_service import ImportedCadModel


def _wait_for_point_cloud_task(app, window: MainWindow) -> None:
    from PyQt5.QtCore import QElapsedTimer
    from PyQt5.QtTest import QTest

    timer = QElapsedTimer()
    timer.start()
    while window._point_cloud_task is not None and timer.elapsed() < 10_000:
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()
    assert window._point_cloud_task is None


def test_main_window_builds_application_shell() -> None:
    app = create_application(["laclean-test"])
    window = MainWindow()

    assert "Laclean Studio" in window.windowTitle()
    assert window.scene_tree.topLevelItemCount() == 1
    assert window.scene_tree.topLevelItem(0).childCount() == 6
    assert "import_point_cloud" in window.actions
    assert "save_project_as" in window.actions
    assert window.properties_dock.widget() is window.properties

    app.processEvents()
    assert window.properties._name.text() == "未命名项目"

    window.close()
    app.processEvents()


def test_main_window_saves_and_reopens_project(tmp_path) -> None:
    app = create_application(["laclean-test"])
    window = MainWindow()
    document = window.project_service.create_project("窗口测试", tmp_path)
    window._set_document(document)

    robot = window.document.root.children[2].children[0]
    robot.visible = True
    window.document.modified = True
    assert window._save_document(window.document.file_path) is True
    assert window.document.modified is False

    window.document.root.name = "临时名称"
    assert window.open_project_path(tmp_path / "窗口测试" / "project.lcp") is True
    assert window.document.root.name == "窗口测试"
    assert window.document.root.children[2].children[0].visible is True

    window.close()
    app.processEvents()


def test_manipulator_transform_updates_node_and_dirty_state() -> None:
    app = create_application(["laclean-test"])
    window = MainWindow()
    point_group = window.document.root.children[0]
    node = point_group.add_child(
        SceneNode(
            "位姿测试点云",
            NodeKind.POINT_CLOUD,
            metadata={"transform": matrix_from_pose((0, 0, 0), (0, 0, 0)).tolist()},
        )
    )
    window._selected_node = node
    target = matrix_from_pose((11, 22, 33), (10, 20, 30))

    window._on_manipulator_transform_changed(str(node.node_id), target.tolist())

    translation, rotation = pose_from_matrix(node.metadata["transform"])
    assert translation == pytest.approx((11, 22, 33))
    assert rotation == pytest.approx((10, 20, 30))
    assert window.document.modified is True
    assert "*" in window.windowTitle()

    window.document.modified = False
    window.close()
    app.processEvents()


def test_main_window_previews_and_applies_point_cloud_processing(tmp_path) -> None:
    app = create_application(["processing-main-window-test"])
    window = MainWindow()
    document = window.project_service.create_project("处理集成", tmp_path)
    window._set_document(document)
    group = window._point_cloud_group()
    assert group is not None
    node = group.add_child(
        SceneNode(
            "处理样本",
            NodeKind.POINT_CLOUD,
            metadata={
                "asset": "assets/pointclouds/source/source.ply",
                "point_count": 4,
                "display_point_count": 4,
                "has_colors": True,
                "has_normals": False,
                "unit": "mm",
                "bounds_min": [0, 0, 0],
                "bounds_max": [1.02, 0.01, 0],
                "transform": np.eye(4).tolist(),
                "point_size": 2.0,
                "coordinate_mode": "local",
            },
        )
    )
    data = PointCloudData(
        node_id=node.node_id,
        name=node.name,
        asset_path=Path("source.ply"),
        points=np.array(
            [[0, 0, 0], [0.02, 0.01, 0], [1, 0, 0], [1.02, 0.01, 0]],
            dtype=np.float32,
        ),
        colors=np.tile(np.array([[30, 120, 220]], dtype=np.uint8), (4, 1)),
    )
    window.point_clouds[node.node_id] = data
    window.scene_tree.rebuild()

    assert window.open_point_cloud_processing(node) is True
    dialog = window._processing_dialog
    assert dialog is not None
    dialog.statistical_group.setChecked(False)
    dialog.voxel_group.setChecked(True)
    dialog.voxel_size.setValue(0.25)
    window._start_point_cloud_preview(dialog.options())
    _wait_for_point_cloud_task(app, window)

    assert window._processing_preview is not None
    assert window._processing_preview.data.point_count == 2
    window._apply_point_cloud_preview()
    _wait_for_point_cloud_task(app, window)

    assert window._processing_dialog is None
    assert window.point_clouds[node.node_id].point_count == 2
    assert node.metadata["original_asset"].endswith("source.ply")
    assert node.metadata["asset"].endswith(".ply")
    assert len(node.metadata["processing_history"]) == 1
    assert window._save_document(window.document.file_path) is True

    loaded = window.project_service.load_project(window.document.file_path).document
    loaded_node = loaded.find(node.node_id)
    assert loaded_node is not None
    assert len(loaded_node.metadata["processing_history"]) == 1
    assert int(loaded_node.metadata["point_count"]) == 2

    window.close()
    app.processEvents()


def test_rectangle_crop_can_be_undone_redone_and_saved(tmp_path) -> None:
    app = create_application(["crop-main-window-test"])
    window = MainWindow()
    document = window.project_service.create_project("裁剪集成", tmp_path)
    window._set_document(document)
    group = window._point_cloud_group()
    assert group is not None
    node = group.add_child(
        SceneNode(
            "裁剪样本",
            NodeKind.POINT_CLOUD,
            metadata={
                "asset": "assets/pointclouds/source/source.ply",
                "point_count": 4,
                "display_point_count": 4,
                "has_colors": True,
                "has_normals": False,
                "unit": "mm",
                "bounds_min": [0, 0, 0],
                "bounds_max": [3, 0, 0],
                "transform": np.eye(4).tolist(),
                "point_size": 2.0,
                "coordinate_mode": "local",
            },
        )
    )
    data = PointCloudData(
        node_id=node.node_id,
        name=node.name,
        asset_path=Path("source.ply"),
        points=np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]], dtype=np.float32),
        colors=np.tile(np.array([[20, 130, 230]], dtype=np.uint8), (4, 1)),
    )
    window.point_clouds[node.node_id] = data
    window._crop_node_id = node.node_id
    window._crop_before_state = PointCloudEditState.capture(node, data)
    window._crop_selection = RectangleSelection(
        np.array([False, True, True, False]), selected_count=2, total_count=4
    )

    window._start_crop_apply(keep_selected=False)
    _wait_for_point_cloud_task(app, window)

    cropped_asset = node.metadata["asset"]
    assert window.point_clouds[node.node_id].point_count == 2
    assert cropped_asset.endswith(".ply")
    assert window.actions["undo"].isEnabled() is True
    assert window.undo_edit() is True
    assert window.point_clouds[node.node_id].point_count == 4
    assert node.metadata["asset"].endswith("source.ply")
    assert window.redo_edit() is True
    assert window.point_clouds[node.node_id].point_count == 2
    assert node.metadata["asset"] == cropped_asset
    assert window._save_document(window.document.file_path) is True

    loaded = window.project_service.load_project(window.document.file_path).document
    loaded_node = loaded.find(node.node_id)
    assert loaded_node is not None
    assert loaded_node.metadata["point_count"] == 2
    assert len(loaded_node.metadata["crop_history"]) == 1

    window.close()
    app.processEvents()


def test_imported_robot_replaces_placeholder_and_is_queued_for_occ(tmp_path) -> None:
    app = create_application(["robot-import-window-test"])
    window = MainWindow()
    document = window.project_service.create_project("机械臂界面", tmp_path)
    window._set_document(document)
    node = SceneNode(
        "R6-093S",
        NodeKind.ROBOT,
        metadata={
            "asset": "assets/robots/id/robot.stp",
            "source_name": "robot.stp",
            "format": "STEP",
            "file_size": 100,
            "root_count": 1,
            "solid_count": 55,
            "face_count": 4426,
            "bounds_min": [-1, 0, -1],
            "bounds_max": [1, 10, 1],
            "display_color": [0.72, 0.76, 0.82],
        },
    )
    data = CadModelData(
        node_id=node.node_id,
        name=node.name,
        asset_path=Path("robot.stp"),
        shape=object(),
        file_size=100,
        root_count=1,
        solid_count=55,
        face_count=4426,
        mesh_deflection=0.1,
        bounds_min=(-1, 0, -1),
        bounds_max=(1, 10, 1),
    )

    window._on_cad_model_imported(ImportedCadModel(node, data))

    robot_group = window._robot_group()
    assert robot_group is not None
    assert robot_group.children == [node]
    assert window.cad_models[node.node_id] is data
    assert str(node.node_id) in window.viewer._pending_cad_models
    assert window.properties._cad_solids.text() == "55"
    assert window._save_document(window.document.file_path) is True

    loaded = window.project_service.load_project(window.document.file_path).document
    assert loaded.find(node.node_id).metadata["face_count"] == 4426
    window.close()
    app.processEvents()
