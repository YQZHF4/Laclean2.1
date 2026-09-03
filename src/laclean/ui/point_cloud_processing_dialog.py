"""Non-destructive basic point-cloud processing and preview dialog."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from laclean.core.point_cloud_processing import (
    PointCloudProcessingError,
    PointCloudProcessingOptions,
    PointCloudProcessingSummary,
)


class PointCloudProcessingDialog(QDialog):
    preview_requested = pyqtSignal(object)
    apply_requested = pyqtSignal()
    preview_invalidated = pyqtSignal()

    def __init__(self, cloud_name: str, point_count: int, unit: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("pointCloudProcessingDialog")
        self.setWindowTitle(f"基本点云处理 — {cloud_name}")
        self.setMinimumWidth(0)
        self.setModal(False)
        self._busy = False
        self._has_preview = False
        self._unit = unit

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("基础处理流水线")
        title.setProperty("section", True)
        root.addWidget(title)
        hint = QLabel(
            "算法按从上到下的顺序执行。预览仅临时替换三维显示，应用后才写入项目；"
            "最初导入的源文件始终保留。"
        )
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        root.addWidget(hint)

        self.voxel_group = self._checkable_group("1  体素降采样", False)
        voxel_form = QFormLayout(self.voxel_group)
        self.voxel_size = self._double_spin(0.001, 1_000_000.0, 0.5, 3)
        self.voxel_size.setSuffix(f" {unit}")
        voxel_form.addRow("体素尺寸", self.voxel_size)
        root.addWidget(self.voxel_group)

        self.statistical_group = self._checkable_group("2  统计离群点滤波", True)
        statistical_form = QFormLayout(self.statistical_group)
        self.statistical_neighbors = self._int_spin(2, 100_000, 20)
        self.statistical_std_ratio = self._double_spin(0.01, 100.0, 2.0, 2)
        statistical_form.addRow("邻域点数", self.statistical_neighbors)
        statistical_form.addRow("标准差倍数", self.statistical_std_ratio)
        root.addWidget(self.statistical_group)

        self.radius_group = self._checkable_group("3  半径离群点滤波", False)
        radius_form = QFormLayout(self.radius_group)
        self.radius_neighbors = self._int_spin(1, 100_000, 8)
        self.radius = self._double_spin(0.001, 1_000_000.0, 2.0, 3)
        self.radius.setSuffix(f" {unit}")
        radius_form.addRow("最少邻点数", self.radius_neighbors)
        radius_form.addRow("搜索半径", self.radius)
        root.addWidget(self.radius_group)

        self.normals_group = self._checkable_group("4  法线估计", False)
        normals_form = QFormLayout(self.normals_group)
        self.normal_radius = self._double_spin(0.001, 1_000_000.0, 3.0, 3)
        self.normal_radius.setSuffix(f" {unit}")
        self.normal_max_neighbors = self._int_spin(3, 100_000, 30)
        normals_form.addRow("搜索半径", self.normal_radius)
        normals_form.addRow("最大邻点数", self.normal_max_neighbors)
        root.addWidget(self.normals_group)

        result_card = QFrame()
        result_card.setProperty("card", True)
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(12, 10, 12, 10)
        result_title = QLabel("预览统计")
        result_title.setStyleSheet("font-weight: 600; color: #8dd3f4;")
        self.result_summary = QLabel(f"原始点数：{point_count:,}\n尚未生成预览")
        self.result_summary.setWordWrap(True)
        self.result_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        result_layout.addWidget(result_title)
        result_layout.addWidget(self.result_summary)
        root.addWidget(result_card)

        buttons = QHBoxLayout()
        self.defaults_button = QPushButton("恢复默认")
        self.cancel_preview_button = QPushButton("取消预览")
        self.cancel_preview_button.setEnabled(False)
        buttons.addWidget(self.defaults_button)
        buttons.addWidget(self.cancel_preview_button)
        buttons.addStretch(1)
        self.close_button = QPushButton("关闭")
        self.preview_button = QPushButton("预览")
        self.apply_button = QPushButton("应用结果")
        self.apply_button.setProperty("accent", True)
        self.apply_button.setEnabled(False)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.apply_button)
        root.addLayout(buttons)

        for group in (
            self.voxel_group,
            self.statistical_group,
            self.radius_group,
            self.normals_group,
        ):
            group.toggled.connect(self._parameters_changed)
        for widget in (
            self.voxel_size,
            self.statistical_neighbors,
            self.statistical_std_ratio,
            self.radius_neighbors,
            self.radius,
            self.normal_radius,
            self.normal_max_neighbors,
        ):
            widget.valueChanged.connect(self._parameters_changed)

        self.defaults_button.clicked.connect(self._restore_defaults)
        self.cancel_preview_button.clicked.connect(self._cancel_preview)
        self.close_button.clicked.connect(self.reject)
        self.preview_button.clicked.connect(self._request_preview)
        self.apply_button.clicked.connect(self.apply_requested)

    def options(self) -> PointCloudProcessingOptions:
        return PointCloudProcessingOptions(
            voxel_enabled=self.voxel_group.isChecked(),
            voxel_size=self.voxel_size.value(),
            statistical_enabled=self.statistical_group.isChecked(),
            statistical_neighbors=self.statistical_neighbors.value(),
            statistical_std_ratio=self.statistical_std_ratio.value(),
            radius_enabled=self.radius_group.isChecked(),
            radius_neighbors=self.radius_neighbors.value(),
            radius=self.radius.value(),
            normals_enabled=self.normals_group.isChecked(),
            normal_radius=self.normal_radius.value(),
            normal_max_neighbors=self.normal_max_neighbors.value(),
        )

    def set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        for widget in (
            self.voxel_group,
            self.statistical_group,
            self.radius_group,
            self.normals_group,
            self.defaults_button,
            self.close_button,
            self.preview_button,
            self.cancel_preview_button,
            self.apply_button,
        ):
            widget.setEnabled(not busy)
        if not busy:
            self.cancel_preview_button.setEnabled(self._has_preview)
            self.apply_button.setEnabled(self._has_preview)
        elif text:
            self.result_summary.setText(text)

    def set_preview_result(self, summary: PointCloudProcessingSummary) -> None:
        self._has_preview = True
        removed = summary.removed_count
        removed_text = f"移除 {removed:,}" if removed >= 0 else f"增加 {-removed:,}"
        lines = [
            f"输入：{summary.input_count:,} 点   →   结果：{summary.output_count:,} 点（{removed_text}）",
            f"耗时：{summary.elapsed_seconds:.3f} 秒",
        ]
        lines.extend(
            f"• {step.name}：{step.input_count:,} → {step.output_count:,}（{step.detail}）"
            for step in summary.steps
        )
        self.result_summary.setText("\n".join(lines))
        self.cancel_preview_button.setEnabled(True)
        self.apply_button.setEnabled(True)

    def show_error(self, message: str) -> None:
        self._has_preview = False
        self.apply_button.setEnabled(False)
        self.cancel_preview_button.setEnabled(False)
        self.result_summary.setText(f"处理失败：{message}")
        QMessageBox.critical(self, "点云处理失败", message)

    def mark_applied(self) -> None:
        self._has_preview = False

    def _request_preview(self) -> None:
        options = self.options()
        try:
            options.validate()
        except PointCloudProcessingError as exc:
            QMessageBox.warning(self, "参数无效", str(exc))
            return
        self.preview_requested.emit(options)

    def _parameters_changed(self, *_args) -> None:
        if self._busy:
            return
        had_preview = self._has_preview
        self._has_preview = False
        self.apply_button.setEnabled(False)
        self.cancel_preview_button.setEnabled(False)
        if had_preview:
            self.preview_invalidated.emit()
            self.result_summary.setText("参数已改变，三维视图已恢复当前点云。请重新预览。")

    def _cancel_preview(self) -> None:
        if not self._has_preview:
            return
        self._has_preview = False
        self.apply_button.setEnabled(False)
        self.cancel_preview_button.setEnabled(False)
        self.preview_invalidated.emit()
        self.result_summary.setText("预览已取消，三维视图已恢复当前点云。")

    def _restore_defaults(self) -> None:
        self.voxel_group.setChecked(False)
        self.voxel_size.setValue(0.5)
        self.statistical_group.setChecked(True)
        self.statistical_neighbors.setValue(20)
        self.statistical_std_ratio.setValue(2.0)
        self.radius_group.setChecked(False)
        self.radius_neighbors.setValue(8)
        self.radius.setValue(2.0)
        self.normals_group.setChecked(False)
        self.normal_radius.setValue(3.0)
        self.normal_max_neighbors.setValue(30)

    @staticmethod
    def _checkable_group(title: str, checked: bool) -> QGroupBox:
        group = QGroupBox(title)
        group.setCheckable(True)
        group.setChecked(checked)
        return group

    @staticmethod
    def _double_spin(
        minimum: float, maximum: float, value: float, decimals: int
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setValue(value)
        widget.setKeyboardTracking(False)
        return widget

    @staticmethod
    def _int_spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        widget.setKeyboardTracking(False)
        return widget

    def reject(self) -> None:
        if not self._busy:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)
