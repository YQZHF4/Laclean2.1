"""Open CASCADE viewer embedded in the Qt main window."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from uuid import UUID

import numpy as np

from laclean.core.error_handling import log_exception
from laclean.core.point_cloud import PointCloudData
from laclean.core.cad_model import CadModelData
from laclean.core.transforms import gp_trsf_to_matrix, matrix_to_gp_trsf

from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class OccViewerPanel(QWidget):
    initialized = pyqtSignal(bool, str)
    manipulator_transform_changed = pyqtSignal(str, object)
    manipulator_coordinate_mode_changed = pyqtSignal(str, str)
    crop_rectangle_drawn = pyqtSignal(object)
    crop_cancelled = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._viewer = None
        self._display = None
        self._driver_initialized = False
        self._occ_error = ""
        self._point_cloud_objects: dict[str, tuple[object, object]] = {}
        self._pending_point_clouds: dict[
            str, tuple[PointCloudData, bool, float, object]
        ] = {}
        self._point_cloud_bounds: dict[str, tuple[object, object]] = {}
        self._cad_objects: dict[str, object] = {}
        self._pending_cad_models: dict[
            str, tuple[CadModelData, bool, tuple[float, float, float]]
        ] = {}
        self._manipulator = None
        self._active_manipulator_key: str | None = None
        self._manipulator_target_key: str | None = None
        self._manipulator_coordinate_mode = "local"
        self._crop_active = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("viewerHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 5, 8, 5)
        header_layout.setSpacing(4)

        title = QLabel("三维场景")
        title.setObjectName("viewerTitle")
        header_layout.addWidget(title)
        header_layout.addStretch(1)

        self._coordinate_mode_combo = QComboBox()
        self._coordinate_mode_combo.addItem("局部", "local")
        self._coordinate_mode_combo.addItem("世界", "world")
        self._coordinate_mode_combo.setEnabled(False)
        self._coordinate_mode_combo.setToolTip("切换操纵器轴的局部/世界坐标方向")
        self._coordinate_mode_combo.currentIndexChanged.connect(
            self._on_coordinate_mode_changed
        )
        header_layout.addWidget(self._coordinate_mode_combo)

        self._crop_badge = QLabel("矩形框选 · 穿透")
        self._crop_badge.setObjectName("cropModeBadge")
        self._crop_badge.hide()
        header_layout.addWidget(self._crop_badge)
        self._cancel_crop_button = QPushButton("取消框选")
        self._cancel_crop_button.clicked.connect(self.cancel_rectangle_crop)
        self._cancel_crop_button.hide()
        header_layout.addWidget(self._cancel_crop_button)

        self._view_buttons: list[QPushButton] = []
        for text, tooltip, callback in (
            ("等轴", "等轴测视图", self.view_iso),
            ("前", "前视图", self.view_front),
            ("顶", "顶视图", self.view_top),
            ("右", "右视图", self.view_right),
            ("适应", "显示全部", self.fit_all),
        ):
            button = QPushButton(text)
            button.setToolTip(tooltip)
            button.setFixedHeight(26)
            button.clicked.connect(callback)
            header_layout.addWidget(button)
            self._view_buttons.append(button)
        root_layout.addWidget(header)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root_layout.addWidget(self._stack, 1)

        self._placeholder = QLabel("正在准备 Open CASCADE 三维窗口…")
        self._placeholder.setObjectName("occUnavailable")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setMargin(40)
        placeholder_host = QWidget()
        placeholder_layout = QVBoxLayout(placeholder_host)
        placeholder_layout.setContentsMargins(60, 60, 60, 60)
        placeholder_layout.addStretch(1)
        placeholder_layout.addWidget(self._placeholder)
        placeholder_layout.addStretch(1)
        self._stack.addWidget(placeholder_host)

        self._create_occ_widget()

    @property
    def display(self):
        return self._display

    @property
    def is_ready(self) -> bool:
        return self._driver_initialized and self._display is not None

    @property
    def manipulator_coordinate_mode(self) -> str:
        return self._manipulator_coordinate_mode

    def _create_occ_widget(self) -> None:
        if os.environ.get("LACLEAN_DISABLE_OCC") == "1":
            self._set_unavailable("测试模式：OCC 原生窗口已禁用")
            return
        try:
            from OCC.Display.backend import load_backend

            load_backend("pyqt5")
            from OCC.Core.AIS import AIS_ManipulatorOwner
            from OCC.Display.qtDisplay import qtViewer3dWithManipulator

            class TransformAwareViewer(qtViewer3dWithManipulator):
                manipulator_released = pyqtSignal()
                crop_rectangle_completed = pyqtSignal(object)
                crop_interaction_cancelled = pyqtSignal()

                def __init__(inner_self, *args) -> None:
                    super(TransformAwareViewer, inner_self).__init__(*args)
                    inner_self.crop_mode = False
                    inner_self.crop_start = None
                    inner_self.crop_current = None
                    inner_self.manipulator_drag_active = False

                def occ_mouse_pos(inner_self, event) -> QPoint:
                    pos = event.pos()
                    ratio_x, ratio_y = inner_self.occ_window_ratio()
                    return QPoint(
                        int(round(pos.x() * ratio_x)),
                        int(round(pos.y() * ratio_y)),
                    )

                def occ_window_ratio(inner_self) -> tuple[float, float]:
                    if getattr(inner_self, "_display", None) is None:
                        return (1.0, 1.0)
                    try:
                        occ_width, occ_height = inner_self._display.GetView().Window().Size()
                    except Exception:
                        ratio = float(inner_self.devicePixelRatioF())
                        return (ratio, ratio)
                    widget_width = max(1, int(inner_self.width()))
                    widget_height = max(1, int(inner_self.height()))
                    return (
                        float(occ_width) / float(widget_width),
                        float(occ_height) / float(widget_height),
                    )

                def occ_rect_from_qt_rect(inner_self, rectangle: QRect) -> QRect:
                    ratio_x, ratio_y = inner_self.occ_window_ratio()
                    left = int(round(rectangle.left() * ratio_x))
                    top = int(round(rectangle.top() * ratio_y))
                    right = int(round(rectangle.right() * ratio_x))
                    bottom = int(round(rectangle.bottom() * ratio_y))
                    return QRect(QPoint(left, top), QPoint(right, bottom)).normalized()

                def set_crop_mode(inner_self, enabled: bool) -> None:
                    inner_self.crop_mode = bool(enabled)
                    inner_self.crop_start = None
                    inner_self.crop_current = None
                    if enabled:
                        inner_self.setCursor(Qt.CrossCursor)
                        inner_self.setFocus()
                    else:
                        inner_self.unsetCursor()
                    inner_self.update()

                def manipulator_hit_at(inner_self, pos: QPoint) -> bool:
                    inner_self._display.MoveTo(pos.x(), pos.y())
                    try:
                        context = inner_self._display.Context
                        if not context.HasDetected():
                            inner_self.manipulator.DeactivateCurrentMode()
                            return False
                        owner = context.DetectedOwner()
                        manipulator_owner = AIS_ManipulatorOwner.DownCast(owner)
                        if manipulator_owner is None or (
                            hasattr(manipulator_owner, "IsNull")
                            and manipulator_owner.IsNull()
                        ):
                            inner_self.manipulator.DeactivateCurrentMode()
                            return False
                        return inner_self.manipulator.HasActiveMode()
                    except Exception:
                        inner_self.manipulator.DeactivateCurrentMode()
                        return False

                def mousePressEvent(inner_self, event) -> None:  # noqa: N802
                    if inner_self.crop_mode:
                        if event.button() == Qt.LeftButton:
                            inner_self.crop_start = event.pos()
                            inner_self.crop_current = event.pos()
                        elif event.button() == Qt.RightButton:
                            inner_self.set_crop_mode(False)
                            inner_self.crop_interaction_cancelled.emit()
                        event.accept()
                        return
                    inner_self.setFocus()
                    pos = inner_self.occ_mouse_pos(event)
                    inner_self.dragStartPosX = pos.x()
                    inner_self.dragStartPosY = pos.y()
                    inner_self.manipulator_drag_active = False
                    if (
                        event.button() == Qt.LeftButton
                        and inner_self.manipulator_hit_at(pos)
                    ):
                        inner_self.manipulator.StartTransform(
                            inner_self.dragStartPosX,
                            inner_self.dragStartPosY,
                            inner_self._display.GetView(),
                        )
                        inner_self.manipulator_drag_active = True
                    else:
                        inner_self._display.StartRotation(
                            inner_self.dragStartPosX,
                            inner_self.dragStartPosY,
                        )

                def mouseMoveEvent(inner_self, event) -> None:  # noqa: N802
                    if inner_self.crop_mode:
                        if (
                            inner_self.crop_start is not None
                            and event.buttons() & Qt.LeftButton
                        ):
                            inner_self.crop_current = event.pos()
                            inner_self.update()
                        event.accept()
                        return
                    pos = inner_self.occ_mouse_pos(event)
                    buttons = event.buttons()
                    modifiers = event.modifiers()
                    if buttons == Qt.LeftButton and modifiers != Qt.ShiftModifier:
                        if inner_self.manipulator_drag_active:
                            inner_self.trsf = inner_self.manipulator.Transform(
                                pos.x(), pos.y(), inner_self._display.GetView()
                            )
                            inner_self.manip_moved = True
                            inner_self._display.View.Redraw()
                        else:
                            inner_self.cursor = "rotate"
                            inner_self._display.Rotation(pos.x(), pos.y())
                            inner_self._drawbox = False
                    elif buttons == Qt.RightButton and modifiers != Qt.ShiftModifier:
                        inner_self.cursor = "zoom"
                        inner_self._display.Repaint()
                        inner_self._display.DynamicZoom(
                            abs(inner_self.dragStartPosX),
                            abs(inner_self.dragStartPosY),
                            abs(pos.x()),
                            abs(pos.y()),
                        )
                        inner_self.dragStartPosX = pos.x()
                        inner_self.dragStartPosY = pos.y()
                        inner_self._drawbox = False
                    elif buttons == Qt.MidButton:
                        dx = pos.x() - inner_self.dragStartPosX
                        dy = pos.y() - inner_self.dragStartPosY
                        inner_self.dragStartPosX = pos.x()
                        inner_self.dragStartPosY = pos.y()
                        inner_self.cursor = "pan"
                        inner_self._display.Pan(dx, -dy)
                        inner_self._drawbox = False
                    else:
                        inner_self._drawbox = False
                        inner_self._display.MoveTo(pos.x(), pos.y())
                        inner_self.cursor = "arrow"

                def mouseReleaseEvent(inner_self, event) -> None:  # noqa: N802
                    if inner_self.crop_mode:
                        if event.button() == Qt.LeftButton and inner_self.crop_start is not None:
                            rectangle = QRect(
                                inner_self.crop_start, event.pos()
                            ).normalized()
                            inner_self.set_crop_mode(False)
                            if rectangle.width() >= 4 and rectangle.height() >= 4:
                                occ_rectangle = inner_self.occ_rect_from_qt_rect(rectangle)
                                inner_self.crop_rectangle_completed.emit(
                                    (
                                        occ_rectangle.left(),
                                        occ_rectangle.top(),
                                        occ_rectangle.right(),
                                        occ_rectangle.bottom(),
                                    )
                                )
                            else:
                                inner_self.crop_interaction_cancelled.emit()
                        event.accept()
                        return
                    was_moved = inner_self.manip_moved
                    pos = inner_self.occ_mouse_pos(event)
                    modifiers = event.modifiers()
                    if event.button() == Qt.LeftButton:
                        if inner_self.manipulator_drag_active and inner_self.manip_moved:
                            inner_self.trsf_manip.append(inner_self.trsf)
                            inner_self.manip_moved = False
                        if not inner_self.manipulator_drag_active and modifiers == Qt.ShiftModifier:
                            inner_self._display.ShiftSelect(pos.x(), pos.y())
                        elif not inner_self.manipulator_drag_active:
                            inner_self._display.Select(pos.x(), pos.y())
                            if inner_self._display.selected_shapes is not None:
                                inner_self.sig_topods_selected.emit(
                                    inner_self._display.selected_shapes
                                )
                        inner_self.manipulator_drag_active = False
                    inner_self.cursor = "arrow"
                    if was_moved:
                        inner_self.manipulator_released.emit()

                def keyPressEvent(inner_self, event) -> None:  # noqa: N802
                    if inner_self.crop_mode and event.key() == Qt.Key_Escape:
                        inner_self.set_crop_mode(False)
                        inner_self.crop_interaction_cancelled.emit()
                        event.accept()
                        return
                    super(TransformAwareViewer, inner_self).keyPressEvent(event)

                def paintEvent(inner_self, event) -> None:  # noqa: N802
                    super(TransformAwareViewer, inner_self).paintEvent(event)
                    if (
                        not inner_self.crop_mode
                        or inner_self.crop_start is None
                        or inner_self.crop_current is None
                    ):
                        return
                    rectangle = QRect(
                        inner_self.crop_start, inner_self.crop_current
                    ).normalized()
                    painter = QPainter(inner_self)
                    painter.setPen(QPen(QColor(62, 190, 255), 2, Qt.DashLine))
                    painter.setBrush(QBrush(QColor(24, 142, 205, 45)))
                    painter.drawRect(rectangle)

            self._viewer = TransformAwareViewer(self)
            self._viewer.manipulator_released.connect(self._on_manipulator_released)
            self._viewer.crop_rectangle_completed.connect(
                self._on_crop_rectangle_completed
            )
            self._viewer.crop_interaction_cancelled.connect(
                self._on_crop_interaction_cancelled
            )
            self._viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._stack.addWidget(self._viewer)
            self._stack.setCurrentWidget(self._viewer)
        except Exception as exc:  # Native packages need a graceful diagnostic.
            log_exception("初始化 OCC Qt 控件", exc)
            details = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, ModuleNotFoundError) and exc.name == "OCC":
                details = (
                    "当前 Python 环境没有安装 pythonocc-core。\n\n"
                    f"当前解释器：\n{sys.executable}\n\n"
                    "请双击 run_laclean.bat，或执行：\n"
                    "conda run -n Laser python main.py"
                )
            self._set_unavailable(f"Open CASCADE 查看器不可用\n\n{details}")

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().showEvent(event)
        if self._viewer is not None and not self._driver_initialized:
            self._initialize_driver()

    def _initialize_driver(self) -> None:
        try:
            self._viewer.InitDriver()
            self._display = self._viewer._display
            self._configure_view_rendering()
            self._display_view_triedron()
            self._display.View_Iso()
            self._display.Repaint()
            self._driver_initialized = True
            pending = list(self._pending_point_clouds.values())
            self._pending_point_clouds.clear()
            for data, visible, point_size, transform in pending:
                self.display_point_cloud(
                    data,
                    visible=visible,
                    point_size=point_size,
                    transform=transform,
                    fit=False,
                )
            if pending:
                self.fit_all()
            pending_cad = list(self._pending_cad_models.values())
            self._pending_cad_models.clear()
            for data, visible, color in pending_cad:
                self.display_cad_model(
                    data, visible=visible, color=color, fit=False
                )
            if pending_cad:
                self.fit_all()
            self.initialized.emit(True, "OCC 7.9.3 三维视图已就绪")
        except Exception as exc:
            detail = log_exception("初始化 Open CASCADE 驱动", exc)
            self._set_unavailable(f"Open CASCADE 驱动初始化失败\n\n{detail}")

    def _configure_view_rendering(self) -> None:
        from OCC.Core.Aspect import Aspect_GFM_VER
        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB

        view = self._display.GetView()
        top = Quantity_Color(0.008, 0.010, 0.013, Quantity_TOC_RGB)
        bottom = Quantity_Color(0.012, 0.015, 0.019, Quantity_TOC_RGB)
        view.SetBgGradientColors(top, bottom, Aspect_GFM_VER)
        params = view.ChangeRenderingParams()
        params.NbMsaaSamples = 8
        params.IsAntialiasingEnabled = True
        view.Redraw()

    def _display_view_triedron(self) -> None:
        from OCC.Core.Aspect import Aspect_TOTP_LEFT_LOWER
        from OCC.Core.Quantity import Quantity_Color, Quantity_NOC_WHITE
        from OCC.Core.V3d import V3d_ZBUFFER

        self._display.GetView().TriedronDisplay(
            Aspect_TOTP_LEFT_LOWER,
            Quantity_Color(Quantity_NOC_WHITE),
            0.14,
            V3d_ZBUFFER,
        )

    @staticmethod
    def _z_gradient_colors(
        points: np.ndarray, z_min: float, z_max: float
    ) -> np.ndarray:
        if len(points) == 0:
            return np.empty((0, 3), dtype=np.uint8)
        if z_max <= z_min:
            return np.tile(np.array([[0, 0, 255]], dtype=np.uint8), (len(points), 1))
        t = np.clip((points[:, 2].astype(np.float32) - z_min) / (z_max - z_min), 0.0, 1.0)
        palette = np.asarray(
            ((0, 0, 255), (0, 255, 255), (0, 255, 0), (255, 255, 0), (255, 0, 0)),
            dtype=np.float32,
        )
        position = t * (len(palette) - 1)
        index = np.minimum(position.astype(np.int32), len(palette) - 2)
        fraction = (position - index)[:, None]
        gradient = palette[index] + (palette[index + 1] - palette[index]) * fraction
        return np.rint(gradient).astype(np.uint8)

    @staticmethod
    def _pack_vertex_color(red: int, green: int, blue: int) -> int:
        color32 = (255 << 24) | (blue << 16) | (green << 8) | red
        return color32 - (1 << 32) if color32 >= (1 << 31) else color32

    def _set_unavailable(self, message: str) -> None:
        self._occ_error = message
        self._placeholder.setText(message)
        self._stack.setCurrentIndex(0)
        for button in self._view_buttons:
            button.setEnabled(False)
        self.initialized.emit(False, message)

    def _call_display(self, callback: Callable[[object], None]) -> None:
        if self.is_ready:
            callback(self._display)

    def view_iso(self) -> None:
        self._call_display(lambda display: display.View_Iso())
        self.fit_all()

    def view_front(self) -> None:
        self._call_display(lambda display: display.View_Front())
        self.fit_all()

    def view_top(self) -> None:
        self._call_display(lambda display: display.View_Top())
        self.fit_all()

    def view_right(self) -> None:
        self._call_display(lambda display: display.View_Right())
        self.fit_all()

    def fit_all(self) -> None:
        self._call_display(lambda display: display.FitAll())

    @property
    def is_rectangle_crop_active(self) -> bool:
        return self._crop_active

    def start_rectangle_crop(self) -> bool:
        if not self.is_ready or self._viewer is None:
            return False
        self.detach_manipulator(clear_target=False)
        self._crop_active = True
        self._crop_badge.show()
        self._cancel_crop_button.show()
        self._viewer.set_crop_mode(True)
        return True

    def cancel_rectangle_crop(self, *, emit_signal: bool = True) -> None:
        was_active = self._crop_active
        self._crop_active = False
        self._crop_badge.hide()
        self._cancel_crop_button.hide()
        if self._viewer is not None:
            self._viewer.set_crop_mode(False)
        if was_active and emit_signal:
            self.crop_cancelled.emit()

    def capture_projection_state(self) -> tuple[object, tuple[int, int]]:
        if not self.is_ready or self._viewer is None:
            raise RuntimeError("OCC 三维视图尚未就绪。")
        camera = self._display.GetView().Camera()
        orientation = self._occ_matrix_to_numpy(camera.OrientationMatrix())
        projection = self._occ_matrix_to_numpy(camera.ProjectionMatrix())
        return projection @ orientation, self._occ_viewport_size()

    def _occ_viewport_size(self) -> tuple[int, int]:
        if not self.is_ready:
            return (
                max(1, int(self._viewer.width() if self._viewer is not None else 1)),
                max(1, int(self._viewer.height() if self._viewer is not None else 1)),
            )
        try:
            width, height = self._display.GetView().Window().Size()
            return max(1, int(width)), max(1, int(height))
        except Exception:
            ratio = float(self._viewer.devicePixelRatioF()) if self._viewer is not None else 1.0
            return (
                max(1, int(round(self._viewer.width() * ratio))),
                max(1, int(round(self._viewer.height() * ratio))),
            )

    @staticmethod
    def _occ_matrix_to_numpy(matrix: object) -> np.ndarray:
        return np.array(
            [
                [float(matrix.GetValue(row, column)) for column in range(4)]
                for row in range(4)
            ],
            dtype=np.float64,
        )

    def _on_crop_rectangle_completed(self, rectangle: object) -> None:
        self.cancel_rectangle_crop(emit_signal=False)
        self.crop_rectangle_drawn.emit(rectangle)

    def _on_crop_interaction_cancelled(self) -> None:
        self.cancel_rectangle_crop(emit_signal=False)
        self.crop_cancelled.emit()

    def display_point_cloud(
        self,
        data: PointCloudData,
        *,
        visible: bool = True,
        point_size: float = 4.0,
        transform: object | None = None,
        fit: bool = True,
    ) -> int:
        """Create or replace an OCC point-cloud presentation on the UI thread."""

        key = str(data.node_id)
        transform_value = transform if transform is not None else np.eye(4)
        if not self.is_ready:
            self._pending_point_clouds[key] = (data, visible, point_size, transform_value)
            self._point_cloud_bounds[key] = (data.bounds_min.copy(), data.bounds_max.copy())
            return len(data.display_arrays()[0])

        from OCC.Core.AIS import AIS_PointCloud
        from OCC.Core.Aspect import Aspect_TOM_POINT
        from OCC.Core.Graphic3d import Graphic3d_ArrayOfPoints
        from OCC.Core.Prs3d import Prs3d_PointAspect
        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCC.Core.gp import gp_Pnt

        self.remove_point_cloud(data.node_id, update=False)
        points, colors = data.display_arrays()
        has_colors = colors is not None or len(points) > 0
        vertices = Graphic3d_ArrayOfPoints(int(len(points)), has_colors, False)

        if colors is None:
            gradient_colors = self._z_gradient_colors(
                points, float(data.bounds_min[2]), float(data.bounds_max[2])
            )
            for (x, y, z), (red, green, blue) in zip(
                points, gradient_colors, strict=True
            ):
                vertices.AddVertex(
                    gp_Pnt(float(x), float(y), float(z)),
                    self._pack_vertex_color(int(red), int(green), int(blue)),
                )
        else:
            for (x, y, z), (red, green, blue) in zip(points, colors, strict=True):
                color32 = self._pack_vertex_color(
                    int(red), int(green), int(blue)
                )
                vertices.AddVertex(gp_Pnt(float(x), float(y), float(z)), color32)

        presentation = AIS_PointCloud()
        presentation.SetPoints(vertices)
        presentation.SetLocalTransformation(matrix_to_gp_trsf(transform_value))
        presentation.SetColor(Quantity_Color(0.8, 0.8, 0.8, Quantity_TOC_RGB))  # 对象级颜色设置

        self._display.Context.Display(presentation, False)
        if not visible:
            self._display.Context.Erase(presentation, False)
        self._point_cloud_objects[key] = (presentation, vertices)
        self._point_cloud_bounds[key] = (data.bounds_min.copy(), data.bounds_max.copy())
        self._display.Context.UpdateCurrentViewer()
        if fit and visible:
            self.fit_all()
        return int(len(points))

    def display_cad_model(
        self,
        data: CadModelData,
        *,
        visible: bool = True,
        color: tuple[float, float, float] = (0.72, 0.76, 0.82),
        fit: bool = True,
    ) -> None:
        """Create or replace a shaded AIS presentation for a STEP shape."""

        key = str(data.node_id)
        color_value = tuple(float(max(0.0, min(1.0, value))) for value in color)
        if not self.is_ready:
            self._pending_cad_models[key] = (data, visible, color_value)
            return

        from OCC.Core.AIS import AIS_Shape
        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB

        self.remove_cad_model(data.node_id, update=False)
        presentation = AIS_Shape(data.shape)
        presentation.SetColor(
            Quantity_Color(*color_value, Quantity_TOC_RGB)
        )
        presentation.SetDisplayMode(1)
        self._display.Context.Display(presentation, False)
        if not visible:
            self._display.Context.Erase(presentation, False)
        self._cad_objects[key] = presentation
        self._display.Context.UpdateCurrentViewer()
        if fit and visible:
            self.fit_all()

    def set_cad_model_visible(self, node_id: UUID, visible: bool) -> None:
        key = str(node_id)
        pending = self._pending_cad_models.get(key)
        if pending is not None:
            data, _, color = pending
            self._pending_cad_models[key] = (data, visible, color)
            return
        presentation = self._cad_objects.get(key)
        if not self.is_ready or presentation is None:
            return
        if visible:
            self._display.Context.Display(presentation, False)
        else:
            self._display.Context.Erase(presentation, False)
        self._display.Context.UpdateCurrentViewer()

    def remove_cad_model(self, node_id: UUID, update: bool = True) -> None:
        key = str(node_id)
        self._pending_cad_models.pop(key, None)
        presentation = self._cad_objects.pop(key, None)
        if not self.is_ready or presentation is None:
            return
        self._display.Context.Remove(presentation, False)
        if update:
            self._display.Context.UpdateCurrentViewer()

    def clear_cad_models(self) -> None:
        self._pending_cad_models.clear()
        if self.is_ready:
            for presentation in self._cad_objects.values():
                self._display.Context.Remove(presentation, False)
            self._display.Context.UpdateCurrentViewer()
        self._cad_objects.clear()

    def set_point_cloud_visible(self, node_id: UUID, visible: bool) -> None:
        key = str(node_id)
        pending = self._pending_point_clouds.get(key)
        if pending is not None:
            data, _, point_size, transform = pending
            self._pending_point_clouds[key] = (data, visible, point_size, transform)
            return
        current = self._point_cloud_objects.get(key)
        if not self.is_ready or current is None:
            return
        presentation, _ = current
        if visible:
            self._display.Context.Display(presentation, False)
        else:
            if self._manipulator_target_key == key:
                self.detach_manipulator()
            self._display.Context.Erase(presentation, False)
        self._display.Context.UpdateCurrentViewer()

    def remove_point_cloud(self, node_id: UUID, update: bool = True) -> None:
        key = str(node_id)
        if self._manipulator_target_key == key:
            self.detach_manipulator()
        self._pending_point_clouds.pop(key, None)
        self._point_cloud_bounds.pop(key, None)
        current = self._point_cloud_objects.pop(key, None)
        if not self.is_ready or current is None:
            return
        presentation, _ = current
        self._display.Context.Remove(presentation, False)
        if update:
            self._display.Context.UpdateCurrentViewer()

    def clear_point_clouds(self) -> None:
        self.detach_manipulator(clear_target=False)
        self._pending_point_clouds.clear()
        self._point_cloud_bounds.clear()
        if self.is_ready:
            for presentation, _ in self._point_cloud_objects.values():
                self._display.Context.Remove(presentation, False)
            self._display.Context.UpdateCurrentViewer()
        self._point_cloud_objects.clear()

    def set_point_cloud_transform(self, node_id: UUID, matrix_value: object) -> None:
        key = str(node_id)
        pending = self._pending_point_clouds.get(key)
        if pending is not None:
            data, visible, point_size, _ = pending
            self._pending_point_clouds[key] = (data, visible, point_size, matrix_value)
            return
        current = self._point_cloud_objects.get(key)
        if not self.is_ready or current is None:
            return
        presentation, _ = current
        presentation.SetLocalTransformation(matrix_to_gp_trsf(matrix_value))
        self._display.Context.Redisplay(presentation, False)
        if self._active_manipulator_key == key:
            self._update_manipulator_position()
        self._display.Context.UpdateCurrentViewer()

    def attach_point_cloud_manipulator(self, node_id: UUID) -> bool:
        key = str(node_id)
        current = self._point_cloud_objects.get(key)
        if not self.is_ready or current is None:
            self._coordinate_mode_combo.setEnabled(False)
            return False

        from OCC.Core.AIS import (
            AIS_MM_Rotation,
            AIS_MM_Scaling,
            AIS_MM_Translation,
            AIS_MM_TranslationPlane,
            AIS_Manipulator,
        )

        self.detach_manipulator()
        presentation, _ = current
        manipulator = AIS_Manipulator()
        manipulator.SetPart(AIS_MM_Scaling, False)
        manipulator.SetPart(AIS_MM_TranslationPlane, False)
        manipulator.SetModeActivationOnDetection(True)
        self._viewer.set_manipulator(manipulator)
        manipulator.Attach(presentation)
        manipulator.EnableMode(AIS_MM_Translation)
        manipulator.EnableMode(AIS_MM_Rotation)

        self._manipulator = manipulator
        self._active_manipulator_key = key
        self._manipulator_target_key = key
        self._coordinate_mode_combo.setEnabled(True)
        self._update_manipulator_position()
        self._display.Context.UpdateCurrentViewer()
        return True

    def detach_manipulator(self, clear_target: bool = True) -> None:
        if self._manipulator is not None:
            try:
                self._manipulator.Detach()
            except Exception:
                pass
        self._manipulator = None
        self._active_manipulator_key = None
        if clear_target:
            self._manipulator_target_key = None
        if self._viewer is not None and self.is_ready:
            from OCC.Core.AIS import AIS_Manipulator

            self._viewer.set_manipulator(AIS_Manipulator())
        has_target = (
            not clear_target
            and self._manipulator_target_key is not None
            and self._manipulator_target_key in self._point_cloud_objects
        )
        self._coordinate_mode_combo.setEnabled(has_target)

    def set_manipulator_coordinate_mode(self, mode: str) -> None:
        if mode not in {"local", "world"}:
            raise ValueError(f"Unknown manipulator coordinate mode: {mode}")
        self._manipulator_coordinate_mode = mode
        index = self._coordinate_mode_combo.findData(mode)
        if index >= 0 and index != self._coordinate_mode_combo.currentIndex():
            self._coordinate_mode_combo.blockSignals(True)
            self._coordinate_mode_combo.setCurrentIndex(index)
            self._coordinate_mode_combo.blockSignals(False)
        self._update_manipulator_position()

    def _on_coordinate_mode_changed(self) -> None:
        mode = self._coordinate_mode_combo.currentData()
        if isinstance(mode, str):
            self.set_manipulator_coordinate_mode(mode)
            if self._manipulator_target_key is not None:
                self.manipulator_coordinate_mode_changed.emit(
                    self._manipulator_target_key, mode
                )

    def _on_manipulator_released(self) -> None:
        key = self._active_manipulator_key
        current = self._point_cloud_objects.get(key or "")
        if key is None or current is None:
            return
        presentation, _ = current
        matrix = gp_trsf_to_matrix(presentation.LocalTransformation())
        self._update_manipulator_position()
        self.manipulator_transform_changed.emit(key, matrix.tolist())

    def _update_manipulator_position(self) -> None:
        key = self._active_manipulator_key
        if self._manipulator is None or key is None:
            return
        current = self._point_cloud_objects.get(key)
        bounds = self._point_cloud_bounds.get(key)
        if current is None or bounds is None:
            return

        from OCC.Core.gp import gp_Ax2, gp_Dir, gp_Pnt

        presentation, _ = current
        matrix = gp_trsf_to_matrix(presentation.LocalTransformation())
        bounds_min, bounds_max = bounds
        local_center = (np.asarray(bounds_min) + np.asarray(bounds_max)) * 0.5
        world_center = matrix @ np.array([*local_center, 1.0], dtype=float)
        rotation = matrix[:3, :3] if self._manipulator_coordinate_mode == "local" else np.eye(3)
        x_direction = rotation[:, 0]
        z_direction = rotation[:, 2]
        position = gp_Ax2(
            gp_Pnt(*(float(value) for value in world_center[:3])),
            gp_Dir(*(float(value) for value in z_direction)),
            gp_Dir(*(float(value) for value in x_direction)),
        )
        self._manipulator.SetPosition(position)
        self._display.Context.Redisplay(self._manipulator, False)
