"""Rigid-transform conversion helpers used by scene nodes and OCC."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray


def validated_matrix(value: object) -> NDArray[np.float64]:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("变换矩阵必须是有限的 4×4 数组。")
    if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8):
        raise ValueError("变换矩阵最后一行必须为 [0, 0, 0, 1]。")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6):
        raise ValueError("变换矩阵旋转部分必须正交且不包含缩放。")
    if not math.isclose(float(np.linalg.det(rotation)), 1.0, abs_tol=1e-6):
        raise ValueError("变换矩阵旋转部分必须是右手刚体旋转。")
    return matrix


def matrix_from_pose(
    translation_xyz: Sequence[float], rotation_xyz_degrees: Sequence[float]
) -> NDArray[np.float64]:
    """Build a matrix using R = Rz @ Ry @ Rx (ZYX Euler convention)."""

    tx, ty, tz = (float(value) for value in translation_xyz)
    rx, ry, rz = (math.radians(float(value)) for value in rotation_xyz_degrees)
    sx, cx = math.sin(rx), math.cos(rx)
    sy, cy = math.sin(ry), math.cos(ry)
    sz, cz = math.sin(rz), math.cos(rz)

    rotation_x = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
    rotation_y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
    rotation_z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)

    matrix = np.eye(4, dtype=float)
    matrix[:3, :3] = rotation_z @ rotation_y @ rotation_x
    matrix[:3, 3] = [tx, ty, tz]
    return matrix


def pose_from_matrix(
    matrix_value: object,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    matrix = validated_matrix(matrix_value)
    rotation = matrix[:3, :3]
    cy = math.hypot(float(rotation[0, 0]), float(rotation[1, 0]))

    if cy > 1e-9:
        rx = math.atan2(float(rotation[2, 1]), float(rotation[2, 2]))
        ry = math.atan2(-float(rotation[2, 0]), cy)
        rz = math.atan2(float(rotation[1, 0]), float(rotation[0, 0]))
    else:
        rx = math.atan2(-float(rotation[1, 2]), float(rotation[1, 1]))
        ry = math.atan2(-float(rotation[2, 0]), cy)
        rz = 0.0

    translation = tuple(float(value) for value in matrix[:3, 3])
    rotation_degrees = tuple(math.degrees(value) for value in (rx, ry, rz))
    return translation, rotation_degrees


def matrix_to_gp_trsf(matrix_value: object):
    from OCC.Core.gp import gp_Trsf

    matrix = validated_matrix(matrix_value)
    transform = gp_Trsf()
    transform.SetValues(*(float(value) for value in matrix[:3, :4].ravel()))
    return transform


def gp_trsf_to_matrix(transform) -> NDArray[np.float64]:
    matrix = np.eye(4, dtype=float)
    for row in range(1, 4):
        for column in range(1, 5):
            matrix[row - 1, column - 1] = float(transform.Value(row, column))
    return validated_matrix(matrix)
