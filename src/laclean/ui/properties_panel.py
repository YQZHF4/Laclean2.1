"""Selection-aware property summary panel."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from laclean.core.scene import NodeKind, SceneNode
from laclean.core.error_handling import format_bytes
from laclean.core.transforms import pose_from_matrix


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


class PropertiesPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll)

        content = QWidget(scroll)
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
        if node.kind not in {NodeKind.CAD_MODEL, NodeKind.ROBOT} or node.metadata.get(
            "placeholder"
        ):
            self._cad_card.hide()
            return
        metadata = node.metadata
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
            return "机械臂 STEP 已加载；正逆解和碰撞检测接口仍为预留。"
        if node.kind is NodeKind.CAD_MODEL:
            return "STEP 数模已加载到三维场景。"
        if node.kind is NodeKind.POINT_CLOUD:
            return "右键点云可进入位置设置、基础处理和矩形裁剪。"
        if node.kind is NodeKind.PROJECT:
            return "项目保存与重新打开将在下一阶段接入。"
        return "该节点的详细参数将在对应功能阶段加入。"
