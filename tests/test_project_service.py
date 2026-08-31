import json

import pytest

from laclean.core.scene import NodeKind, SceneNode
from laclean.services.project_service import (
    InvalidProjectError,
    ProjectError,
    ProjectService,
)


def test_create_save_and_load_portable_project(tmp_path) -> None:
    service = ProjectService()
    document = service.create_project("清洗测试项目", tmp_path)
    project_directory = tmp_path / "清洗测试项目"
    project_file = project_directory / "project.lcp"

    assert project_file.is_file()
    assert (project_directory / "assets" / "pointclouds").is_dir()
    assert (project_directory / "assets" / "cad").is_dir()
    assert (project_directory / "assets" / "robots").is_dir()
    assert (project_directory / "cache").is_dir()
    assert (project_directory / "autosave").is_dir()

    point_cloud_group = document.root.children[0]
    cloud = point_cloud_group.add_child(
        SceneNode(
            "相机点云 001",
            NodeKind.POINT_CLOUD,
            metadata={"asset": "assets/pointclouds/cloud-001/source.ply", "unit": "mm"},
        )
    )
    original_id = cloud.node_id
    document.modified = True

    service.save_project(
        document,
        ui_state={"main_window_state": "test-layout"},
    )
    loaded = service.load_project(project_file)

    loaded_cloud = loaded.document.root.children[0].children[0]
    assert loaded.document.root.name == "清洗测试项目"
    assert loaded.document.modified is False
    assert loaded_cloud.node_id == original_id
    assert loaded_cloud.kind is NodeKind.POINT_CLOUD
    assert loaded_cloud.metadata["unit"] == "mm"
    assert loaded.ui_state == {"main_window_state": "test-layout"}
    assert not (project_directory / ".project.lcp.tmp").exists()


@pytest.mark.parametrize("name", ["", "bad/name", "bad*name", "trailing.", "CON"])
def test_invalid_project_names_are_rejected(tmp_path, name) -> None:
    with pytest.raises(ProjectError):
        ProjectService().create_project(name, tmp_path)


def test_invalid_or_future_project_files_are_rejected(tmp_path) -> None:
    invalid_file = tmp_path / "invalid.lcp"
    invalid_file.write_text("not-json", encoding="utf-8")
    with pytest.raises(InvalidProjectError):
        ProjectService().load_project(invalid_file)

    future_file = tmp_path / "future.lcp"
    future_file.write_text(
        json.dumps({"format": "laclean-project", "schema_version": 999}),
        encoding="utf-8",
    )
    with pytest.raises(InvalidProjectError, match="999"):
        ProjectService().load_project(future_file)


def test_duplicate_node_ids_and_unsafe_assets_are_rejected(tmp_path) -> None:
    service = ProjectService()
    document = service.create_project("损坏项目", tmp_path)
    project_path = tmp_path / "损坏项目" / "project.lcp"
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    root = payload["project"]["root"]
    root["children"][0]["id"] = root["id"]
    project_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvalidProjectError, match="重复"):
        service.load_project(project_path)

    document = service.create_project("不安全资产", tmp_path)
    group = document.root.children[0]
    group.add_child(
        SceneNode("越界", NodeKind.POINT_CLOUD, metadata={"asset": "../outside.ply"})
    )
    service.save_project(document)
    with pytest.raises(InvalidProjectError, match="不安全"):
        service.load_project(document.file_path)


def test_oversized_project_is_rejected_before_json_parsing(tmp_path) -> None:
    oversized = tmp_path / "oversized.lcp"
    with oversized.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)

    with pytest.raises(InvalidProjectError, match="超过 64 MB"):
        ProjectService().load_project(oversized)
