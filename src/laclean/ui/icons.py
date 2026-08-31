"""Small code-native line icons used by the industrial toolbar."""

from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def make_toolbar_icon(name: str, size: int = 32) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(QColor("#8dd8fa"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)

    drawers = {
        "capture": _draw_camera,
        "camera_connection": _draw_camera_connection,
        "import_point_cloud": _draw_point_cloud,
        "import_cad": _draw_cube,
        "import_robot": _draw_robot,
        "path_parameters": _draw_sliders,
        "generate_path": _draw_path,
        "robot_connection": _draw_robot,
        "galvo_connection": _draw_galvo,
    }
    drawers.get(name, _draw_placeholder)(painter)
    painter.end()
    return QIcon(pixmap)


def _draw_camera(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(4, 9, 24, 17), 3, 3)
    p.drawEllipse(QPointF(16, 17.5), 5.5, 5.5)
    p.drawPolyline(QPointF(9, 9), QPointF(11.5, 6), QPointF(18, 6), QPointF(20.5, 9))


def _draw_camera_connection(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(4, 8, 17, 16), 2.5, 2.5)
    p.drawEllipse(QPointF(12.5, 16), 4.2, 4.2)
    p.drawArc(QRectF(20, 8, 8, 8), -55 * 16, 110 * 16)
    p.drawArc(QRectF(19, 5, 13, 14), -55 * 16, 110 * 16)


def _draw_point_cloud(p: QPainter) -> None:
    for x, y in ((7, 21), (11, 14), (15, 23), (19, 17), (24, 22), (25, 12), (8, 9)):
        p.drawEllipse(QPointF(x, y), 1.25, 1.25)
    p.drawLine(QPointF(16, 4), QPointF(16, 15))
    p.drawPolyline(QPointF(11.5, 10.5), QPointF(16, 15), QPointF(20.5, 10.5))


def _draw_cube(p: QPainter) -> None:
    top = QPolygonF([QPointF(16, 4), QPointF(27, 10), QPointF(16, 16), QPointF(5, 10)])
    p.drawPolygon(top)
    p.drawPolyline(QPointF(5, 10), QPointF(5, 22), QPointF(16, 28), QPointF(16, 16))
    p.drawPolyline(QPointF(27, 10), QPointF(27, 22), QPointF(16, 28))


def _draw_sliders(p: QPainter) -> None:
    for y, knob in ((8, 11), (16, 21), (24, 15)):
        p.drawLine(QPointF(5, y), QPointF(27, y))
        p.setBrush(QColor("#8dd8fa"))
        p.drawEllipse(QPointF(knob, y), 2.3, 2.3)
        p.setBrush(Qt.NoBrush)


def _draw_path(p: QPainter) -> None:
    path = QPainterPath(QPointF(5, 24))
    path.cubicTo(QPointF(9, 5), QPointF(19, 27), QPointF(27, 8))
    p.drawPath(path)
    p.drawPolyline(QPointF(21.5, 10), QPointF(27, 8), QPointF(27.5, 13.5))
    p.drawEllipse(QPointF(5, 24), 1.5, 1.5)


def _draw_robot(p: QPainter) -> None:
    p.drawLine(QPointF(7, 27), QPointF(25, 27))
    p.drawRect(QRectF(10, 22, 9, 5))
    p.drawLine(QPointF(14.5, 22), QPointF(11, 15))
    p.drawLine(QPointF(11, 15), QPointF(19, 9))
    p.drawLine(QPointF(19, 9), QPointF(25, 13))
    for point in (QPointF(11, 15), QPointF(19, 9)):
        p.setBrush(QColor("#171a1f"))
        p.drawEllipse(point, 2.4, 2.4)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(25, 13), QPointF(27, 10))
    p.drawLine(QPointF(25, 13), QPointF(28, 15))


def _draw_galvo(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(6, 6, 20, 16), 2, 2)
    p.drawEllipse(QPointF(16, 14), 4.5, 4.5)
    p.drawLine(QPointF(16, 3), QPointF(16, 8))
    p.drawLine(QPointF(16, 20), QPointF(16, 29))
    p.drawLine(QPointF(12, 26), QPointF(20, 26))


def _draw_placeholder(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(6, 6, 20, 20), 4, 4)
