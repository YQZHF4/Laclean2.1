from uuid import UUID

import numpy as np

from laclean.application.controller import ApplicationController
from laclean.core.point_cloud import PointCloudData
from laclean.core.scene import NodeKind, SceneNode


def test_controller_owns_scene_state_and_node_mutations() -> None:
    controller = ApplicationController()
    group = controller.point_cloud_group()
    assert group is not None

    node = group.add_child(SceneNode("测试点云", NodeKind.POINT_CLOUD))
    data = PointCloudData(
        node_id=node.node_id,
        name=node.name,
        asset_path=None,
        points=np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
    )
    controller.register_point_cloud(node, data)

    assert controller.point_clouds[node.node_id] is data
    assert controller.set_visibility(node, False) is True
    assert node.visible is False

    matrix = np.eye(4, dtype=float)
    matrix[0, 3] = 12.5
    updated = controller.update_transform(node.node_id, matrix.tolist())

    assert updated is node
    assert node.metadata["transform"] == matrix.tolist()
    assert node.metadata["coordinate_mode"] == "local"
    assert controller.find_node(UUID(str(node.node_id))) is node
    assert controller.document.modified is True
