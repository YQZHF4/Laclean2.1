"""Native OCC smoke test for upload, projection, and rectangle mouse interaction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import numpy as np
from PyQt5.QtCore import QPoint, QTimer, Qt
from PyQt5.QtTest import QTest

from laclean.app import create_application
from laclean.core.point_cloud import PointCloudData
from laclean.ui.main_window import MainWindow


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--points", type=int, default=1_000_000)
    arguments = parser.parse_args()
    count = max(1, arguments.points)

    app = create_application(["occ-smoke-test"])
    window = MainWindow()
    window.show()
    points = np.empty((count, 3), dtype=np.float32)
    points[:, 0] = np.linspace(-100.0, 100.0, count, dtype=np.float32)
    phase = np.arange(count, dtype=np.float32) * 0.0001
    points[:, 1] = np.sin(phase) * 30.0
    points[:, 2] = np.cos(phase) * 15.0
    data = PointCloudData(uuid4(), "occ-smoke", Path("occ-smoke.ply"), points)
    result: dict[str, object] = {"passed": False, "reason": "OCC initialization timeout"}

    def verify() -> None:
        if not window.viewer.is_ready:
            QTimer.singleShot(250, verify)
            return
        started = perf_counter()
        displayed = window.viewer.display_point_cloud(data, fit=True)
        upload_seconds = perf_counter() - started

        vp, (width, height) = window.viewer.capture_projection_state()
        world = np.array([*data.points[count // 2], 1.0], dtype=float)
        clip = np.asarray(vp) @ world
        ndc = clip[:3] / clip[3]
        matrix_xy = np.array(
            [(ndc[0] + 1.0) * width * 0.5, (1.0 - ndc[1]) * height * 0.5]
        )
        occ_xy = np.asarray(
            window.viewer.display.GetView().Convert(*map(float, world[:3])), dtype=float
        )
        projection_error = float(np.linalg.norm(matrix_xy - occ_xy))

        rectangle = {"value": None}
        window.viewer.crop_rectangle_drawn.connect(
            lambda value: rectangle.update(value=tuple(value))
        )
        widget = window.viewer._viewer
        window.viewer.start_rectangle_crop()
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(100, 110))
        QTest.mouseMove(widget, QPoint(300, 310), 50)
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(300, 310))

        passed = (
            displayed > 0
            and displayed <= data.display_point_limit
            and projection_error <= 2.0
            and rectangle["value"] == (100, 110, 300, 310)
        )
        result.update(
            passed=passed,
            source_points=count,
            displayed_points=displayed,
            upload_seconds=round(upload_seconds, 4),
            projection_error_pixels=round(projection_error, 4),
            crop_rectangle=rectangle["value"],
            reason="" if passed else "native OCC assertion failed",
        )
        QTimer.singleShot(300, app.quit)

    QTimer.singleShot(800, verify)
    QTimer.singleShot(30_000, app.quit)
    app.exec_()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
