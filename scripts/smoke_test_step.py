"""Native import/display smoke test for a STEP robot model."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from time import perf_counter

from PyQt5.QtCore import QTimer

from laclean.app import create_application
from laclean.core.scene import NodeKind
from laclean.services.project_service import ProjectService
from laclean.ui.main_window import MainWindow
from laclean.workers.point_cloud_tasks import CadModelImportThread


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", type=Path)
    arguments = parser.parse_args()
    source = arguments.step.expanduser().resolve()
    if not source.is_file():
        parser.error(f"STEP file does not exist: {source}")

    temporary = tempfile.TemporaryDirectory(prefix="laclean-step-smoke-")
    document = ProjectService().create_project("STEP冒烟测试", temporary.name)
    app = create_application(["step-smoke-test"])
    window = MainWindow()
    window._set_document(document)
    window.show()
    result: dict[str, object] = {"passed": False, "reason": "timeout"}
    started = perf_counter()
    imported_node_id = {"value": None}

    def reload_project_when_idle() -> None:
        if window._point_cloud_task is not None:
            QTimer.singleShot(100, reload_project_when_idle)
            return
        ProjectService().save_project(window.document)
        loaded = ProjectService().load_project(window.document.file_path).document
        window._set_document(loaded)
        window._restore_project_assets()
        QTimer.singleShot(100, verify_reload)

    def verify_reload() -> None:
        if window._point_cloud_task is not None:
            QTimer.singleShot(100, verify_reload)
            return
        node_id = imported_node_id["value"]
        restored = node_id in window.cad_models if node_id is not None else False
        redisplayed = (
            str(node_id) in window.viewer._cad_objects if node_id is not None else False
        )
        passed = bool(result.get("import_passed")) and restored and redisplayed
        result.update(
            passed=passed,
            project_reload_restored=restored,
            project_reload_redisplayed=redisplayed,
            total_seconds=round(perf_counter() - started, 4),
            reason="" if passed else "STEP import/reload assertion failed",
        )
        QTimer.singleShot(300, app.quit)

    def begin() -> None:
        if not window.viewer.is_ready:
            QTimer.singleShot(250, begin)
            return
        task = CadModelImportThread(
            str(source), document.file_path, NodeKind.ROBOT, window
        )

        def imported(model) -> None:
            display_started = perf_counter()
            window._on_cad_model_imported(model)
            display_seconds = perf_counter() - display_started
            robot_group = window._robot_group()
            passed = (
                model.data.shape.IsNull() is False
                and str(model.node.node_id) in window.viewer._cad_objects
                and robot_group is not None
                and len(robot_group.children) == 1
                and not robot_group.children[0].metadata.get("placeholder")
            )
            imported_node_id["value"] = model.node.node_id
            result.update(
                import_passed=passed,
                source=str(source),
                file_size=model.data.file_size,
                roots=model.data.root_count,
                solids=model.data.solid_count,
                faces=model.data.face_count,
                bounds_min=model.data.bounds_min,
                bounds_max=model.data.bounds_max,
                display_seconds=round(display_seconds, 4),
                reason="" if passed else "STEP tree/display assertion failed",
            )
            QTimer.singleShot(100, reload_project_when_idle)

        task.succeeded.connect(imported)
        task.failed.connect(
            lambda message: (
                result.update(reason=message),
                QTimer.singleShot(0, app.quit),
            )
        )
        task.finished.connect(window._finish_point_cloud_task)
        window._point_cloud_task = task
        window._begin_point_cloud_task(f"正在解析 STEP：{source.name}")
        task.start()

    QTimer.singleShot(500, begin)
    QTimer.singleShot(60_000, app.quit)
    app.exec_()
    temporary.cleanup()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
