import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LACLEAN_DISABLE_OCC", "1")

from laclean.app import create_application
from laclean.core.scene import NodeKind, SceneNode
from laclean.core.transforms import matrix_from_pose
from laclean.ui.properties_panel import PropertiesPanel


def test_point_cloud_properties_are_displayed() -> None:
    app = create_application(["properties-test"])
    panel = PropertiesPanel()
    node = SceneNode(
        "工件点云",
        NodeKind.POINT_CLOUD,
        metadata={
            "source_name": "camera.ply",
            "asset": "assets/pointclouds/id/camera.ply",
            "point_count": 123456,
            "display_point_count": 50000,
            "has_colors": True,
            "has_normals": False,
            "unit": "mm",
            "bounds_min": [0, 1, 2],
            "bounds_max": [10, 21, 32],
            "invalid_points_removed": 2,
            "transform": matrix_from_pose((10, 20, 30), (5, 15, 25)).tolist(),
            "coordinate_mode": "local",
        },
    )

    panel.set_node(node)

    assert not panel._point_cloud_card.isHidden()
    assert panel._cloud_source.text() == "camera.ply"
    assert panel._cloud_asset.text().startswith("assets/pointclouds/")
    assert panel._cloud_points.text() == "123,456"
    assert panel._cloud_display_points.text() == "50,000"
    assert panel._cloud_colors.text() == "有"
    assert panel._cloud_size.text() == "10.000 × 20.000 × 30.000"
    assert panel._cloud_translation.text() == "10.000, 20.000, 30.000 mm"
    assert panel._cloud_rotation.text() == "5.000°, 15.000°, 25.000°"
    assert panel._cloud_coordinate_mode.text() == "局部"
    app.processEvents()
