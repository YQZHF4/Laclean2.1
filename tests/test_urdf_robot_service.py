from pathlib import Path

import pytest

from laclean.core.scene import NodeKind
from laclean.core.robot_model import RobotJoint, RobotLink, RobotModelData
from laclean.services.urdf_robot_service import UrdfRobotError, UrdfRobotService


def write_urdf(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "robot.urdf"
    path.write_text(f'<robot name="demo">{body}</robot>', encoding="utf-8")
    return path


def test_valid_urdf_parses_links_joints_and_limits(tmp_path, monkeypatch):
    source = write_urdf(tmp_path, """
      <link name="base"/><link name="tool"/>
      <joint name="j1" type="revolute"><parent link="base"/><child link="tool"/>
        <axis xyz="0 0 1"/><limit lower="-1.2" upper="1.2" effort="10" velocity="2"/>
      </joint>
    """)
    service = UrdfRobotService()
    monkeypatch.setattr(service, "_build_link_shapes", lambda links, asset: {})
    result = service.import_to_project(source, tmp_path / "project.lcp")
    assert result.node.kind is NodeKind.ROBOT
    assert result.data.link_count == 2
    assert result.data.joints[0].lower == -1.2
    assert result.data.joints[0].upper == 1.2


def test_each_mesh_keeps_its_own_urdf_scale(tmp_path, monkeypatch):
    mesh = tmp_path / "part.stl"
    mesh.write_text("solid part\nendsolid part\n", encoding="ascii")
    other = tmp_path / "other.stl"
    other.write_text("solid other\nendsolid other\n", encoding="ascii")
    source = write_urdf(tmp_path, """
      <link name="base">
        <visual><geometry><mesh filename="part.stl" scale="2 3 4"/></geometry></visual>
        <visual><geometry><mesh filename="other.stl" scale="0.1 0.2 0.3"/></geometry></visual>
      </link>
    """)
    service = UrdfRobotService()
    monkeypatch.setattr(service, "_build_link_shapes", lambda links, asset: {})
    result = service.import_to_project(source, tmp_path / "project.lcp")
    assert result.data.links[0].visual_meshes[0].scale == (2.0, 3.0, 4.0)
    assert result.data.links[0].visual_meshes[1].scale == (0.1, 0.2, 0.3)


def test_visual_and_collision_meshes_with_same_name_are_not_overwritten(tmp_path, monkeypatch):
    visual = tmp_path / "meshes" / "visual" / "base_link.stl"
    collision = tmp_path / "meshes" / "collision" / "base_link.stl"
    visual.parent.mkdir(parents=True)
    collision.parent.mkdir(parents=True)
    visual.write_text("visual", encoding="ascii")
    collision.write_text("collision", encoding="ascii")
    source = write_urdf(tmp_path, """
      <link name="base">
        <visual><geometry><mesh filename="package://robot/meshes/visual/base_link.stl"/></geometry></visual>
        <collision><geometry><mesh filename="package://robot/meshes/collision/base_link.stl"/></geometry></collision>
      </link>
    """)
    service = UrdfRobotService()
    monkeypatch.setattr(service, "_build_link_shapes", lambda links, asset: {})
    result = service.import_to_project(source, tmp_path / "project.lcp")
    visual_path = Path(result.data.links[0].visual_meshes[0].path)
    collision_path = Path(result.data.links[0].collision_meshes[0].path)
    assert visual_path != collision_path
    assert visual_path.relative_to(result.data.urdf_path.parent).as_posix() == "meshes/visual/base_link.stl"
    assert collision_path.relative_to(result.data.urdf_path.parent).as_posix() == "meshes/collision/base_link.stl"
    assert visual_path.read_text(encoding="ascii") == "visual"
    assert collision_path.read_text(encoding="ascii") == "collision"


@pytest.mark.parametrize("body", [
    '<link name="a"/><link name="a"/>',
    '<link name="a"/><joint name="j" type="fixed"><parent link="x"/><child link="a"/></joint>',
])
def test_invalid_link_structure_is_rejected(tmp_path, body):
    service = UrdfRobotService()
    with pytest.raises(UrdfRobotError):
        service._parse_structure(service._parse_xml(write_urdf(tmp_path, body)).getroot(), tmp_path / "robot.urdf")


def test_old_step_robot_is_rejected(tmp_path):
    from laclean.core.scene import SceneNode
    from uuid import uuid4

    node = SceneNode("old", NodeKind.ROBOT, node_id=uuid4(), metadata={"format": "STEP", "asset": "old.stp"})
    with pytest.raises(UrdfRobotError, match="旧 STEP"):
        UrdfRobotService().load_project_asset(node, tmp_path / "project.lcp")


def test_forward_kinematics_applies_revolute_joint_origin():
    data = RobotModelData(
        node_id=__import__("uuid").uuid4(), name="demo", urdf_path=Path("demo.urdf"),
        links=[RobotLink("base"), RobotLink("tool")],
        joints=[RobotJoint("joint", "revolute", "base", "tool",
                           [[1, 0, 0, 100], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                           (0, 0, 1))],
        link_transforms={},
    )
    transforms = UrdfRobotService.forward_kinematics(data, {"joint": 1.5707963267948966})
    assert transforms["tool"][0][3] == 100
    assert abs(transforms["tool"][0][0]) < 1e-9
    assert abs(transforms["tool"][1][0] - 1.0) < 1e-9
