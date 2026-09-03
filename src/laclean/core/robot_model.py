"""URDF-backed robot model data used by the application and viewer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import numpy as np


@dataclass(slots=True)
class RobotJoint:
    name: str
    joint_type: str
    parent: str
    child: str
    origin: list[list[float]]
    axis: tuple[float, float, float]
    lower: float | None = None
    upper: float | None = None
    effort: float | None = None
    velocity: float | None = None
    dynamics: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class RobotMesh:
    """A mesh reference; vertices are treated as millimeters and scaled per URDF."""
    filename: str
    path: str = ""
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    origin: list[list[float]] = field(default_factory=lambda: np.eye(4).tolist())


@dataclass(slots=True)
class RobotLink:
    name: str
    visual_meshes: list[RobotMesh] = field(default_factory=list)
    collision_meshes: list[RobotMesh] = field(default_factory=list)
    visual_colors: list[tuple[float, float, float, float]] = field(default_factory=list)
    inertial: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class RobotModelData:
    node_id: UUID
    name: str
    urdf_path: Path
    links: list[RobotLink]
    joints: list[RobotJoint]
    link_transforms: dict[str, list[list[float]]]
    link_shapes: dict[str, list[object]] = field(default_factory=dict)
    joint_positions: dict[str, float] = field(default_factory=dict)

    @property
    def link_count(self) -> int:
        return len(self.links)

    @property
    def joint_count(self) -> int:
        return len(self.joints)

    @property
    def root_link(self) -> str | None:
        children = {joint.child for joint in self.joints}
        return next((link.name for link in self.links if link.name not in children), None)

    def metadata(self, relative_urdf: str) -> dict[str, object]:
        asset_directory = self.urdf_path.parent

        def relative_mesh_path(mesh: RobotMesh) -> str:
            try:
                return Path(mesh.path).resolve().relative_to(asset_directory.resolve()).as_posix()
            except (OSError, ValueError):
                return f"meshes/{Path(mesh.path).name}"

        return {
            "asset": relative_urdf,
            "source_name": self.urdf_path.name,
            "format": "URDF",
            "model_type": "robot",
            "robot_name": self.name,
            "link_count": self.link_count,
            "joint_count": self.joint_count,
            "links": [
                {
                    "name": link.name,
                    "visual_meshes": [
                        {"filename": mesh.filename, "path": relative_mesh_path(mesh),
                         "scale": list(mesh.scale), "origin": mesh.origin}
                        for mesh in link.visual_meshes
                    ],
                    "collision_meshes": [
                        {"filename": mesh.filename, "path": relative_mesh_path(mesh),
                         "scale": list(mesh.scale), "origin": mesh.origin}
                        for mesh in link.collision_meshes
                    ],
                    "visual_colors": [list(color) for color in link.visual_colors],
                    "inertial": link.inertial,
                }
                for link in self.links
            ],
            "joints": [
                {
                    "name": joint.name,
                    "type": joint.joint_type,
                    "parent": joint.parent,
                    "child": joint.child,
                    "origin": joint.origin,
                    "axis": list(joint.axis),
                    "lower": joint.lower,
                    "upper": joint.upper,
                    "effort": joint.effort,
                    "velocity": joint.velocity,
                    "dynamics": joint.dynamics,
                }
                for joint in self.joints
            ],
            "joint_positions": dict(self.joint_positions) or {joint.name: 0.0 for joint in self.joints},
            "transform": np.eye(4, dtype=float).tolist(),
        }
