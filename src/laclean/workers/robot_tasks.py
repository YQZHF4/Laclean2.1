"""Background tasks for URDF robot import and project restore."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from laclean.core.error_handling import log_exception
from laclean.core.scene import SceneNode
from laclean.services.urdf_robot_service import ImportedRobotModel, UrdfRobotService


class UrdfRobotImportThread(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, source_path: str, project_file_path: str, parent=None) -> None:
        super().__init__(parent)
        self.source_path = source_path
        self.project_file_path = project_file_path

    def run(self) -> None:
        try:
            result = UrdfRobotService().import_to_project(self.source_path, self.project_file_path)
        except Exception as exc:
            self.failed.emit(log_exception("导入机械臂 URDF", exc))
            return
        self.succeeded.emit(result)


class UrdfRobotRestoreThread(QThread):
    succeeded = pyqtSignal(object, object)

    def __init__(self, nodes: list[SceneNode], project_file_path: str | Path, parent=None) -> None:
        super().__init__(parent)
        self.nodes = list(nodes)
        self.project_file_path = str(project_file_path)

    def run(self) -> None:
        service = UrdfRobotService()
        loaded = []
        errors = []
        for node in self.nodes:
            try:
                loaded.append((node, service.load_project_asset(node, self.project_file_path)))
            except Exception as exc:
                errors.append(f"{node.name}：{log_exception('恢复 URDF', exc)}")
        self.succeeded.emit(loaded, errors)
