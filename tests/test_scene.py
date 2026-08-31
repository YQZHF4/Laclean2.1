from laclean.core.scene import NodeKind, SceneDocument


def test_default_scene_hierarchy_contains_reserved_groups() -> None:
    document = SceneDocument.create_default("测试项目")

    assert document.root.name == "测试项目"
    assert document.root.kind is NodeKind.PROJECT
    assert [node.name for node in document.root.children] == [
        "点云",
        "数模",
        "机械臂",
        "工具与振镜",
        "坐标系",
        "路径",
    ]


def test_scene_find_is_recursive() -> None:
    document = SceneDocument.create_default()
    robot = document.root.children[2].children[0]

    assert document.find(robot.node_id) is robot
    assert robot.kind is NodeKind.ROBOT
    assert robot.metadata["placeholder"] is True
