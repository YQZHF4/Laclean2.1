"""Non-blocking point-cloud import and project restoration tasks."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from laclean.core.error_handling import log_exception
from laclean.core.scene import NodeKind, SceneNode
from laclean.core.point_cloud import PointCloudData
from laclean.core.point_cloud_editing import (
    RectangleSelection,
    crop_point_cloud,
    select_points_in_screen_rectangle,
)
from laclean.core.point_cloud_processing import PointCloudProcessingOptions
from laclean.services.point_cloud_service import PointCloudService
from laclean.services.point_cloud_processing_service import PointCloudProcessingService
from laclean.services.cad_model_service import CadModelService


class PointCloudImportThread(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, source_path: str, project_file_path: str, parent=None) -> None:
        super().__init__(parent)
        self.source_path = source_path
        self.project_file_path = project_file_path

    def run(self) -> None:
        try:
            result = PointCloudService().import_to_project(
                self.source_path, self.project_file_path
            )
        except Exception as exc:
            self.failed.emit(log_exception("导入点云", exc))
            return
        self.succeeded.emit(result)


class PointCloudRestoreThread(QThread):
    succeeded = pyqtSignal(object, object)

    def __init__(
        self, nodes: list[SceneNode], project_file_path: str | Path, parent=None
    ) -> None:
        super().__init__(parent)
        self.nodes = list(nodes)
        self.project_file_path = str(project_file_path)

    def run(self) -> None:
        service = PointCloudService()
        loaded = []
        errors = []
        for node in self.nodes:
            try:
                loaded.append((node, service.load_project_asset(node, self.project_file_path)))
            except Exception as exc:
                errors.append(f"{node.name}：{log_exception('恢复点云', exc)}")
        self.succeeded.emit(loaded, errors)


class PointCloudProcessThread(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        data: PointCloudData,
        options: PointCloudProcessingOptions,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.data = data
        self.options = options

    def run(self) -> None:
        try:
            result = PointCloudProcessingService().process(self.data, self.options)
        except Exception as exc:
            self.failed.emit(log_exception("处理点云", exc))
            return
        self.succeeded.emit(result)


class PointCloudPersistThread(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self, data: PointCloudData, project_file_path: str | Path, parent=None
    ) -> None:
        super().__init__(parent)
        self.data = data
        self.project_file_path = str(project_file_path)

    def run(self) -> None:
        try:
            result = PointCloudProcessingService().persist(
                self.data, self.project_file_path
            )
        except Exception as exc:
            self.failed.emit(log_exception("保存处理结果", exc))
            return
        self.succeeded.emit(result)


class PointCloudRectangleSelectionThread(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        data: PointCloudData,
        rectangle: tuple[int, int, int, int],
        view_projection: object,
        viewport_size: tuple[int, int],
        model_transform: object,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.data = data
        self.rectangle = rectangle
        self.view_projection = view_projection
        self.viewport_size = viewport_size
        self.model_transform = model_transform

    def run(self) -> None:
        try:
            selection = select_points_in_screen_rectangle(
                self.data,
                self.rectangle,
                self.view_projection,
                self.viewport_size,
                self.model_transform,
            )
        except Exception as exc:
            self.failed.emit(log_exception("矩形框选", exc))
            return
        self.succeeded.emit(selection)


class PointCloudCropPersistThread(QThread):
    succeeded = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        data: PointCloudData,
        selection: RectangleSelection,
        keep_selected: bool,
        project_file_path: str | Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.data = data
        self.selection = selection
        self.keep_selected = keep_selected
        self.project_file_path = str(project_file_path)

    def run(self) -> None:
        try:
            cropped = crop_point_cloud(
                self.data, self.selection, keep_selected=self.keep_selected
            )
            persisted = PointCloudProcessingService().persist(
                cropped.data,
                self.project_file_path,
                filename_prefix="cropped",
            )
            cropped.data.asset_path = persisted.asset_path
        except Exception as exc:
            self.failed.emit(log_exception("应用矩形裁剪", exc))
            return
        self.succeeded.emit(cropped, persisted)


class CadModelImportThread(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        source_path: str,
        project_file_path: str,
        node_kind: NodeKind,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.source_path = source_path
        self.project_file_path = project_file_path
        self.node_kind = node_kind

    def run(self) -> None:
        try:
            result = CadModelService().import_to_project(
                self.source_path, self.project_file_path, self.node_kind
            )
        except Exception as exc:
            self.failed.emit(log_exception("导入 STEP", exc))
            return
        self.succeeded.emit(result)


class CadModelRestoreThread(QThread):
    succeeded = pyqtSignal(object, object)

    def __init__(
        self, nodes: list[SceneNode], project_file_path: str | Path, parent=None
    ) -> None:
        super().__init__(parent)
        self.nodes = list(nodes)
        self.project_file_path = str(project_file_path)

    def run(self) -> None:
        service = CadModelService()
        loaded = []
        errors = []
        for node in self.nodes:
            try:
                loaded.append((node, service.load_project_asset(node, self.project_file_path)))
            except Exception as exc:
                errors.append(f"{node.name}：{log_exception('恢复 STEP', exc)}")
        self.succeeded.emit(loaded, errors)
