import numpy as np
import pytest

from laclean.core.transforms import (
    gp_trsf_to_matrix,
    matrix_from_pose,
    matrix_to_gp_trsf,
    pose_from_matrix,
    validated_matrix,
)


@pytest.mark.parametrize(
    ("translation", "rotation"),
    [
        ((0, 0, 0), (0, 0, 0)),
        ((12.5, -8.0, 24.0), (15.0, 25.0, -35.0)),
        ((-100, 200, 3.5), (-45.0, 60.0, 120.0)),
    ],
)
def test_pose_matrix_round_trip(translation, rotation) -> None:
    matrix = matrix_from_pose(translation, rotation)
    restored_translation, restored_rotation = pose_from_matrix(matrix)

    assert np.allclose(restored_translation, translation)
    assert np.allclose(restored_rotation, rotation)


def test_occ_transform_round_trip() -> None:
    matrix = matrix_from_pose((5, 6, 7), (10, 20, 30))

    restored = gp_trsf_to_matrix(matrix_to_gp_trsf(matrix))

    assert np.allclose(restored, matrix)


def test_scaled_matrix_is_rejected() -> None:
    matrix = np.eye(4)
    matrix[0, 0] = 2.0

    with pytest.raises(ValueError, match="不包含缩放"):
        validated_matrix(matrix)
