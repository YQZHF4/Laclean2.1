import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LACLEAN_DISABLE_OCC", "1")

from laclean.app import create_application
from laclean.ui.point_cloud_processing_dialog import PointCloudProcessingDialog


def test_processing_dialog_builds_default_statistical_pipeline() -> None:
    app = create_application(["processing-dialog-test"])
    dialog = PointCloudProcessingDialog("相机点云", 12345, "mm")

    options = dialog.options()
    assert options.statistical_enabled is True
    assert options.statistical_neighbors == 20
    assert options.statistical_std_ratio == 2.0
    assert options.voxel_enabled is False
    assert dialog.apply_button.isEnabled() is False
    assert "12,345" in dialog.result_summary.text()

    dialog.close()
    app.processEvents()
