"""Main desktop shell for the offline programming application."""

from __future__ import annotations

import shutil
import tempfile
from copy import deepcopy
from functools import partial
from pathlib import Path
from uuid import UUID

from PyQt5.QtCore import QByteArray, QSize, Qt, QTimer
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAction,
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QStyle,
    QToolBar,
)

from laclean.core.cad_model import CadModelData
from laclean.core.robot_model import RobotModelData
from laclean.core.point_cloud import PointCloudData
from laclean.core.error_handling import format_bytes, log_exception
from laclean.core.point_cloud_editing import EditCommandHistory, PointCloudEditState, RectangleSelection
from laclean.core.scene import NodeKind, SceneDocument, SceneNode
from laclean.application.controller import ApplicationController
from laclean.services.point_cloud_service import (
    ImportedPointCloud,
    SUPPORTED_POINT_CLOUD_SUFFIXES,
)
from laclean.services.cad_model_service import (
    ImportedCadModel,
    SUPPORTED_CAD_SUFFIXES,
)
from laclean.services.urdf_robot_service import ImportedRobotModel
from laclean.services.point_cloud_processing_service import (
    PersistedPointCloud,
    ProcessedPointCloud,
)
from laclean.services.project_service import ProjectError, ProjectService
from laclean.ui.icons import make_toolbar_icon
from laclean.ui.new_project_dialog import NewProjectDialog
from laclean.ui.occ_viewer import OccViewerPanel
from laclean.ui.point_cloud_processing_dialog import PointCloudProcessingDialog
from laclean.ui.properties_panel import OperationPanel, PropertiesPanel
from laclean.ui.scene_tree import SceneTreeWidget
from laclean.workers.point_cloud_tasks import (
    CadModelImportThread,
    CadModelRestoreThread,
    PointCloudImportThread,
    PointCloudCropPersistThread,
    PointCloudPersistThread,
    PointCloudProcessThread,
    PointCloudRectangleSelectionThread,
    PointCloudRestoreThread,
)
from laclean.workers.robot_tasks import UrdfRobotImportThread, UrdfRobotRestoreThread


class ProcessingScrollArea(QScrollArea):
    """Keep embedded processing controls clear of an overlay scrollbar."""

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        self.fit_content_width()

    def fit_content_width(self) -> None:
        widget = self.widget()
        if widget is None:
            return
        scrollbar_width = self.verticalScrollBar().sizeHint().width()
        content_width = max(1, self.viewport().width() - scrollbar_width - 2)
        widget.setFixedWidth(content_width)


class MainWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.resize(1480, 900)
        self.setMinimumSize(1100, 680)
        self.setDockOptions(
            QMainWindow.AnimatedDocks
            | QMainWindow.AllowNestedDocks
            | QMainWindow.AllowTabbedDocks
        )

        self.application = ApplicationController()
        self._point_cloud_task = None
        self._selected_node: SceneNode | None = None
        self._processing_dialog: PointCloudProcessingDialog | None = None
        self._processing_node_id: UUID | None = None
        self._processing_original: PointCloudData | None = None
        self._processing_preview: ProcessedPointCloud | None = None
        self._processing_applied = False
        self._crop_node_id: UUID | None = None
        self._crop_before_state: PointCloudEditState | None = None
        self._crop_selection: RectangleSelection | None = None
        self._scratch_project_directory: tempfile.TemporaryDirectory | None = None
        self.actions: dict[str, QAction] = {}
        self._operation_node: SceneNode | None = None
        self._pending_pose: tuple[UUID, object] | None = None
        self._pending_pose_matrix: object | None = None
        self._pending_robot_kinematics: tuple[UUID, dict[str, float], dict[str, list[list[float]]]] | None = None
        self._processing_scroll_area: QScrollArea | None = None

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_central_viewer()
        self._create_docks()
        self._create_status_bar()
        self._connect_signals()
        self._update_window_title()

        QTimer.singleShot(0, self._select_project_root)

    @property
    def project_service(self) -> ProjectService:
        return self.application.project_service

    @property
    def document(self) -> SceneDocument:
        return self.application.document

    @document.setter
    def document(self, value: SceneDocument) -> None:
        self.application.document = value

    @property
    def point_clouds(self) -> dict[object, PointCloudData]:
        return self.application.point_clouds

    @property
    def cad_models(self) -> dict[object, CadModelData]:
        return self.application.cad_models

    @property
    def robot_models(self) -> dict[object, RobotModelData]:
        return self.application.robot_models

    @property
    def _edit_history(self) -> EditCommandHistory:
        return self.application.edit_history

    def _create_actions(self) -> None:
        style = self.style()
        specs = {
            "new_project": ("新建项目", QStyle.SP_FileIcon, "Ctrl+N"),
            "open_project": ("打开项目…", QStyle.SP_DialogOpenButton, "Ctrl+O"),
            "save_project": ("保存项目", QStyle.SP_DialogSaveButton, "Ctrl+S"),
            "save_project_as": ("项目另存为…", QStyle.SP_DialogSaveButton, "Ctrl+Shift+S"),
            "capture": ("拍照", QStyle.SP_DialogYesButton, ""),
            "camera_connection": ("相机通讯", QStyle.SP_DriveNetIcon, ""),
            "import_point_cloud": ("导入点云", QStyle.SP_FileDialogNewFolder, "Ctrl+I"),
            "import_cad": ("导入数模", QStyle.SP_FileIcon, ""),
            "import_robot": ("导入机械臂 URDF", QStyle.SP_ComputerIcon, ""),
            "path_parameters": ("路径参数", QStyle.SP_FileDialogDetailedView, ""),
            "generate_path": ("路径生成", QStyle.SP_ArrowForward, ""),
            "robot_connection": ("机械臂通讯", QStyle.SP_ComputerIcon, ""),
            "galvo_connection": ("振镜通讯", QStyle.SP_DriveNetIcon, ""),
            "undo": ("撤销", QStyle.SP_ArrowBack, "Ctrl+Z"),
            "redo": ("重做", QStyle.SP_ArrowForward, "Ctrl+Y"),
            "about": ("关于", QStyle.SP_MessageBoxInformation, ""),
            "exit": ("退出", QStyle.SP_DialogCloseButton, "Alt+F4"),
        }
        for action_id, (text, icon_enum, shortcut) in specs.items():
            action = QAction(style.standardIcon(icon_enum), text, self)
            action.setObjectName(f"action_{action_id}")
            if shortcut:
                action.setShortcut(shortcut)
            self.actions[action_id] = action

        for action_id in (
            "capture",
            "camera_connection",
            "import_point_cloud",
            "import_cad",
            "import_robot",
            "path_parameters",
            "generate_path",
            "robot_connection",
            "galvo_connection",
        ):
            self.actions[action_id].setIcon(make_toolbar_icon(action_id))

        self.actions["new_project"].triggered.connect(
            lambda checked=False: self.new_project()
        )
        self.actions["open_project"].triggered.connect(
            lambda checked=False: self.open_project()
        )
        self.actions["save_project"].triggered.connect(
            lambda checked=False: self.save_project()
        )
        self.actions["save_project_as"].triggered.connect(
            lambda checked=False: self.save_project_as()
        )
        self.actions["import_point_cloud"].triggered.connect(
            lambda checked=False: self.import_point_cloud()
        )
        self.actions["import_cad"].triggered.connect(
            lambda checked=False: self.import_cad_model(NodeKind.CAD_MODEL)
        )
        self.actions["import_robot"].triggered.connect(
            lambda checked=False: self.import_robot_urdf()
        )
        self.actions["undo"].triggered.connect(lambda checked=False: self.undo_edit())
        self.actions["redo"].triggered.connect(lambda checked=False: self.redo_edit())

        for action_id in (
            "capture",
            "camera_connection",
            "path_parameters",
            "generate_path",
            "robot_connection",
            "galvo_connection",
        ):
            self.actions[action_id].triggered.connect(partial(self._reserved_action, action_id))

        self._update_edit_actions()

        self.actions["about"].triggered.connect(self._show_about)
        self.actions["exit"].triggered.connect(self.close)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")
        file_menu.addAction(self.actions["new_project"])
        file_menu.addAction(self.actions["open_project"])
        file_menu.addSeparator()
        file_menu.addAction(self.actions["save_project"])
        file_menu.addAction(self.actions["save_project_as"])
        file_menu.addSeparator()
        file_menu.addAction(self.actions["import_point_cloud"])
        file_menu.addAction(self.actions["import_cad"])
        file_menu.addAction(self.actions["import_robot"])
        file_menu.addSeparator()
        file_menu.addAction(self.actions["exit"])

        edit_menu = self.menuBar().addMenu("编辑(&E)")
        edit_menu.addAction(self.actions["undo"])
        edit_menu.addAction(self.actions["redo"])

        view_menu = self.menuBar().addMenu("视图(&V)")

        tools_menu = self.menuBar().addMenu("工具(&T)")
        tools_menu.addAction(self.actions["camera_connection"])
        tools_menu.addAction(self.actions["robot_connection"])
        tools_menu.addAction(self.actions["galvo_connection"])
        tools_menu.addSeparator()
        tools_menu.addAction(self.actions["path_parameters"])
        tools_menu.addAction(self.actions["generate_path"])

        help_menu = self.menuBar().addMenu("帮助(&H)")
        help_menu.addAction(self.actions["about"])

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.setIconSize(QSize(30, 30))
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        toolbar.addAction(self.actions["capture"])
        toolbar.addAction(self.actions["camera_connection"])
        toolbar.addSeparator()
        toolbar.addAction(self.actions["import_point_cloud"])
        toolbar.addAction(self.actions["import_cad"])
        toolbar.addAction(self.actions["import_robot"])
        toolbar.addSeparator()
        toolbar.addAction(self.actions["path_parameters"])
        toolbar.addAction(self.actions["generate_path"])
        toolbar.addSeparator()
        toolbar.addAction(self.actions["robot_connection"])
        toolbar.addAction(self.actions["galvo_connection"])

    def _create_central_viewer(self) -> None:
        self.viewer = OccViewerPanel(self)
        self.setCentralWidget(self.viewer)

    def _create_docks(self) -> None:
        self.scene_tree = SceneTreeWidget(self.document, self)
        self.scene_dock = QDockWidget("项目对象", self)
        self.scene_dock.setObjectName("sceneDock")
        self.scene_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.scene_dock.setMinimumWidth(290)
        self.scene_dock.setWidget(self.scene_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.scene_dock)

        self.properties = PropertiesPanel(self)
        self.operation_panel = OperationPanel(self)
        self.properties_dock = QDockWidget("属性与任务", self)
        self.properties_dock.setObjectName("propertiesDock")
        self.properties_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.properties_dock.setMinimumWidth(360)
        self.properties_dock.setWidget(self.properties)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)

        view_menu = next(
            (action.menu() for action in self.menuBar().actions() if action.text().startswith("视图")),
            None,
        )
        if view_menu is not None:
            view_menu.addSeparator()
            view_menu.addAction(self.scene_dock.toggleViewAction())
            view_menu.addAction(self.properties_dock.toggleViewAction())

    def _create_status_bar(self) -> None:
        self._status_message = QLabel("就绪")
        self.statusBar().addWidget(self._status_message, 1)

        self._task_progress = QProgressBar()
        self._task_progress.setRange(0, 0)
        self._task_progress.setFixedWidth(130)
        self._task_progress.setTextVisible(False)
        self._task_progress.hide()
        self.statusBar().addPermanentWidget(self._task_progress)

        self._camera_badge = QLabel("相机 未连接")
        self._camera_badge.setProperty("badge", "offline")
        self._robot_badge = QLabel("机械臂 未连接")
        self._robot_badge.setProperty("badge", "offline")
        self._galvo_badge = QLabel("振镜 未连接")
        self._galvo_badge.setProperty("badge", "offline")

        for widget in (
            self._camera_badge,
            self._robot_badge,
            self._galvo_badge,
        ):
            self.statusBar().addPermanentWidget(widget)

    def _connect_signals(self) -> None:
        self.scene_tree.node_selected.connect(self._on_node_selected)
        self.scene_tree.action_requested.connect(self._handle_tree_action)
        self.viewer.initialized.connect(self._on_viewer_initialized)
        self.viewer.manipulator_transform_changed.connect(
            self._on_manipulator_transform_changed
        )
        self.viewer.crop_rectangle_drawn.connect(self._on_crop_rectangle_drawn)
        self.viewer.crop_cancelled.connect(self._on_crop_cancelled)
        self.operation_panel.confirmed.connect(self._on_operation_confirmed)
        self.operation_panel.cancelled.connect(self._on_operation_cancelled)
        self.operation_panel.pose_changed.connect(self._on_operation_pose_changed)
        self.operation_panel.robot_joints_changed.connect(self._on_robot_joints_changed)
        self.operation_panel.crop_redraw_requested.connect(self._on_crop_redraw_requested)

    def new_project(self) -> bool:
        if not self._confirm_close_current_project():
            return False

        dialog = NewProjectDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return False

        try:
            document = self.project_service.create_project(
                dialog.project_name, dialog.parent_directory
            )
        except ProjectError as exc:
            QMessageBox.critical(self, "新建项目失败", str(exc))
            return False

        self._set_document(document)
        self._save_document(document.file_path)
        self._status_message.setText(f"项目已创建：{document.file_path}")
        return True

    def open_project(self) -> bool:
        if not self._confirm_close_current_project():
            return False

        start_directory = (
            str(Path(self.document.file_path).parent)
            if self.document.file_path
            else str(Path.cwd())
        )
        project_path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 Laclean 项目",
            start_directory,
            "Laclean 项目 (*.lcp);;所有文件 (*)",
        )
        if not project_path:
            return False
        return self.open_project_path(project_path)

    def open_project_path(self, project_path: str | Path) -> bool:
        """Open a concrete path; separated for recent-files and test integration."""

        try:
            loaded = self.project_service.load_project(project_path)
        except ProjectError as exc:
            QMessageBox.critical(self, "打开项目失败", str(exc))
            return False

        self._set_document(loaded.document)
        self._restore_ui_state(loaded.ui_state)
        self._restore_project_assets()
        self._status_message.setText(f"项目已打开：{loaded.document.file_path}")
        return True

    def save_project(self) -> bool:
        if self.document.file_path is None:
            return self.save_project_as()
        return self._save_document(self.document.file_path)

    def save_project_as(self) -> bool:
        suggested_path = self.document.file_path or str(Path.cwd() / "project.lcp")
        project_path, _ = QFileDialog.getSaveFileName(
            self,
            "项目另存为",
            suggested_path,
            "Laclean 项目 (*.lcp)",
        )
        if not project_path:
            return False
        return self._save_document(project_path)

    def _save_document(self, project_path: str | Path | None) -> bool:
        try:
            target_path = Path(project_path).expanduser().resolve() if project_path else None
            if target_path is not None and target_path.suffix.lower() != ".lcp":
                target_path = target_path.with_suffix(".lcp")
            if target_path is not None:
                self._copy_scratch_assets_to_project(target_path.parent)
        except OSError as exc:
            QMessageBox.critical(self, "保存项目失败", f"复制临时项目资产失败：{exc}")
            return False

        try:
            saved_path = self.project_service.save_project(
                self.document,
                ui_state=self._capture_ui_state(),
                target_path=target_path or project_path,
            )
        except ProjectError as exc:
            QMessageBox.critical(self, "保存项目失败", str(exc))
            return False

        self._cleanup_scratch_project_directory()
        self._update_window_title()
        self._status_message.setText(f"项目已保存：{saved_path}")
        return True

    def _set_document(self, document: SceneDocument) -> None:
        if self._processing_dialog is not None:
            self._processing_dialog.reject()
        self._finish_crop_session(reattach=False)
        self._update_edit_actions()
        self.viewer.clear_point_clouds()
        self.viewer.clear_cad_models()
        self.viewer.clear_robot_models()
        self.point_clouds.clear()
        self.cad_models.clear()
        self.robot_models.clear()
        self._cleanup_scratch_project_directory()
        self.application.replace_document(document)
        self.scene_tree.set_document(document)
        self._select_project_root()
        self._update_window_title()

    def _asset_project_file_path(self) -> str:
        if self.document.file_path is not None:
            return self.document.file_path
        return self._ensure_scratch_project_file_path()

    def _ensure_scratch_project_file_path(self) -> str:
        if self._scratch_project_directory is None:
            self._scratch_project_directory = tempfile.TemporaryDirectory(
                prefix="laclean-unsaved-"
            )
        scratch_root = Path(self._scratch_project_directory.name)
        return str(scratch_root / "project.lcp")

    def _copy_scratch_assets_to_project(self, project_directory: Path) -> None:
        if self._scratch_project_directory is None:
            return
        scratch_assets = Path(self._scratch_project_directory.name) / "assets"
        if not scratch_assets.exists():
            return
        target_assets = project_directory / "assets"
        shutil.copytree(scratch_assets, target_assets, dirs_exist_ok=True)
        for data in self.point_clouds.values():
            if data.asset_path is not None:
                candidate = Path(data.asset_path)
                try:
                    relative = candidate.resolve().relative_to(scratch_assets.parent.resolve())
                except ValueError:
                    continue
                data.asset_path = project_directory / relative
        for data in self.cad_models.values():
            candidate = Path(data.asset_path)
            try:
                relative = candidate.resolve().relative_to(scratch_assets.parent.resolve())
            except ValueError:
                continue
            data.asset_path = project_directory / relative
        for data in self.robot_models.values():
            candidate = Path(data.urdf_path)
            try:
                relative = candidate.resolve().relative_to(scratch_assets.parent.resolve())
            except ValueError:
                continue
            data.urdf_path = project_directory / relative

    def _cleanup_scratch_project_directory(self) -> None:
        if self._scratch_project_directory is not None:
            self._scratch_project_directory.cleanup()
            self._scratch_project_directory = None

    def _capture_ui_state(self) -> dict[str, str]:
        return {
            "main_window_state": bytes(self.saveState().toBase64()).decode("ascii"),
        }

    def _restore_ui_state(self, ui_state: dict[str, object]) -> None:
        encoded_state = ui_state.get("main_window_state")
        if not isinstance(encoded_state, str) or not encoded_state:
            return
        try:
            state = QByteArray.fromBase64(encoded_state.encode("ascii"))
            self.restoreState(state)
        except (UnicodeEncodeError, ValueError):
            self._status_message.setText("项目已打开，但界面布局数据无效")

    def _confirm_close_current_project(self) -> bool:
        if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
            QMessageBox.information(self, "任务进行中", "请等待点云任务完成后再切换或关闭项目。")
            return False
        if not self.document.modified:
            return True

        choice = QMessageBox.warning(
            self,
            "项目尚未保存",
            f"项目“{self.document.root.name}”包含未保存的修改。",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if choice == QMessageBox.Save:
            return self.save_project()
        return choice == QMessageBox.Discard

    def _select_project_root(self) -> None:
        root = self.scene_tree.topLevelItem(0)
        if root is not None:
            self.scene_tree.setCurrentItem(root)
            self.properties.set_node(self.document.root)

    def _update_window_title(self) -> None:
        modified_marker = " *" if self.document.modified else ""
        self.setWindowTitle(
            f"{self.document.root.name}{modified_marker} — Laclean Studio · 激光清洗离线编程平台"
        )

    def _on_viewer_initialized(self, success: bool, message: str) -> None:
        self._status_message.setText(message if success else "三维视图未就绪")

    def _on_node_selected(self, node: SceneNode | None) -> None:
        if self._operation_node is not None and node is not self._operation_node:
            self._on_operation_cancelled()
        self._selected_node = node
        self.properties.set_node(node)
        if node is not None and node.kind is NodeKind.POINT_CLOUD:
            count = int(node.metadata.get("point_count", 0))
            self._status_message.setText(f"{node.name} · {count:,} 点")
            self.viewer.detach_manipulator()
        elif (
            node is not None
            and node.kind in {NodeKind.CAD_MODEL, NodeKind.ROBOT}
            and not node.metadata.get("placeholder")
        ):
            self.viewer.detach_manipulator()
            if node.kind is NodeKind.ROBOT:
                self._status_message.setText(f"{node.name} · {node.metadata.get('link_count', 0)} 个 link · {node.metadata.get('joint_count', 0)} 个 joint")
            else:
                solids = int(node.metadata.get("solid_count", 0))
                faces = int(node.metadata.get("face_count", 0))
                self._status_message.setText(f"{node.name} · {solids:,} 实体 · {faces:,} 面")
        else:
            self.viewer.detach_manipulator()

    def _fit_all(self) -> None:
        self.viewer.fit_all()
        self._status_message.setText("视图已适应窗口")

    def _handle_tree_action(self, action_id: str, node: SceneNode | None) -> None:
        if action_id == "visibility_changed":
            if node is not None:
                self.application.set_visibility(node, node.visible)
                self._update_window_title()
                state = "显示" if node.visible else "隐藏"
                self._status_message.setText(f"{node.name}：{state}")
                if node.kind is NodeKind.POINT_CLOUD:
                    self.viewer.set_point_cloud_visible(node.node_id, node.visible)
                elif node.kind is NodeKind.CAD_MODEL:
                    self.viewer.set_cad_model_visible(node.node_id, node.visible)
                elif node.kind is NodeKind.ROBOT:
                    self.viewer.set_robot_model_visible(node.node_id, node.visible)
            return
        if action_id in {
            "import_point_cloud",
            "import_cad",
            "import_robot",
        }:
            if action_id == "import_point_cloud":
                self.import_point_cloud()
            elif action_id == "import_cad":
                self.import_cad_model(NodeKind.CAD_MODEL)
            else:
                self.import_robot_urdf()
            return
        if action_id == "rename_node" and node is not None:
            self._rename_node_dialog(node)
            return
        if action_id == "delete_node" and node is not None:
            self._delete_node_confirm(node)
            return
        if action_id in {
            "set_point_cloud_pose",
            "set_cad_model_pose",
            "set_robot_pose",
            "process_point_cloud",
            "crop_point_cloud",
            "save_project",
            "forward_kinematics",
            "inverse_kinematics",
            "collision_check",
        }:
            self._begin_tree_operation(action_id, node)
            return
        if action_id in {"set_point_cloud_pose", "set_cad_model_pose", "set_robot_pose"} and node is not None:
            self.scene_tree.select_node(node.node_id)
            self.viewer.attach_model_manipulator(node.node_id)
            self._status_message.setText("拖动三轴箭头平移，拖动圆环旋转")
            return
        if action_id == "process_point_cloud" and node is not None:
            self.open_point_cloud_processing(node)
            return
        if action_id == "crop_point_cloud" and node is not None:
            self.start_point_cloud_crop(node)
            return
        self._reserved_action(action_id)

    def _rename_node_dialog(self, node: SceneNode) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "重命名节点",
            "节点名称：",
            QLineEdit.Normal,
            node.name,
        )
        if not accepted:
            return
        if not self.application.rename_node(node, name):
            QMessageBox.warning(self, "重命名失败", "名称不能为空，且项目根节点不能重命名。")
            return
        self.scene_tree.rebuild()
        self.scene_tree.select_node(node.node_id)
        self._update_window_title()
        self._status_message.setText(f"已重命名：{node.name}")

    def _delete_node_confirm(self, node: SceneNode) -> None:
        choice = QMessageBox.warning(
            self,
            "删除节点",
            f"确定删除节点“{node.name}”吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return
        self.viewer.detach_manipulator()
        if node.kind is NodeKind.POINT_CLOUD:
            self.viewer.remove_point_cloud(node.node_id)
        elif node.kind is NodeKind.CAD_MODEL:
            self.viewer.remove_cad_model(node.node_id)
        elif node.kind is NodeKind.ROBOT:
            self.viewer.remove_robot_model(node.node_id)
        if self.application.delete_node(node):
            self.scene_tree.rebuild()
            self._update_window_title()
            self._status_message.setText(f"已删除：{node.name}")

    def _begin_tree_operation(self, action_id: str, node: SceneNode | None) -> None:
        if action_id != "save_project" and node is None:
            return
        if self._processing_dialog is not None and action_id != "process_point_cloud":
            if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
                QMessageBox.information(self, "点云任务", "当前点云任务完成后才能切换操作。")
                return
            self._processing_dialog.reject()
        self._operation_node = node
        if action_id == "process_point_cloud" and node is not None:
            self._begin_processing_panel(node)
            return
        payload: dict[str, object] = {}
        if action_id == "forward_kinematics" and node is not None:
            payload["robot_data"] = self.robot_models.get(node.node_id)
            data = self.robot_models.get(node.node_id)
            if data is not None:
                self._pending_robot_kinematics = (
                    node.node_id, deepcopy(data.joint_positions), deepcopy(data.link_transforms)
                )
        title = {
            "set_point_cloud_pose": "设置点云位置",
            "set_cad_model_pose": "设置数模位置",
            "set_robot_pose": "设置机械臂位置",
            "process_point_cloud": "基本点云处理",
            "crop_point_cloud": "手动矩形裁剪",
            "rename_node": "重命名节点",
            "delete_node": "删除节点",
            "save_project": "保存项目",
            "forward_kinematics": "正运动学（预留）",
            "inverse_kinematics": "逆运动学（预留）",
            "collision_check": "碰撞检测（预留）",
        }[action_id]
        if action_id == "rename_node" and node is not None:
            payload["name"] = node.name
        if action_id in {"set_point_cloud_pose", "set_cad_model_pose", "set_robot_pose"} and node is not None:
            self._pending_pose = (
                node.node_id,
                deepcopy(node.metadata.get("transform")),
            )
            self._pending_pose_matrix = deepcopy(node.metadata.get("transform"))
            self.scene_tree.select_node(node.node_id)
            self.viewer.attach_model_manipulator(node.node_id)
        self.properties_dock.setWidget(self.operation_panel)
        self.operation_panel.begin(action_id, title, node, **payload)
        if action_id == "crop_point_cloud" and node is not None:
            self.start_point_cloud_crop(node)

    def _begin_processing_panel(self, node: SceneNode) -> None:
        if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
            QMessageBox.information(self, "点云任务", "已有点云任务正在执行，请稍候。")
            return
        data = self.point_clouds.get(node.node_id)
        if data is None:
            QMessageBox.warning(self, "点云尚未就绪", "该点云仍在加载或加载失败。")
            return
        if self._processing_dialog is not None:
            self._processing_dialog.raise_()
            self._processing_dialog.activateWindow()
            return

        dialog = PointCloudProcessingDialog(node.name, data.point_count, data.unit, self)
        dialog.preview_requested.connect(self._start_point_cloud_preview)
        dialog.preview_invalidated.connect(self._restore_processing_original)
        dialog.apply_requested.connect(self._apply_point_cloud_preview)
        dialog.finished.connect(self._on_processing_dialog_closed)
        dialog.setWindowFlags(Qt.Widget)
        dialog.setModal(False)
        dialog.layout().setContentsMargins(12, 12, 28, 12)
        scroll_area = ProcessingScrollArea(self.properties_dock)
        scroll_area.setObjectName("processingScrollArea")
        scroll_area.setWidgetResizable(False)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setWidget(dialog)
        QTimer.singleShot(0, scroll_area.fit_content_width)
        self._processing_scroll_area = scroll_area
        self.properties_dock.setWidget(scroll_area)
        self._processing_dialog = dialog
        self._processing_node_id = node.node_id
        self._processing_original = data
        self._processing_preview = None
        self._processing_applied = False
        self.scene_tree.select_node(node.node_id)
        dialog.show()

    def _on_operation_confirmed(self, action_id: str, payload: object) -> None:
        node = self._operation_node
        values = payload if isinstance(payload, dict) else {}
        if action_id == "save_project":
            if self.save_project():
                self._clear_operation()
                return
            return
        elif action_id in {"set_point_cloud_pose", "set_cad_model_pose", "set_robot_pose"} and node is not None:
            if self._pending_pose is not None and self._pending_pose[0] == node.node_id:
                matrix = self._pending_pose_matrix
                if matrix is not None:
                    self.application.update_transform(node.node_id, matrix)
            self.viewer.detach_manipulator()
            self._pending_pose = None
            self._pending_pose_matrix = None
        elif action_id == "forward_kinematics" and node is not None:
            data = self.robot_models.get(node.node_id)
            positions = values.get("joint_positions")
            if data is not None and isinstance(positions, dict):
                from laclean.services.urdf_robot_service import UrdfRobotService
                data.joint_positions = {str(name): float(value) for name, value in positions.items()}
                transforms = UrdfRobotService.forward_kinematics(data, data.joint_positions)
                data.link_transforms = transforms
                node.metadata["joint_positions"] = dict(data.joint_positions)
                node.metadata["link_transforms"] = transforms
                self.viewer.update_robot_kinematics(data, transforms, node.metadata.get("transform"))
                self.application.document.modified = True
            self._pending_robot_kinematics = None
        elif action_id == "process_point_cloud" and node is not None:
            self._clear_operation()
            self.open_point_cloud_processing(node)
            return
        elif action_id == "crop_point_cloud" and node is not None:
            if self._crop_selection is None:
                self.operation_panel.set_crop_status("请先完成矩形框选")
                return
            keep_selected = values.get("crop_mode") == "keep"
            self._start_crop_apply(keep_selected=keep_selected)
            return
        elif action_id in {"forward_kinematics", "inverse_kinematics", "collision_check"}:
            self._reserved_action(action_id)
        self._clear_operation()
        self._update_window_title()

    def _on_robot_joints_changed(self, positions: object) -> None:
        node = self._operation_node
        if node is None or node.kind is not NodeKind.ROBOT or not isinstance(positions, dict):
            return
        data = self.robot_models.get(node.node_id)
        if data is None:
            return
        from laclean.services.urdf_robot_service import UrdfRobotService
        transforms = UrdfRobotService.forward_kinematics(data, positions)
        self.viewer.update_robot_kinematics(data, transforms, node.metadata.get("transform"))
        self.operation_panel._payload["joint_positions"] = dict(positions)

    def _on_operation_cancelled(self) -> None:
        if self._crop_node_id is not None:
            node = self._crop_node()
            name = node.name if node is not None else "点云"
            self._finish_crop_session()
            self._clear_operation()
            self._status_message.setText(f"{name}：已取消矩形裁剪")
            return
        if self._pending_pose is not None:
            node_id, transform = self._pending_pose
            node = self.document.find(node_id)
            if node is not None and transform is not None:
                self.viewer.detach_manipulator()
                # The presentation is already in the viewer. Restoring its
                # transformation avoids rebuilding a potentially large cloud.
                restored = self.viewer.set_model_transform(node_id, transform)
                if not restored and node.kind is NodeKind.POINT_CLOUD and node_id in self.point_clouds:
                    # Keep a fallback for a presentation that disappeared
                    # while the operation was active.
                    self.viewer.display_point_cloud(
                        self.point_clouds[node_id],
                        visible=node.visible,
                        point_size=float(node.metadata.get("point_size", 4.0)),
                        transform=transform,
                        fit=False,
                    )
                elif not restored and node.kind is NodeKind.CAD_MODEL and node_id in self.cad_models:
                    self.viewer.display_cad_model(
                        self.cad_models[node_id],
                        visible=node.visible,
                        color=self._cad_display_color(node),
                        transform=transform,
                        fit=False,
                    )
                elif not restored and node.kind is NodeKind.ROBOT and node_id in self.robot_models:
                    self.viewer.display_robot_model(
                        self.robot_models[node_id], visible=node.visible,
                        transform=transform, fit=False,
                    )
            self._pending_pose = None
            self._pending_pose_matrix = None
        if self._pending_robot_kinematics is not None:
            node_id, positions, transforms = self._pending_robot_kinematics
            node = self.document.find(node_id)
            data = self.robot_models.get(node_id)
            if node is not None and data is not None:
                self.viewer.update_robot_kinematics(data, transforms, node.metadata.get("transform"))
            self._pending_robot_kinematics = None
        self._clear_operation()

    def _on_operation_pose_changed(self, matrix: object) -> None:
        if self._pending_pose is None:
            return
        node_id, _original = self._pending_pose
        self._pending_pose_matrix = deepcopy(matrix)
        self.viewer.set_model_transform(node_id, matrix)
        self._status_message.setText("位置参数已暂存，点击确认后写入项目")

    def _clear_operation(self) -> None:
        self._operation_node = None
        self.operation_panel.clear_operation()
        self.properties_dock.setWidget(self.properties)

    def open_point_cloud_processing(self, node: SceneNode) -> bool:
        if node.kind is not NodeKind.POINT_CLOUD:
            return False
        if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
            QMessageBox.information(self, "点云任务", "已有点云任务正在执行，请稍候。")
            return False
        data = self.point_clouds.get(node.node_id)
        if data is None:
            QMessageBox.warning(
                self,
                "点云尚未就绪",
                "该点云仍在加载或加载失败，暂时不能进行处理。",
            )
            return False
        if self._processing_dialog is not None:
            self._processing_dialog.raise_()
            self._processing_dialog.activateWindow()
            return False

        self.scene_tree.select_node(node.node_id)
        dialog = PointCloudProcessingDialog(
            node.name, data.point_count, data.unit, self
        )
        dialog.preview_requested.connect(self._start_point_cloud_preview)
        dialog.preview_invalidated.connect(self._restore_processing_original)
        dialog.apply_requested.connect(self._apply_point_cloud_preview)
        dialog.finished.connect(self._on_processing_dialog_closed)
        self._processing_dialog = dialog
        self._processing_node_id = node.node_id
        self._processing_original = data
        self._processing_preview = None
        self._processing_applied = False
        dialog.show()
        self._status_message.setText(f"{node.name}：设置算法参数后点击“预览”")
        return True

    def _start_point_cloud_preview(self, options: object) -> None:
        dialog = self._processing_dialog
        original = self._processing_original
        if dialog is None or original is None:
            return
        if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
            return

        dialog.set_busy(True, "正在计算预览…")
        task = PointCloudProcessThread(original, options, self)
        task.succeeded.connect(self._on_point_cloud_preview_ready)
        task.failed.connect(self._on_point_cloud_processing_failed)
        task.finished.connect(self._finish_point_cloud_task)
        self._point_cloud_task = task
        self._begin_point_cloud_task(f"正在处理点云：{original.name}")
        task.start()

    def _on_point_cloud_preview_ready(self, result: ProcessedPointCloud) -> None:
        node = self._processing_node()
        dialog = self._processing_dialog
        if node is None or dialog is None:
            return
        self._processing_preview = result
        self._display_processing_data(node, result.data)
        dialog.set_preview_result(result.summary)
        self._status_message.setText(
            f"预览：{result.summary.input_count:,} → {result.summary.output_count:,} 点；"
            "点击“应用结果”才会写入项目"
        )

    def _apply_point_cloud_preview(self) -> None:
        dialog = self._processing_dialog
        preview = self._processing_preview
        if dialog is None or preview is None:
            return
        if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
            return

        dialog.set_busy(True, "正在将处理结果写入项目资产…")
        task = PointCloudPersistThread(preview.data, self._asset_project_file_path(), self)
        task.succeeded.connect(self._on_point_cloud_result_persisted)
        task.failed.connect(self._on_point_cloud_processing_failed)
        task.finished.connect(self._finish_point_cloud_task)
        self._point_cloud_task = task
        self._begin_point_cloud_task(f"正在应用处理结果：{preview.data.name}")
        task.start()

    def _on_point_cloud_result_persisted(self, persisted: PersistedPointCloud) -> None:
        node = self._processing_node()
        preview = self._processing_preview
        dialog = self._processing_dialog
        if node is None or preview is None or dialog is None:
            return

        data = preview.data
        self.application.apply_processed_result(node, preview, persisted)
        self._processing_original = data
        self._processing_applied = True
        self._update_edit_actions()
        self._update_window_title()
        self._display_processing_data(node, data)
        if self._selected_node is node:
            self.properties.set_node(node)
        dialog.mark_applied()
        dialog.accept()
        self._status_message.setText(
            f"已应用点云处理：{preview.summary.input_count:,} → "
            f"{preview.summary.output_count:,} 点；按 Ctrl+S 保存项目"
        )

    def _on_point_cloud_processing_failed(self, message: str) -> None:
        dialog = self._processing_dialog
        self._restore_processing_original()
        if dialog is not None:
            dialog.show_error(message)
        self._status_message.setText("点云处理失败")

    def _restore_processing_original(self) -> None:
        node = self._processing_node()
        original = self._processing_original
        self._processing_preview = None
        if node is not None and original is not None:
            self._display_processing_data(node, original)
            self._status_message.setText(f"{node.name}：已取消处理预览")

    def _display_processing_data(self, node: SceneNode, data: PointCloudData) -> None:
        try:
            displayed = self.viewer.display_point_cloud(
                data,
                visible=node.visible,
                point_size=float(node.metadata.get("point_size", 4.0)),
                transform=node.metadata.get("transform"),
                fit=False,
            )
            if data is self.point_clouds.get(node.node_id):
                node.metadata["display_point_count"] = displayed
        except Exception as exc:
            QMessageBox.warning(
                self, "点云预览显示失败", log_exception("显示点云预览", exc)
            )

    def _processing_node(self) -> SceneNode | None:
        if self._processing_node_id is None:
            return None
        return self.document.find(self._processing_node_id)

    def _on_processing_dialog_closed(self, _result: int) -> None:
        if not self._processing_applied:
            self._restore_processing_original()
        self._processing_dialog = None
        self._processing_node_id = None
        self._processing_original = None
        self._processing_preview = None
        self._processing_applied = False
        self._operation_node = None
        if self.properties_dock.widget() is not self.properties:
            self.properties_dock.setWidget(self.properties)
        if self._processing_scroll_area is not None:
            self._processing_scroll_area.deleteLater()
            self._processing_scroll_area = None

    def start_point_cloud_crop(self, node: SceneNode) -> bool:
        if node.kind is not NodeKind.POINT_CLOUD:
            return False
        if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
            QMessageBox.information(self, "点云任务", "已有点云任务正在执行，请稍候。")
            return False
        if self._processing_dialog is not None:
            QMessageBox.information(self, "矩形裁剪", "请先关闭点云处理窗口。")
            return False
        data = self.point_clouds.get(node.node_id)
        if data is None:
            QMessageBox.warning(self, "点云尚未就绪", "该点云尚未加载，不能进行裁剪。")
            return False
        if not node.visible:
            QMessageBox.information(self, "矩形裁剪", "请先将点云设置为显示状态。")
            return False
        if self._crop_node_id is not None:
            self._finish_crop_session()

        self.scene_tree.select_node(node.node_id)
        self._crop_node_id = node.node_id
        self._crop_before_state = PointCloudEditState.capture(node, data)
        self._crop_selection = None
        if not self.viewer.start_rectangle_crop():
            self._finish_crop_session(reattach=False)
            QMessageBox.warning(self, "矩形裁剪", "三维视图尚未就绪。")
            return False
        self._status_message.setText(
            "矩形框选：按住左键拖动；默认穿透选择；右键或 Esc 取消"
        )
        return True

    def _on_crop_rectangle_drawn(self, rectangle: object) -> None:
        node = self._crop_node()
        if node is None:
            self._finish_crop_session()
            return
        data = self.point_clouds.get(node.node_id)
        if data is None:
            self._finish_crop_session()
            return
        try:
            view_projection, viewport_size = self.viewer.capture_projection_state()
            rect = tuple(int(value) for value in rectangle)
            if len(rect) != 4:
                raise ValueError("矩形坐标无效")
        except Exception as exc:
            self._finish_crop_session()
            QMessageBox.warning(
                self, "矩形框选失败", log_exception("准备矩形框选", exc)
            )
            return

        task = PointCloudRectangleSelectionThread(
            data,
            rect,
            view_projection,
            viewport_size,
            node.metadata.get("transform"),
            self,
        )
        task.succeeded.connect(self._on_rectangle_selection_ready)
        task.failed.connect(self._on_point_cloud_crop_failed)
        task.finished.connect(self._finish_point_cloud_task)
        self._point_cloud_task = task
        self._begin_point_cloud_task(f"正在穿透框选：{node.name}")
        task.start()

    def _on_rectangle_selection_ready(self, selection: RectangleSelection) -> None:
        node = self._crop_node()
        if node is None:
            return
        self._crop_selection = selection
        if selection.selected_count == 0:
            self.operation_panel.set_crop_selection(
                selection.selected_count, selection.total_count
            )
            self.operation_panel.set_crop_status("矩形范围内没有点，请重新绘制")
            self.viewer.start_rectangle_crop()
            return

        self.operation_panel.set_crop_selection(
            selection.selected_count, selection.total_count
        )
        self._status_message.setText(
            f"{node.name}：矩形框选完成，请在右侧面板确认裁剪方式"
        )

    def _start_crop_apply(self, *, keep_selected: bool) -> None:
        node = self._crop_node()
        selection = self._crop_selection
        if (
            node is None
            or selection is None
            or (self._point_cloud_task is not None and self._point_cloud_task.isRunning())
        ):
            return
        data = self.point_clouds.get(node.node_id)
        if data is None:
            return
        self.viewer.cancel_rectangle_crop(emit_signal=False)

        task = PointCloudCropPersistThread(
            data,
            selection,
            keep_selected,
            self._asset_project_file_path(),
            self,
        )
        task.succeeded.connect(self._on_point_cloud_crop_applied)
        task.failed.connect(self._on_point_cloud_crop_failed)
        task.finished.connect(self._finish_point_cloud_task)
        self._point_cloud_task = task
        action = "保留框内" if keep_selected else "删除框内"
        self._begin_point_cloud_task(f"正在应用矩形裁剪（{action}）：{node.name}")
        task.start()

    def _on_point_cloud_crop_applied(
        self, cropped: object, persisted: PersistedPointCloud
    ) -> None:
        node = self._crop_node()
        before = self._crop_before_state
        if node is None or before is None:
            return
        command, trimmed_commands = self.application.apply_cropped_result(
            node, before, cropped, persisted
        )
        command_text = command.text
        self._display_processing_data(node, cropped.data)
        self._update_edit_actions()
        self._finish_crop_session()
        self._clear_operation()
        memory_note = (
            f"；为控制内存已释放 {trimmed_commands} 条较早历史"
            if trimmed_commands
            else f"；撤销缓存 {format_bytes(self._edit_history.memory_bytes)}"
        )
        self._status_message.setText(
            f"{command_text}：选中 {cropped.selected_count:,} 点，"
            f"结果保留 {cropped.kept_count:,} 点；可按 Ctrl+Z 撤销{memory_note}"
        )

    def _on_point_cloud_crop_failed(self, message: str) -> None:
        self.operation_panel.set_crop_status(message)
        self._status_message.setText("矩形裁剪失败")

    def _on_crop_cancelled(self) -> None:
        node = self._crop_node()
        name = node.name if node is not None else "点云"
        self._finish_crop_session()
        self._clear_operation()
        self._status_message.setText(f"{name}：已取消矩形框选")

    def _on_crop_redraw_requested(self) -> None:
        node = self._crop_node()
        if node is None or (
            self._point_cloud_task is not None and self._point_cloud_task.isRunning()
        ):
            return
        self._crop_selection = None
        self.operation_panel.reset_crop_selection()
        if self.viewer.start_rectangle_crop():
            self._status_message.setText("矩形框选：请重新按住左键拖动")

    def _crop_node(self) -> SceneNode | None:
        if self._crop_node_id is None:
            return None
        return self.document.find(self._crop_node_id)

    def _finish_crop_session(self, *, reattach: bool = True) -> None:
        self.viewer.cancel_rectangle_crop(emit_signal=False)
        self._crop_node_id = None
        self._crop_before_state = None
        self._crop_selection = None

    def undo_edit(self) -> bool:
        if not self._can_run_edit_history_action():
            return False
        command = self.application.undo_edit()
        if command is None:
            return False
        node = self.document.find(command.node_id)
        if node is None or node.kind is not NodeKind.POINT_CLOUD:
            self.application.edit_history.clear()
            self._update_edit_actions()
            return False
        self.application.apply_edit_state(node, command.before)
        self._display_processing_data(node, command.before.data)
        self._update_edit_actions()
        self._status_message.setText(f"已撤销：{command.text}")
        return True

    def redo_edit(self) -> bool:
        if not self._can_run_edit_history_action():
            return False
        command = self.application.redo_edit()
        if command is None:
            return False
        node = self.document.find(command.node_id)
        if node is None or node.kind is not NodeKind.POINT_CLOUD:
            self.application.edit_history.clear()
            self._update_edit_actions()
            return False
        self.application.apply_edit_state(node, command.after)
        self._display_processing_data(node, command.after.data)
        self._update_edit_actions()
        self._status_message.setText(f"已重做：{command.text}")
        return True

    def _can_run_edit_history_action(self) -> bool:
        if self._point_cloud_task is not None:
            return False
        if self._processing_dialog is not None:
            QMessageBox.information(self, "撤销/重做", "请先关闭点云处理窗口。")
            return False
        if self._crop_node_id is not None:
            self._finish_crop_session()
        return True

    def _apply_point_cloud_edit_state(
        self, node: SceneNode, state: PointCloudEditState
    ) -> None:
        self.application.apply_edit_state(node, state)
        self._display_processing_data(node, state.data)
        self._update_window_title()
        if self._selected_node is node:
            self.properties.set_node(node)

    def _update_edit_actions(self) -> None:
        if not hasattr(self, "actions") or "undo" not in self.actions:
            return
        busy = self._point_cloud_task is not None
        undo_text = self._edit_history.undo_text
        redo_text = self._edit_history.redo_text
        self.actions["undo"].setEnabled(bool(undo_text) and not busy)
        self.actions["redo"].setEnabled(bool(redo_text) and not busy)
        self.actions["undo"].setText(f"撤销 {undo_text}" if undo_text else "撤销")
        self.actions["redo"].setText(f"重做 {redo_text}" if redo_text else "重做")

    def import_cad_model(self, node_kind: NodeKind = NodeKind.CAD_MODEL) -> bool:
        if node_kind is not NodeKind.CAD_MODEL:
            return False
        if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
            QMessageBox.information(self, "后台任务", "已有导入或处理任务正在执行，请稍候。")
            return False
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_CAD_SUFFIXES))
        title = "导入 STEP 数模"
        start_directory = (
            str(Path(self.document.file_path).parent)
            if self.document.file_path
            else str(Path.cwd())
        )
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            start_directory,
            f"STEP 文件 ({suffixes});;所有文件 (*)",
        )
        if not source_path:
            return False

        task = CadModelImportThread(
            source_path, self._asset_project_file_path(), node_kind, self
        )
        task.succeeded.connect(self._on_cad_model_imported)
        task.failed.connect(self._on_cad_model_task_failed)
        task.finished.connect(self._finish_point_cloud_task)
        self._point_cloud_task = task
        self._begin_point_cloud_task(f"正在解析 STEP：{Path(source_path).name}")
        task.start()
        return True

    def import_robot_urdf(self) -> bool:
        if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
            QMessageBox.information(self, "后台任务", "已有导入或处理任务正在执行，请稍候。")
            return False
        start_directory = str(Path(self.document.file_path).parent) if self.document.file_path else str(Path.cwd())
        source_path, _ = QFileDialog.getOpenFileName(
            self, "导入机械臂 URDF", start_directory,
            "URDF 文件 (*.urdf);;所有文件 (*)",
        )
        if not source_path:
            return False
        task = UrdfRobotImportThread(source_path, self._asset_project_file_path(), self)
        task.succeeded.connect(self._on_robot_imported)
        task.failed.connect(self._on_robot_task_failed)
        task.finished.connect(self._finish_point_cloud_task)
        self._point_cloud_task = task
        self._begin_point_cloud_task(f"正在解析机械臂 URDF：{Path(source_path).name}")
        task.start()
        return True

    def _on_robot_imported(self, result: ImportedRobotModel) -> None:
        if not self.application.add_cad_model(result.node, result.data):
            QMessageBox.critical(self, "导入 URDF 失败", "项目缺少机械臂对象组。")
            return
        try:
            self.viewer.display_robot_model(result.data, visible=result.node.visible,
                                            transform=result.node.metadata.get("transform"))
        except Exception as exc:
            QMessageBox.warning(self, "URDF 显示失败", f"机械臂已加入项目，但三维显示失败：\n{log_exception('显示 URDF', exc)}")
        self._update_window_title()
        self.scene_tree.rebuild()
        self.scene_tree.select_node(result.node.node_id)
        self._status_message.setText(f"已导入机械臂 {result.node.name} · {result.data.link_count} 个 link · {result.data.joint_count} 个 joint")

    def _on_robot_task_failed(self, message: str) -> None:
        self._status_message.setText("机械臂 URDF 导入失败")
        QMessageBox.critical(self, "导入机械臂 URDF 失败", message)

    def _on_cad_model_imported(self, result: ImportedCadModel) -> None:
        if not self.application.add_cad_model(result.node, result.data):
            QMessageBox.critical(self, "导入 STEP 失败", "项目缺少目标模型对象组。")
            return
        try:
            self.viewer.display_cad_model(
                result.data,
                visible=result.node.visible,
                color=self._cad_display_color(result.node),
                transform=result.node.metadata.get("transform"),
            )
        except Exception as exc:
            detail = log_exception("显示 STEP", exc)
            QMessageBox.warning(
                self,
                "STEP 显示失败",
                f"模型已复制并加入项目，但三维显示失败：\n{detail}",
            )

        self._update_window_title()
        self.scene_tree.rebuild()
        self.scene_tree.select_node(result.node.node_id)
        self._status_message.setText(
            f"已导入 {result.node.name} · {result.data.solid_count:,} 实体 · "
            f"{result.data.face_count:,} 面"
        )

    def _on_cad_model_task_failed(self, message: str) -> None:
        self._status_message.setText("STEP 导入失败")
        QMessageBox.critical(self, "STEP 导入失败", message)

    def import_point_cloud(self) -> bool:
        if self._point_cloud_task is not None and self._point_cloud_task.isRunning():
            QMessageBox.information(self, "点云任务", "已有点云任务正在执行，请稍候。")
            return False

        suffixes = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_POINT_CLOUD_SUFFIXES))
        start_directory = (
            str(Path(self.document.file_path).parent)
            if self.document.file_path
            else str(Path.cwd())
        )
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入点云",
            start_directory,
            f"点云文件 ({suffixes});;所有文件 (*)",
        )
        if not source_path:
            return False

        task = PointCloudImportThread(source_path, self._asset_project_file_path(), self)
        task.succeeded.connect(self._on_point_cloud_imported)
        task.failed.connect(self._on_point_cloud_task_failed)
        task.finished.connect(self._finish_point_cloud_task)
        self._point_cloud_task = task
        self._begin_point_cloud_task(f"正在导入点云：{Path(source_path).name}")
        task.start()
        return True

    def _on_point_cloud_imported(self, result: ImportedPointCloud) -> None:
        if not self.application.add_point_cloud(result.node, result.data):
            QMessageBox.critical(self, "导入点云失败", "项目缺少点云对象组。")
            return
        try:
            displayed = self.viewer.display_point_cloud(
                result.data,
                visible=result.node.visible,
                point_size=float(result.node.metadata.get("point_size", 4.0)),
                transform=result.node.metadata.get("transform"),
            )
            result.node.metadata["display_point_count"] = displayed
        except Exception as exc:
            detail = log_exception("显示导入点云", exc)
            QMessageBox.warning(
                self,
                "点云显示失败",
                f"点云已复制并加入项目，但三维显示失败：\n{detail}",
            )

        self._update_window_title()
        self.scene_tree.rebuild()
        self.scene_tree.select_node(result.node.node_id)
        self._status_message.setText(
            f"已导入 {result.node.name} · {result.data.point_count:,} 点"
        )

    def _restore_project_assets(self) -> None:
        if self._point_cloud_nodes():
            self._restore_project_point_clouds()
        else:
            self._restore_project_cad_models()

    def _restore_project_point_clouds(self) -> None:
        if self.document.file_path is None:
            return
        nodes = self._point_cloud_nodes()
        if not nodes:
            return

        task = PointCloudRestoreThread(nodes, self.document.file_path, self)
        task.succeeded.connect(self._on_point_clouds_restored)
        task.finished.connect(self._finish_point_cloud_restore)
        self._point_cloud_task = task
        self._begin_point_cloud_task(f"正在恢复项目点云（{len(nodes)}）")
        task.start()

    def _finish_point_cloud_restore(self) -> None:
        self._finish_point_cloud_task()
        QTimer.singleShot(0, self._restore_project_cad_models)

    def _on_point_clouds_restored(self, loaded: list, errors: list) -> None:
        render_errors = []
        for node, data in loaded:
            self.application.register_point_cloud(node, data)
            node.metadata["memory_bytes"] = data.memory_bytes
            try:
                displayed = self.viewer.display_point_cloud(
                    data,
                    visible=node.visible,
                    point_size=float(node.metadata.get("point_size", 4.0)),
                    transform=node.metadata.get("transform"),
                    fit=False,
                )
                node.metadata["display_point_count"] = displayed
            except Exception as exc:
                render_errors.append(
                    f"{node.name}：{log_exception('恢复点云显示', exc)}"
                )
        if loaded:
            self.viewer.fit_all()
        all_errors = [*errors, *render_errors]
        if all_errors:
            QMessageBox.warning(
                self,
                "部分点云未能恢复",
                "\n\n".join(all_errors),
            )
        self._status_message.setText(f"已恢复 {len(loaded)} 个点云")

    def _restore_project_cad_models(self) -> None:
        if self.document.file_path is None or self._point_cloud_task is not None:
            return
        nodes = self._cad_model_nodes()
        if not nodes:
            QTimer.singleShot(0, self._restore_project_robots)
            return
        task = CadModelRestoreThread(nodes, self.document.file_path, self)
        task.succeeded.connect(self._on_cad_models_restored)
        task.finished.connect(self._finish_point_cloud_task)
        self._point_cloud_task = task
        self._begin_point_cloud_task(f"正在恢复 STEP 模型（{len(nodes)}）")
        task.start()

    def _on_cad_models_restored(self, loaded: list, errors: list) -> None:
        render_errors = []
        for node, data in loaded:
            self.application.register_cad_model(node, data)
            try:
                self.viewer.display_cad_model(
                    data,
                    visible=node.visible,
                    color=self._cad_display_color(node),
                    transform=node.metadata.get("transform"),
                    fit=False,
                )
            except Exception as exc:
                render_errors.append(
                    f"{node.name}：{log_exception('恢复 STEP 显示', exc)}"
                )
        if loaded:
            self.viewer.fit_all()
        all_errors = [*errors, *render_errors]
        if all_errors:
            QMessageBox.warning(self, "部分 STEP 模型未能恢复", "\n\n".join(all_errors))
        self._status_message.setText(f"已恢复 {len(loaded)} 个 STEP 模型")
        QTimer.singleShot(0, self._restore_project_robots)

    def _restore_project_robots(self) -> None:
        if self.document.file_path is None or self._point_cloud_task is not None:
            return
        nodes = self.application.robot_model_nodes()
        if not nodes:
            return
        task = UrdfRobotRestoreThread(nodes, self.document.file_path, self)
        task.succeeded.connect(self._on_robot_models_restored)
        task.finished.connect(self._finish_point_cloud_task)
        self._point_cloud_task = task
        self._begin_point_cloud_task(f"正在恢复 URDF 机械臂（{len(nodes)}）")
        task.start()

    def _on_robot_models_restored(self, loaded: list, errors: list) -> None:
        render_errors = []
        for node, data in loaded:
            self.application.register_robot_model(node, data)
            try:
                self.viewer.display_robot_model(data, visible=node.visible,
                                                transform=node.metadata.get("transform"), fit=False)
            except Exception as exc:
                render_errors.append(f"{node.name}：{log_exception('恢复 URDF 显示', exc)}")
        if loaded:
            self.viewer.fit_all()
        all_errors = [*errors, *render_errors]
        if all_errors:
            QMessageBox.warning(self, "部分机械臂未能恢复", "\n\n".join(all_errors))
        self._status_message.setText(f"已恢复 {len(loaded)} 个 URDF 机械臂")

    def _point_cloud_group(self) -> SceneNode | None:
        return self.application.point_cloud_group()

    def _point_cloud_nodes(self) -> list[SceneNode]:
        return self.application.point_cloud_nodes()

    def _cad_model_group(self) -> SceneNode | None:
        return self.application.cad_model_group()

    def _robot_group(self) -> SceneNode | None:
        return self.application.robot_group()

    def _cad_model_nodes(self) -> list[SceneNode]:
        return self.application.cad_model_nodes()

    def _robot_model_nodes(self) -> list[SceneNode]:
        return self.application.robot_model_nodes()

    @staticmethod
    def _cad_display_color(node: SceneNode) -> tuple[float, float, float]:
        value = node.metadata.get("display_color", [0.72, 0.76, 0.82])
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return (0.72, 0.76, 0.82)
        try:
            return tuple(float(component) for component in value)
        except (TypeError, ValueError):
            return (0.72, 0.76, 0.82)

    def _begin_point_cloud_task(self, message: str) -> None:
        self.actions["import_point_cloud"].setEnabled(False)
        self.actions["import_cad"].setEnabled(False)
        self.actions["import_robot"].setEnabled(False)
        self._update_edit_actions()
        self._task_progress.show()
        self._status_message.setText(message)

    def _finish_point_cloud_task(self) -> None:
        task = self._point_cloud_task
        self._point_cloud_task = None
        self.actions["import_point_cloud"].setEnabled(True)
        self.actions["import_cad"].setEnabled(True)
        self.actions["import_robot"].setEnabled(True)
        self._task_progress.hide()
        if self._processing_dialog is not None:
            self._processing_dialog.set_busy(False)
        self._update_edit_actions()
        if task is not None:
            task.deleteLater()

    def _on_point_cloud_task_failed(self, message: str) -> None:
        self._status_message.setText("点云导入失败")
        QMessageBox.critical(self, "点云导入失败", message)

    def _on_manipulator_transform_changed(self, node_id: str, matrix: object) -> None:
        try:
            node_id_value = UUID(node_id)
        except ValueError:
            return
        if self._pending_pose is not None and self._pending_pose[0] == node_id_value:
            self._pending_pose_matrix = deepcopy(matrix)
            self.operation_panel.set_pose_matrix(matrix)
            from laclean.core.transforms import pose_from_matrix

            translation, rotation = pose_from_matrix(matrix)
            self._status_message.setText(
                "暂存位置 "
                f"X {translation[0]:.2f}  Y {translation[1]:.2f}  Z {translation[2]:.2f} mm · "
                "旋转 "
                f"Rx {rotation[0]:.2f}°  Ry {rotation[1]:.2f}°  Rz {rotation[2]:.2f}°"
            )
            return
        node = self.application.update_transform(node_id_value, matrix)
        if node is None:
            return
        self._update_window_title()
        if self._selected_node is node:
            self.properties.set_node(node)

        from laclean.core.transforms import pose_from_matrix

        translation, rotation = pose_from_matrix(matrix)
        self._status_message.setText(
            "位置 "
            f"X {translation[0]:.2f}  Y {translation[1]:.2f}  Z {translation[2]:.2f} mm · "
            "旋转 "
            f"Rx {rotation[0]:.2f}°  Ry {rotation[1]:.2f}°  Rz {rotation[2]:.2f}°"
        )

    def _reserved_action(self, action_id: str) -> None:
        labels = {
            "capture": "拍照",
            "camera_connection": "相机通讯",
            "import_point_cloud": "导入点云",
            "import_cad": "导入数模",
            "path_parameters": "路径参数设置",
            "generate_path": "路径生成",
            "robot_connection": "机械臂通讯",
            "galvo_connection": "振镜通讯",
            "undo": "撤销",
            "redo": "重做",
            "set_point_cloud_pose": "设置点云位置",
            "set_cad_model_pose": "设置数模位置",
            "process_point_cloud": "基本点云处理",
            "crop_point_cloud": "手动矩形裁剪",
            "forward_kinematics": "正运动学",
            "inverse_kinematics": "逆运动学",
            "collision_check": "碰撞检测",
            "rename_node": "重命名",
            "delete_node": "删除节点",
        }
        label = labels.get(action_id, action_id)
        self._status_message.setText(f"{label}：接口已预留")
        QMessageBox.information(self, label, f"“{label}”接口已预留，将在后续阶段实现。")

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 Laclean Studio",
            "<b>Laclean Studio 0.1.0</b><br><br>"
            "激光清洗机械臂离线编程平台",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        if self._confirm_close_current_project():
            self._cleanup_scratch_project_directory()
            event.accept()
        else:
            event.ignore()
