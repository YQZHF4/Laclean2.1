from pathlib import Path

import pytest

from laclean.core.scene import NodeKind
from laclean.services.cad_model_service import CadModelError, CadModelService
from laclean.services.project_service import ProjectService


ROBOT_STEP = (
    Path(__file__).resolve().parents[1] / "模型" / "【机械臂R6-093S】客户模型.stp"
)


def test_robot_step_is_copied_parsed_and_reloadable(tmp_path) -> None:
    project_service = ProjectService()
    document = project_service.create_project("机械臂STEP", tmp_path)

    result = CadModelService().import_to_project(
        ROBOT_STEP, document.file_path, NodeKind.ROBOT
    )

    assert result.node.kind is NodeKind.ROBOT
    assert result.data.shape.IsNull() is False
    assert result.data.root_count == 1
    assert result.data.solid_count == 55
    assert result.data.face_count == 4426
    assert result.data.bounds_max[1] > 1100
    copied = Path(document.file_path).parent / result.node.metadata["asset"]
    assert copied.is_file()
    assert copied.read_bytes() == ROBOT_STEP.read_bytes()

    robot_group = document.root.children[2]
    robot_group.children.clear()
    robot_group.add_child(result.node)
    project_service.save_project(document)
    loaded = project_service.load_project(document.file_path).document
    loaded_node = loaded.find(result.node.node_id)
    assert loaded_node is not None
    restored = CadModelService().load_project_asset(loaded_node, document.file_path)
    assert restored.node_id == result.node.node_id
    assert restored.solid_count == 55
    assert restored.face_count == 4426


def test_unsupported_cad_format_is_rejected(tmp_path) -> None:
    project = ProjectService().create_project("错误数模", tmp_path)
    source = tmp_path / "robot.obj"
    source.write_text("not a STEP", encoding="ascii")

    with pytest.raises(CadModelError, match="不支持"):
        CadModelService().import_to_project(source, project.file_path, NodeKind.ROBOT)
