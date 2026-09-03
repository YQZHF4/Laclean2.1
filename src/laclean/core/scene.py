"""UI-independent scene hierarchy used by the project tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class NodeKind(str, Enum):
    PROJECT = "project"
    GROUP = "group"
    POINT_CLOUD = "point_cloud"
    CAD_MODEL = "cad_model"
    ROBOT = "robot"
    TOOL = "tool"
    COORDINATE_FRAME = "coordinate_frame"
    PATH = "path"


@dataclass(slots=True)
class SceneNode:
    name: str
    kind: NodeKind
    node_id: UUID = field(default_factory=uuid4)
    visible: bool = True
    children: list["SceneNode"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_child(self, node: "SceneNode") -> "SceneNode":
        self.children.append(node)
        return node

    def find(self, node_id: UUID) -> "SceneNode | None":
        if self.node_id == node_id:
            return self
        for child in self.children:
            match = child.find(node_id)
            if match is not None:
                return match
        return None


@dataclass(slots=True)
class SceneDocument:
    root: SceneNode
    file_path: str | None = None
    modified: bool = False

    @classmethod
    def create_default(cls, name: str = "未命名项目") -> "SceneDocument":
        root = SceneNode(name=name, kind=NodeKind.PROJECT)

        point_clouds = root.add_child(
            SceneNode("点云", NodeKind.GROUP, metadata={"group": "point_clouds"})
        )
        cad_models = root.add_child(
            SceneNode("数模", NodeKind.GROUP, metadata={"group": "cad_models"})
        )
        robots = root.add_child(
            SceneNode("机械臂", NodeKind.GROUP, metadata={"group": "robots"})
        )
        root.add_child(SceneNode("工具与振镜", NodeKind.GROUP, metadata={"group": "tools"}))
        root.add_child(SceneNode("坐标系", NodeKind.GROUP, metadata={"group": "frames"}))
        root.add_child(SceneNode("路径", NodeKind.GROUP, metadata={"group": "paths"}))

        point_clouds.metadata["accepted_formats"] = [
            ".pcd",
            ".ply",
            ".xyz",
            ".xyzn",
            ".xyzrgb",
            ".pts",
        ]
        cad_models.metadata["accepted_formats"] = [".step", ".stp"]
        robots.metadata["accepted_formats"] = [".urdf"]
        return cls(root=root)

    def find(self, node_id: UUID) -> SceneNode | None:
        return self.root.find(node_id)
