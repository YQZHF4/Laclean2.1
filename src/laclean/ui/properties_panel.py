"""Selection-aware property summary panel."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSizePolicy,
    QScrollArea,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from laclean.core.scene import NodeKind, SceneNode
from laclean.core.error_handling import format_bytes
from laclean.core.transforms import matrix_from_pose, pose_from_matrix


KIND_NAMES = {
    NodeKind.PROJECT: "项目",
    NodeKind.GROUP: "对象组",
    NodeKind.POINT_CLOUD: "点云",
    NodeKind.CAD_MODEL: "数模",
    NodeKind.ROBOT: "机械臂",
    NodeKind.TOOL: "工具/振镜",
    NodeKind.COORDINATE_FRAME: "坐标系",
    NodeKind.PATH: "路径",
}


class OperationPanel(QFrame):
    """Reusable confirmation surface for one pending tree operation."""

    confirmed = pyqtSignal(str, object)
    cancelled = pyqtSignal()
    pose_changed = pyqtSignal(object)
    robot_joints_changed = pyqtSignal(object)
    crop_redraw_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("operationPanel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._action_id = ""
        self._payload: dict[str, object] = {}
        self._pose_editors: list[QDoubleSpinBox] = []
        self._crop_status: QLabel | None = None
        self._crop_selected: QLabel | None = None
        self._crop_redraw: QPushButton | None = None
        self._crop_mode_group: QButtonGroup | None = None
        self._form = QVBoxLayout(self)
        self._form.setContentsMargins(12, 12, 12, 12)
        self._form.setSpacing(8)
        self._form.setAlignment(Qt.AlignTop)

        self._title = QLabel("当前操作")
        self._title.setProperty("section", True)
        self._target = QLabel("—")
        self._target.setWordWrap(True)
        self._body = QVBoxLayout()
        self._body.setAlignment(Qt.AlignTop)
        body_host = QWidget()
        body_host.setObjectName("operationBody")
        body_host.setAutoFillBackground(True)
        body_host.setLayout(self._body)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("operationScrollArea")
        self._scroll.setAutoFillBackground(True)
        self._scroll.viewport().setObjectName("operationViewport")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setViewportMargins(0, 0, 18, 0)
        self._scroll.setWidget(body_host)
        self._buttons = QHBoxLayout()
        self._confirm = QPushButton("确认")
        self._confirm.setProperty("accent", True)
        self._cancel = QPushButton("取消")
        self._buttons.addStretch(1)
        self._buttons.addWidget(self._cancel)
        self._buttons.addWidget(self._confirm)
        self._form.addWidget(self._title)
        self._form.addWidget(self._target)
        self._form.addWidget(self._scroll, 1)
        self._form.addLayout(self._buttons)
        self._confirm.clicked.connect(self._emit_confirmed)
        self._cancel.clicked.connect(self.cancelled)
        self.hide()

    @property
    def action_id(self) -> str:
        return self._action_id

    def begin(self, action_id: str, title: str, node: SceneNode | None, **payload) -> None:
        self._action_id = str(action_id)
        self._payload = dict(payload)
        self._pose_editors = []
        self._crop_status = None
        self._crop_selected = None
        self._crop_redraw = None
        self._crop_mode_group = None
        self._title.setText(title)
        self._target.setText(
            f"目标：{node.name}（{KIND_NAMES.get(node.kind, node.kind.value)}）"
            if node is not None
            else "目标：当前项目"
        )
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if action_id == "rename_node":
            editor = QLineEdit(str(payload.get("name", node.name if node else "")))
            editor.setObjectName("operationNameEdit")
            self._body.addWidget(QLabel("名称"))
            self._body.addWidget(editor)
            self._payload["name_editor"] = editor
        elif action_id in {"set_point_cloud_pose", "set_cad_model_pose", "set_robot_pose"}:
            hint = QLabel("拖动三维场景中的箭头平移、圆环旋转，也可以直接编辑下方数值。")
            hint.setWordWrap(True)
            hint.setMinimumWidth(0)
            hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self._body.addWidget(hint)
            try:
                translation, rotation = pose_from_matrix(node.metadata.get("transform"))
            except (AttributeError, TypeError, ValueError):
                translation = (0.0, 0.0, 0.0)
                rotation = (0.0, 0.0, 0.0)
            self._add_pose_editors(translation, rotation)
        elif action_id == "forward_kinematics":
            robot = payload.get("robot_data")
            joints = getattr(robot, "joints", [])
            if not joints:
                self._body.addWidget(QLabel("该机械臂没有可控制的关节。"))
            for joint in joints:
                if joint.joint_type == "fixed":
                    continue
                self._add_joint_editor(joint, float(getattr(robot, "joint_positions", {}).get(joint.name, 0.0)))
            self._body.addStretch(1)
        elif action_id in {"import_point_cloud", "import_cad", "import_robot"}:
            self._add_readonly_value("待导入文件", str(payload.get("path", "—")))
            self._add_readonly_value("格式", str(payload.get("format", "—")))
        elif action_id == "crop_point_cloud":
            hint = QLabel("已进入矩形框选模式。按住左键拖动绘制矩形，右键或 Esc 取消框选。")
            hint.setWordWrap(True)
            hint.setMinimumWidth(0)
            hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self._body.addWidget(hint)
            self._crop_status = QLabel("状态：等待绘制矩形")
            self._crop_selected = QLabel("选中点数：尚未完成框选")
            self._body.addWidget(self._crop_status)
            self._body.addWidget(self._crop_selected)
            self._body.addWidget(QLabel("裁剪方式"))
            mode_group = QButtonGroup(self)
            mode_group.setExclusive(True)
            keep_box = QCheckBox("保留框内")
            delete_box = QCheckBox("删除框内")
            keep_box.setChecked(True)
            mode_group.addButton(keep_box, 0)
            mode_group.addButton(delete_box, 1)
            mode_layout = QHBoxLayout()
            mode_layout.addWidget(keep_box)
            mode_layout.addWidget(delete_box)
            mode_layout.addStretch(1)
            self._body.addLayout(mode_layout)
            self._crop_mode_group = mode_group
            self._crop_redraw = QPushButton("重新绘制")
            self._crop_redraw.clicked.connect(self.crop_redraw_requested)
            self._body.addWidget(self._crop_redraw)
        elif action_id == "process_point_cloud":
            self._body.addWidget(QLabel("确认后打开点云处理参数面板，取消不执行处理。"))
        elif action_id == "delete_node":
            self._body.addWidget(QLabel("确认后将删除该节点及其三维显示，操作不可直接恢复。"))
        elif action_id == "save_project":
            self._add_readonly_value("项目", node.name if node is not None else "当前项目")
            self._add_readonly_value("状态", "存在未保存修改")
        else:
            self._body.addWidget(QLabel("该功能当前为预留接口。点击确认后仅显示提示，不修改项目。"))
        self.show()

    def set_crop_selection(self, selected_count: int, total_count: int) -> None:
        if self._crop_status is not None:
            self._crop_status.setText("状态：矩形框选完成，可确认裁剪或重新绘制")
        if self._crop_selected is not None:
            self._crop_selected.setText(
                f"选中点数：{int(selected_count):,} / {int(total_count):,}"
            )

    def set_crop_status(self, text: str) -> None:
        if self._crop_status is not None:
            self._crop_status.setText(f"状态：{text}")

    def reset_crop_selection(self) -> None:
        if self._crop_status is not None:
            self._crop_status.setText("状态：等待重新绘制矩形")
        if self._crop_selected is not None:
            self._crop_selected.setText("选中点数：尚未完成框选")

    def _add_pose_editors(self, translation, rotation) -> None:
        self._pose_editors = []
        for title, axes, values, suffix in (
            ("世界坐标 XYZ（mm）", ("X", "Y", "Z"), translation, " mm"),
            ("旋转 Rx/Ry/Rz（°）", ("Rx", "Ry", "Rz"), rotation, "°"),
        ):
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(12, 10, 12, 10)
            group_layout.setSpacing(7)
            for axis, value in zip(axes, values):
                row = QHBoxLayout()
                row.setSpacing(8)
                axis_label = QLabel(axis)
                axis_label.setFixedWidth(30)
                row.addWidget(axis_label)
                editor = QDoubleSpinBox()
                editor.setRange(-1_000_000_000.0, 1_000_000_000.0)
                editor.setDecimals(3)
                editor.setSingleStep(1.0)
                editor.setValue(float(value))
                editor.setSuffix(suffix)
                editor.setKeyboardTracking(False)
                editor.setMinimumWidth(0)
                editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                editor.valueChanged.connect(self._emit_pose_changed)
                self._pose_editors.append(editor)
                row.addWidget(editor, 1)
                group_layout.addLayout(row)
            self._body.addWidget(group)

    def _add_joint_editor(self, joint, value: float) -> None:
        group = QGroupBox(f"{joint.name} · {joint.joint_type}")
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        editor = QDoubleSpinBox()
        slider = QSlider(Qt.Horizontal)
        if joint.joint_type in {"revolute", "continuous"}:
            lower = -180.0 if joint.lower is None else joint.lower * 180.0 / 3.141592653589793
            upper = 180.0 if joint.upper is None else joint.upper * 180.0 / 3.141592653589793
            shown = value * 180.0 / 3.141592653589793
            suffix = " °"
        else:
            lower = -1000.0 if joint.lower is None else joint.lower * 1000.0
            upper = 1000.0 if joint.upper is None else joint.upper * 1000.0
            shown = value * 1000.0
            suffix = " mm"
        lower, upper = min(lower, upper), max(lower, upper)
        editor.setRange(lower, upper)
        editor.setDecimals(3)
        editor.setSuffix(suffix)
        editor.setValue(shown)
        editor.setKeyboardTracking(False)
        slider.setRange(-100000, 100000)
        slider.setValue(round((shown - lower) / (upper - lower or 1.0) * 200000 - 100000))
        row.addWidget(editor, 1)
        row.addWidget(slider, 2)
        layout.addLayout(row)
        self._body.addWidget(group)
        def emit_editor(new_value):
            blocked = slider.blockSignals(True)
            slider.setValue(round((editor.value() - lower) / (upper - lower or 1.0) * 200000 - 100000))
            slider.blockSignals(blocked)
            self._emit_robot_joints()
        def emit_slider(new_value):
            blocked = editor.blockSignals(True)
            editor.setValue(lower + (upper - lower) * (new_value + 100000) / 200000)
            editor.blockSignals(blocked)
            self._emit_robot_joints()
        editor.valueChanged.connect(emit_editor)
        slider.valueChanged.connect(emit_slider)
        self._payload.setdefault("joint_editors", {})[joint.name] = (editor, joint.joint_type)

    def _emit_robot_joints(self) -> None:
        values = {}
        for name, (editor, joint_type) in self._payload.get("joint_editors", {}).items():
            value = editor.value()
            values[name] = value * 3.141592653589793 / 180.0 if joint_type in {"revolute", "continuous"} else value / 1000.0
        self.robot_joints_changed.emit(values)

    def set_pose_matrix(self, matrix: object) -> None:
        if len(self._pose_editors) != 6:
            return
        try:
            translation, rotation = pose_from_matrix(matrix)
        except (TypeError, ValueError):
            return
        for editor, value in zip(self._pose_editors, (*translation, *rotation)):
            blocked = editor.blockSignals(True)
            editor.setValue(float(value))
            editor.blockSignals(blocked)

    def _emit_pose_changed(self, _value: float) -> None:
        if len(self._pose_editors) != 6:
            return
        values = [editor.value() for editor in self._pose_editors]
        self.pose_changed.emit(matrix_from_pose(values[:3], values[3:]).tolist())

    def _add_readonly_value(self, label: str, value: str) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        value_label = QLabel(value)
        value_label.setWordWrap(True)
        row.addWidget(value_label, 1)
        self._body.addLayout(row)

    def _emit_confirmed(self) -> None:
        payload = dict(self._payload)
        editor = payload.pop("name_editor", None)
        if isinstance(editor, QLineEdit):
            payload["name"] = editor.text()
        if self._crop_mode_group is not None:
            payload["crop_mode"] = (
                "keep" if self._crop_mode_group.checkedId() == 0 else "delete"
            )
        self.confirmed.emit(self._action_id, payload)

    def clear_operation(self) -> None:
        self._action_id = ""
        self._payload.clear()
        self.hide()


class PropertiesPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("propertiesPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setObjectName("propertiesScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll)

        content = QWidget(scroll)
        content.setObjectName("propertiesContent")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(12, 12, 12, 12)
        self._content_layout.setSpacing(12)
        scroll.setWidget(content)

        title = QLabel("对象属性")
        title.setProperty("section", True)
        self._content_layout.addWidget(title)

        self._summary_card = QFrame()
        self._summary_card.setProperty("card", True)
        summary_layout = QFormLayout(self._summary_card)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setVerticalSpacing(10)
        summary_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        summary_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._name = QLabel("—")
        self._kind = QLabel("—")
        self._state = QLabel("—")
        self._id = QLabel("—")
        self._id.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._id.setWordWrap(True)
        summary_layout.addRow("名称", self._name)
        summary_layout.addRow("类型", self._kind)
        summary_layout.addRow("状态", self._state)
        summary_layout.addRow("标识", self._id)
        self._content_layout.addWidget(self._summary_card)

        self._point_cloud_card = QFrame()
        self._point_cloud_card.setProperty("card", True)
        point_cloud_layout = QFormLayout(self._point_cloud_card)
        point_cloud_layout.setContentsMargins(12, 12, 12, 12)
        point_cloud_layout.setVerticalSpacing(9)
        point_cloud_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        point_cloud_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._cloud_source = QLabel("—")
        self._cloud_source.setWordWrap(True)
        self._cloud_asset = QLabel("—")
        self._cloud_asset.setWordWrap(True)
        self._cloud_asset.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._cloud_points = QLabel("—")
        self._cloud_display_points = QLabel("—")
        self._cloud_colors = QLabel("—")
        self._cloud_normals = QLabel("—")
        self._cloud_unit = QLabel("—")
        self._cloud_size = QLabel("—")
        self._cloud_bounds = QLabel("—")
        self._cloud_bounds.setWordWrap(True)
        self._cloud_invalid = QLabel("—")
        self._cloud_memory = QLabel("—")
        self._cloud_translation = QLabel("—")
        self._cloud_rotation = QLabel("—")
        self._cloud_coordinate_mode = QLabel("—")
        self._cloud_processing_state = QLabel("—")
        self._cloud_last_processing = QLabel("—")
        self._cloud_last_processing.setWordWrap(True)
        self._cloud_crop_state = QLabel("—")

        point_cloud_layout.addRow("源文件", self._cloud_source)
        point_cloud_layout.addRow("项目资产", self._cloud_asset)
        point_cloud_layout.addRow("完整点数", self._cloud_points)
        point_cloud_layout.addRow("显示点数", self._cloud_display_points)
        point_cloud_layout.addRow("颜色", self._cloud_colors)
        point_cloud_layout.addRow("法线", self._cloud_normals)
        point_cloud_layout.addRow("单位", self._cloud_unit)
        point_cloud_layout.addRow("包围盒尺寸", self._cloud_size)
        point_cloud_layout.addRow("坐标范围", self._cloud_bounds)
        point_cloud_layout.addRow("移除无效点", self._cloud_invalid)
        point_cloud_layout.addRow("内存占用", self._cloud_memory)
        point_cloud_layout.addRow("世界坐标位置 XYZ", self._cloud_translation)
        point_cloud_layout.addRow("旋转 Rx/Ry/Rz", self._cloud_rotation)
        point_cloud_layout.addRow("操纵器坐标", self._cloud_coordinate_mode)
        point_cloud_layout.addRow("处理状态", self._cloud_processing_state)
        point_cloud_layout.addRow("最近处理", self._cloud_last_processing)
        point_cloud_layout.addRow("矩形裁剪", self._cloud_crop_state)
        self._point_cloud_card.hide()
        self._content_layout.addWidget(self._point_cloud_card)

        self._cad_card = QFrame()
        self._cad_card.setProperty("card", True)
        cad_layout = QFormLayout(self._cad_card)
        cad_layout.setContentsMargins(12, 12, 12, 12)
        cad_layout.setVerticalSpacing(9)
        cad_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        cad_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._cad_source = QLabel("—")
        self._cad_source.setWordWrap(True)
        self._cad_asset = QLabel("—")
        self._cad_asset.setWordWrap(True)
        self._cad_asset.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._cad_format = QLabel("—")
        self._cad_file_size = QLabel("—")
        self._cad_roots = QLabel("—")
        self._cad_solids = QLabel("—")
        self._cad_faces = QLabel("—")
        self._cad_size = QLabel("—")
        self._cad_bounds = QLabel("—")
        self._cad_translation = QLabel("—")
        self._cad_rotation = QLabel("—")
        self._cad_bounds.setWordWrap(True)
        cad_layout.addRow("源文件", self._cad_source)
        cad_layout.addRow("项目资产", self._cad_asset)
        cad_layout.addRow("格式", self._cad_format)
        cad_layout.addRow("文件大小", self._cad_file_size)
        cad_layout.addRow("STEP 根", self._cad_roots)
        cad_layout.addRow("实体数", self._cad_solids)
        cad_layout.addRow("面数", self._cad_faces)
        cad_layout.addRow("包围盒尺寸", self._cad_size)
        cad_layout.addRow("坐标范围", self._cad_bounds)
        cad_layout.addRow("世界坐标位置 XYZ", self._cad_translation)
        cad_layout.addRow("旋转 Rx/Ry/Rz", self._cad_rotation)
        self._cad_card.hide()
        self._content_layout.addWidget(self._cad_card)

        self._hint_card = QFrame()
        self._hint_card.setProperty("card", True)
        hint_layout = QVBoxLayout(self._hint_card)
        hint_layout.setContentsMargins(12, 12, 12, 12)
        hint_title = QLabel("工作提示")
        hint_title.setStyleSheet("font-weight: 600; color: #8dd3f4;")
        self._hint = QLabel("从左侧对象树选择节点，可查看对应属性和可用操作。")
        self._hint.setWordWrap(True)
        self._hint.setProperty("muted", True)
        hint_layout.addWidget(hint_title)
        hint_layout.addWidget(self._hint)
        self._content_layout.addWidget(self._hint_card)
        self._content_layout.addStretch(1)

    def set_node(self, node: SceneNode | None) -> None:
        if node is None:
            self._name.setText("—")
            self._kind.setText("—")
            self._state.setText("—")
            self._id.setText("—")
            self._hint.setText("从左侧对象树选择节点，可查看对应属性和可用操作。")
            self._point_cloud_card.hide()
            self._cad_card.hide()
            return

        self._name.setText(node.name)
        self._kind.setText(KIND_NAMES[node.kind])
        self._state.setText("接口预留" if node.metadata.get("placeholder") else "可用")
        self._id.setText(str(node.node_id))
        self._hint.setText(self._hint_for(node))
        self._update_point_cloud_properties(node)
        self._update_cad_properties(node)

    def _update_point_cloud_properties(self, node: SceneNode) -> None:
        if node.kind is not NodeKind.POINT_CLOUD:
            self._point_cloud_card.hide()
            return

        metadata = node.metadata
        point_count = int(metadata.get("point_count", 0))
        display_count = int(metadata.get("display_point_count", point_count))
        bounds_min = metadata.get("bounds_min")
        bounds_max = metadata.get("bounds_max")

        self._cloud_source.setText(str(metadata.get("source_name", metadata.get("asset", "—"))))
        self._cloud_asset.setText(str(metadata.get("asset", "—")))
        self._cloud_points.setText(f"{point_count:,}")
        self._cloud_display_points.setText(f"{display_count:,}")
        self._cloud_colors.setText("有" if metadata.get("has_colors") else "无")
        self._cloud_normals.setText("有" if metadata.get("has_normals") else "无")
        self._cloud_unit.setText(str(metadata.get("unit", "mm")))
        self._cloud_invalid.setText(f"{int(metadata.get('invalid_points_removed', 0)):,}")
        memory_bytes = int(metadata.get("memory_bytes", 0))
        self._cloud_memory.setText(format_bytes(memory_bytes) if memory_bytes else "—")
        try:
            translation, rotation = pose_from_matrix(metadata.get("transform"))
            self._cloud_translation.setText(
                ", ".join(f"{value:.3f}" for value in translation) + " mm"
            )
            self._cloud_rotation.setText(
                ", ".join(f"{value:.3f}°" for value in rotation)
            )
        except (TypeError, ValueError):
            self._cloud_translation.setText("—")
            self._cloud_rotation.setText("—")
        self._cloud_coordinate_mode.setText("点云自身")
        history = metadata.get("processing_history", [])
        if isinstance(history, list) and history:
            self._cloud_processing_state.setText(f"已应用 {len(history)} 次")
            latest = history[-1] if isinstance(history[-1], dict) else {}
            summary = latest.get("summary", {}) if isinstance(latest, dict) else {}
            steps = summary.get("steps", []) if isinstance(summary, dict) else []
            names = [
                str(step.get("name"))
                for step in steps
                if isinstance(step, dict) and step.get("name")
            ]
            input_count = int(summary.get("input_count", point_count))
            output_count = int(summary.get("output_count", point_count))
            description = "、".join(names) if names else "基础处理"
            self._cloud_last_processing.setText(
                f"{description}\n{input_count:,} → {output_count:,} 点"
            )
        else:
            self._cloud_processing_state.setText("原始导入数据")
            self._cloud_last_processing.setText("—")
        crop_history = metadata.get("crop_history", [])
        if isinstance(crop_history, list) and crop_history:
            latest_crop = crop_history[-1] if isinstance(crop_history[-1], dict) else {}
            mode = latest_crop.get("mode")
            action = "保留框内" if mode == "keep" else "删除框内"
            selected = int(latest_crop.get("selected_count", 0))
            self._cloud_crop_state.setText(
                f"已裁剪 {len(crop_history)} 次\n最近：{action} {selected:,} 点"
            )
        else:
            self._cloud_crop_state.setText("未裁剪")

        if self._is_vector3(bounds_min) and self._is_vector3(bounds_max):
            size = [float(high) - float(low) for low, high in zip(bounds_min, bounds_max)]
            self._cloud_size.setText(" × ".join(f"{value:.3f}" for value in size))
            minimum = ", ".join(f"{float(value):.3f}" for value in bounds_min)
            maximum = ", ".join(f"{float(value):.3f}" for value in bounds_max)
            self._cloud_bounds.setText(f"最小：{minimum}\n最大：{maximum}")
        else:
            self._cloud_size.setText("—")
            self._cloud_bounds.setText("—")
        self._point_cloud_card.show()

    def _update_cad_properties(self, node: SceneNode) -> None:
        if node.kind not in {NodeKind.CAD_MODEL, NodeKind.ROBOT} or node.metadata.get("placeholder"):
            self._cad_card.hide()
            return
        metadata = node.metadata
        if node.kind is NodeKind.ROBOT:
            self._cad_source.setText(str(metadata.get("source_name", "—")))
            self._cad_asset.setText(str(metadata.get("asset", "—")))
            self._cad_format.setText("URDF")
            self._cad_file_size.setText("—")
            self._cad_roots.setText(str(metadata.get("link_count", 0)))
            self._cad_solids.setText(str(metadata.get("joint_count", 0)))
            self._cad_faces.setText("—")
            self._cad_size.setText("—")
            self._cad_bounds.setText("—")
            self._cad_translation.setText("世界坐标位姿")
            self._cad_rotation.setText("静态零位")
            self._cad_card.show()
            return
        self._cad_source.setText(str(metadata.get("source_name", "—")))
        self._cad_asset.setText(str(metadata.get("asset", "—")))
        self._cad_format.setText(str(metadata.get("format", "STEP")))
        self._cad_file_size.setText(format_bytes(int(metadata.get("file_size", 0))))
        self._cad_roots.setText(f"{int(metadata.get('root_count', 0)):,}")
        self._cad_solids.setText(f"{int(metadata.get('solid_count', 0)):,}")
        self._cad_faces.setText(f"{int(metadata.get('face_count', 0)):,}")
        bounds_min = metadata.get("bounds_min")
        bounds_max = metadata.get("bounds_max")
        if self._is_vector3(bounds_min) and self._is_vector3(bounds_max):
            size = [float(high) - float(low) for low, high in zip(bounds_min, bounds_max)]
            self._cad_size.setText(" × ".join(f"{value:.3f}" for value in size) + " mm")
            minimum = ", ".join(f"{float(value):.3f}" for value in bounds_min)
            maximum = ", ".join(f"{float(value):.3f}" for value in bounds_max)
            self._cad_bounds.setText(f"最小：{minimum}\n最大：{maximum}")
        else:
            self._cad_size.setText("—")
            self._cad_bounds.setText("—")
        try:
            translation, rotation = pose_from_matrix(metadata.get("transform"))
            self._cad_translation.setText(
                ", ".join(f"{value:.3f}" for value in translation) + " mm"
            )
            self._cad_rotation.setText(
                ", ".join(f"{value:.3f}°" for value in rotation)
            )
        except (TypeError, ValueError):
            self._cad_translation.setText("—")
            self._cad_rotation.setText("—")
        self._cad_card.show()

    @staticmethod
    def _is_vector3(value) -> bool:
        return isinstance(value, (list, tuple)) and len(value) == 3

    @staticmethod
    def _hint_for(node: SceneNode) -> str:
        group = node.metadata.get("group")
        if group == "point_clouds":
            return "右键此节点或使用工具栏导入点云。"
        if group == "cad_models":
            return "数模导入接口已经预留，后续支持 STEP/IGES/STL。"
        if node.kind is NodeKind.ROBOT and node.metadata.get("placeholder"):
            return "正逆解、碰撞检测和机械臂通信接口已经预留。"
        if node.kind is NodeKind.ROBOT:
            return "URDF 机械臂已加载；当前显示初始零位，正逆解和碰撞检测接口仍为预留。"
        if node.kind is NodeKind.CAD_MODEL:
            return "STEP 数模已加载到三维场景。"
        if node.kind is NodeKind.POINT_CLOUD:
            return "右键点云可进入位置设置、基础处理和矩形裁剪。"
        if node.kind is NodeKind.PROJECT:
            return "项目保存与重新打开将在下一阶段接入。"
        return "该节点的详细参数将在对应功能阶段加入。"
