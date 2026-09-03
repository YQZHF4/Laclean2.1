"""URDF import, validation, resource copying, and static mesh assembly."""

from __future__ import annotations

import math
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np

from laclean.core.error_handling import ensure_free_disk_space
from laclean.core.robot_model import RobotJoint, RobotLink, RobotMesh, RobotModelData
from laclean.core.scene import NodeKind, SceneNode


SUPPORTED_ROBOT_MESH_SUFFIXES = {".stl", ".obj", ".dae"}


class UrdfRobotError(RuntimeError):
    """User-facing URDF import or validation failure."""


@dataclass(slots=True)
class ImportedRobotModel:
    node: SceneNode
    data: RobotModelData


class UrdfRobotService:
    def forward_kinematics(data: RobotModelData, joint_positions: dict[str, float]) -> dict[str, list[list[float]]]:
        """Return link poses in millimeters for the supplied URDF joint positions."""
        identity = [[1.0 if row == column else 0.0 for column in range(4)] for row in range(4)]

        def multiply(left, right):
            return [[sum(left[i][k] * right[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

        def joint_motion(joint: RobotJoint, value: float):
            if joint.joint_type in {"revolute", "continuous"}:
                x, y, z = joint.axis
                length = math.sqrt(x * x + y * y + z * z) or 1.0
                x, y, z = x / length, y / length, z / length
                c, s, one = math.cos(value), math.sin(value), 1.0 - math.cos(value)
                return [
                    [c + x*x*one, x*y*one-z*s, x*z*one+y*s, 0.0],
                    [y*x*one+z*s, c+y*y*one, y*z*one-x*s, 0.0],
                    [z*x*one-y*s, z*y*one+x*s, c+z*z*one, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ]
            if joint.joint_type == "prismatic":
                return [[1.0, 0.0, 0.0, joint.axis[0] * value * 1000.0],
                        [0.0, 1.0, 0.0, joint.axis[1] * value * 1000.0],
                        [0.0, 0.0, 1.0, joint.axis[2] * value * 1000.0],
                        [0.0, 0.0, 0.0, 1.0]]
            return identity

        by_parent: dict[str, list[RobotJoint]] = {}
        for joint in data.joints:
            by_parent.setdefault(joint.parent, []).append(joint)
        transforms = {data.root_link: identity} if data.root_link else {}
        stack = list(transforms)
        while stack:
            parent = stack.pop()
            for joint in by_parent.get(parent, []):
                origin_motion = multiply(joint.origin, joint_motion(joint, float(joint_positions.get(joint.name, 0.0))))
                transforms[joint.child] = multiply(transforms[parent], origin_motion)
                stack.append(joint.child)
        return transforms
    def import_to_project(
        self, source_path: str | Path, project_file_path: str | Path
    ) -> ImportedRobotModel:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise UrdfRobotError(f"URDF 文件不存在：\n{source}")
        if source.suffix.lower() != ".urdf":
            raise UrdfRobotError("机械臂文件必须是 .urdf 格式。")

        tree = self._parse_xml(source)
        robot_element = tree.getroot()
        name = robot_element.attrib.get("name", source.stem).strip() or source.stem
        links, joints, mesh_refs = self._parse_structure(robot_element, source)
        node_id = uuid4()
        project_directory = Path(project_file_path).expanduser().resolve().parent
        asset_directory = project_directory / "assets" / "robots" / str(node_id)
        try:
            required_size = source.stat().st_size + sum(
                path.stat().st_size for path in mesh_refs.values()
            )
            ensure_free_disk_space(project_directory, required_size)
            asset_directory.mkdir(parents=True, exist_ok=False)
            urdf_target = asset_directory / source.name
            shutil.copy2(source, urdf_target)
            copied = {}
            for reference, path in mesh_refs.items():
                target = asset_directory / self._asset_relative_path(reference, path, source.parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied[reference] = target
        except (OSError, ValueError) as exc:
            if asset_directory.exists():
                shutil.rmtree(asset_directory, ignore_errors=True)
            raise UrdfRobotError(f"复制 URDF 资源失败：{exc}") from exc

        self._rewrite_mesh_paths(links, copied, asset_directory)
        transforms = self._static_link_transforms(links, joints)
        shapes = self._build_link_shapes(links, asset_directory)
        data = RobotModelData(node_id, name, urdf_target, links, joints, transforms, shapes)
        relative_asset = urdf_target.relative_to(project_directory).as_posix()
        node = SceneNode(name, NodeKind.ROBOT, node_id=node_id, metadata=data.metadata(relative_asset))
        node.metadata["asset_files"] = [
            str(path.relative_to(project_directory).as_posix())
            for path in [urdf_target, *copied.values()]
        ]
        return ImportedRobotModel(node, data)

    def load_project_asset(
        self, node: SceneNode, project_file_path: str | Path
    ) -> RobotModelData:
        if node.kind is not NodeKind.ROBOT:
            raise UrdfRobotError(f"节点“{node.name}”不是机械臂节点。")
        if node.metadata.get("format") == "STEP" or str(node.metadata.get("asset", "")).lower().endswith((".step", ".stp")):
            raise UrdfRobotError(f"机械臂“{node.name}”使用旧 STEP 格式，请重新导入 URDF。")
        raw_asset = node.metadata.get("asset")
        if not isinstance(raw_asset, str) or not raw_asset.lower().endswith(".urdf"):
            raise UrdfRobotError(f"机械臂“{node.name}”缺少有效 URDF 资产。")
        project_directory = Path(project_file_path).expanduser().resolve().parent
        asset_path = (project_directory / raw_asset).resolve()
        if not asset_path.is_relative_to(project_directory) or not asset_path.is_file():
            raise UrdfRobotError(f"URDF 资产不存在：\n{asset_path}")
        result = self.import_structure(asset_path, node.node_id, node.name, project_directory)
        saved_positions = node.metadata.get("joint_positions", {})
        if isinstance(saved_positions, dict):
            result.joint_positions = {
                joint.name: float(saved_positions.get(joint.name, 0.0))
                for joint in result.joints
            }
            result.link_transforms = self.forward_kinematics(result, result.joint_positions)
        return result

    def import_structure(
        self, source: Path, node_id: UUID, name: str, project_directory: Path
    ) -> RobotModelData:
        tree = self._parse_xml(source)
        links, joints, _ = self._parse_structure(tree.getroot(), source)
        asset_directory = source.parent
        self._rewrite_mesh_paths(links, {}, asset_directory)
        return RobotModelData(
            node_id, name, source, links, joints,
            self._static_link_transforms(links, joints),
            self._build_link_shapes(links, asset_directory),
            {joint.name: 0.0 for joint in joints},
        )

    def _parse_xml(self, source: Path) -> ET.ElementTree:
        try:
            tree = ET.parse(source)
        except (ET.ParseError, OSError) as exc:
            raise UrdfRobotError(f"URDF XML 解析失败：{exc}") from exc
        if tree.getroot().tag != "robot":
            raise UrdfRobotError("URDF 根节点必须是 robot。")
        return tree

    def _parse_structure(self, root: ET.Element, source: Path):
        links: list[RobotLink] = []
        link_names: set[str] = set()
        refs: dict[str, Path] = {}
        for element in root.findall("link"):
            name = self._required_name(element, "link")
            if name in link_names:
                raise UrdfRobotError(f"URDF 中存在重复 link：{name}")
            link_names.add(name)
            link = RobotLink(name)
            for visual in element.findall("visual"):
                self._parse_geometry(visual, link.visual_meshes, link.visual_colors, refs, source)
            for collision in element.findall("collision"):
                self._parse_geometry(collision, link.collision_meshes, [], refs, source)
            inertial = element.find("inertial")
            if inertial is not None:
                link.inertial = self._parse_inertial(inertial)
            links.append(link)

        joints: list[RobotJoint] = []
        joint_names: set[str] = set()
        children: set[str] = set()
        for element in root.findall("joint"):
            name = self._required_name(element, "joint")
            if name in joint_names:
                raise UrdfRobotError(f"URDF 中存在重复 joint：{name}")
            parent = self._required_child_name(element, "parent")
            child = self._required_child_name(element, "child")
            if parent not in link_names or child not in link_names:
                raise UrdfRobotError(f"joint {name} 引用了未知 link：{parent} -> {child}")
            if child in children:
                raise UrdfRobotError(f"link {child} 被多个 joint 作为 child 引用。")
            joint_names.add(name)
            children.add(child)
            origin = self._origin(element.find("origin"))
            axis_element = element.find("axis")
            axis = self._vector(axis_element, "xyz", (1.0, 0.0, 0.0))
            limit = element.find("limit")
            joints.append(RobotJoint(
                name, element.attrib.get("type", "fixed"), parent, child, origin, axis,
                self._float_attr(limit, "lower"), self._float_attr(limit, "upper"),
                self._float_attr(limit, "effort"), self._float_attr(limit, "velocity"),
                {key: float(value) for key, value in (element.find("dynamics").attrib.items() if element.find("dynamics") is not None else [])},
            ))
        if links and len(children) != len(links) - 1:
            raise UrdfRobotError("URDF link/joint 关系不是单根树结构。")
        return links, joints, refs

    def _parse_geometry(self, element, meshes, colors, refs, source) -> None:
        geometry = element.find("geometry")
        mesh = geometry.find("mesh") if geometry is not None else None
        if mesh is None or not mesh.attrib.get("filename"):
            return
        filename = mesh.attrib["filename"]
        path = self._resolve_resource(filename, source.parent)
        if path.suffix.lower() not in SUPPORTED_ROBOT_MESH_SUFFIXES:
            raise UrdfRobotError(f"不支持的 URDF 网格格式：{path.suffix}")
        # Keep the scale declared by each URDF mesh. Unit conversion is
        # applied separately during OCC conversion and must not overwrite it.
        scale = self._vector(mesh, "scale", (1.0, 1.0, 1.0))
        meshes.append(RobotMesh(filename, scale=tuple(scale), origin=self._origin(element.find("origin"))))
        refs[filename] = path
        material = element.find("material/color")
        if colors is not None:
            rgba = self._vector(material, "rgba", (0.58, 0.64, 0.72, 1.0))
            colors.append(tuple(rgba))

    @staticmethod
    def _resolve_resource(filename: str, base: Path) -> Path:
        raw = filename.split("package://", 1)[-1].lstrip("/")
        relative_paths = [Path(raw)]
        if filename.startswith("package://") and "/" in raw:
            # A package URI contains the package name before the actual
            # resource path, while the project folder is already that package.
            relative_paths.insert(0, Path(raw.split("/", 1)[1]))
        candidates = [
            base / relative
            for relative in relative_paths
        ] + [
            parent / relative
            for parent in (base.parent, base.parent.parent)
            for relative in relative_paths
        ]
        path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
        if path is None:
            raise UrdfRobotError(f"URDF 网格资源不存在：{filename}")
        return path

    @staticmethod
    def _asset_relative_path(reference: str, path: Path, source_directory: Path) -> Path:
        """Keep visual/collision subdirectories distinct in project assets."""
        if reference.startswith("package://"):
            raw = reference.split("package://", 1)[1].lstrip("/")
            parts = raw.split("/", 1)
            if len(parts) == 2:
                return Path(parts[1])
        try:
            relative = path.resolve().relative_to(source_directory.resolve())
            return relative
        except ValueError:
            return Path("meshes") / path.parent.name / path.name

    @staticmethod
    def _required_name(element, kind: str) -> str:
        name = element.attrib.get("name", "").strip()
        if not name:
            raise UrdfRobotError(f"URDF {kind} 缺少 name。")
        return name

    @staticmethod
    def _required_child_name(element, tag: str) -> str:
        child = element.find(tag)
        name = child.attrib.get("link", "").strip() if child is not None else ""
        if not name:
            raise UrdfRobotError(f"URDF joint 缺少 {tag} link。")
        return name

    @staticmethod
    def _float_attr(element, key: str):
        if element is None or key not in element.attrib:
            return None
        return float(element.attrib[key])

    @staticmethod
    def _vector(element, key: str, default):
        if element is None or key not in element.attrib:
            return default
        values = tuple(float(value) for value in element.attrib[key].split())
        if len(values) != len(default):
            raise UrdfRobotError(f"URDF 属性 {key} 维度错误。")
        return values

    def _origin(self, element) -> list[list[float]]:
        xyz = self._vector(element, "xyz", (0.0, 0.0, 0.0))
        rpy = self._vector(element, "rpy", (0.0, 0.0, 0.0))
        roll, pitch, yaw = rpy
        rx = [[1, 0, 0], [0, math.cos(roll), -math.sin(roll)], [0, math.sin(roll), math.cos(roll)]]
        ry = [[math.cos(pitch), 0, math.sin(pitch)], [0, 1, 0], [-math.sin(pitch), 0, math.cos(pitch)]]
        rz = [[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]]
        def multiply(left, right):
            return [[sum(left[i][k] * right[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        rotation = multiply(multiply(rz, ry), rx)
        return [
            [*rotation[0], xyz[0] * 1000.0],
            [*rotation[1], xyz[1] * 1000.0],
            [*rotation[2], xyz[2] * 1000.0],
            [0.0, 0.0, 0.0, 1.0],
        ]

    @staticmethod
    def _parse_inertial(element) -> dict[str, object]:
        mass = element.find("mass")
        inertia = element.find("inertia")
        return {
            "mass": float(mass.attrib["value"]) if mass is not None and "value" in mass.attrib else None,
            "inertia": dict(inertia.attrib) if inertia is not None else {},
        }

    @staticmethod
    def _rewrite_mesh_paths(links, copied, asset_directory) -> None:
        for link in links:
            for mesh in [*link.visual_meshes, *link.collision_meshes]:
                target = copied.get(mesh.filename)
                if target is None:
                    try:
                        target = UrdfRobotService._resolve_resource(mesh.filename, asset_directory)
                    except UrdfRobotError:
                        target = asset_directory / "meshes" / Path(mesh.filename).name
                mesh.path = str(target)

    @staticmethod
    def _static_link_transforms(links, joints) -> dict[str, list[list[float]]]:
        identity = [[1.0 if row == column else 0.0 for column in range(4)] for row in range(4)]
        def multiply(left, right):
            return [[sum(left[i][k] * right[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
        by_parent: dict[str, list[RobotJoint]] = {}
        for joint in joints:
            by_parent.setdefault(joint.parent, []).append(joint)
        transforms = {link.name: identity for link in links}
        roots = [link.name for link in links if link.name not in {joint.child for joint in joints}]
        stack = list(roots)
        while stack:
            parent = stack.pop()
            for joint in by_parent.get(parent, []):
                transforms[joint.child] = multiply(transforms[parent], joint.origin)
                stack.append(joint.child)
        return transforms

    @staticmethod
    def _build_link_shapes(links, asset_directory):
        # Mesh conversion is intentionally isolated so XML import remains testable
        # without loading OCC. The viewer consumes these shapes when available.
        try:
            import trimesh
            from OCC.Core.BRep import BRep_Builder
            from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
            from OCC.Core.TopoDS import TopoDS_Compound
        except ImportError as exc:
            raise UrdfRobotError("当前环境缺少 trimesh 或 OCC，无法显示 URDF 网格。") from exc

        def make_shape(paths):
            builder = BRep_Builder()
            compound = TopoDS_Compound()
            builder.MakeCompound(compound)
            for descriptor in paths:
                meshes = UrdfRobotService._read_mesh_primitives(descriptor.path, trimesh)
                for mesh in meshes:
                    vertices = np.asarray(mesh.vertices, dtype=float) * np.asarray(descriptor.scale) * 1000.0
                    vertices = (np.asarray(descriptor.origin)[:3, :3] @ vertices.T).T + np.asarray(descriptor.origin)[:3, 3]
                    for face in np.asarray(mesh.faces, dtype=int):
                        polygon = BRepBuilderAPI_MakePolygon()
                        for index in face[:3]:
                            x, y, z = vertices[int(index)]
                            from OCC.Core.gp import gp_Pnt
                            polygon.Add(gp_Pnt(float(x), float(y), float(z)))
                        polygon.Close()
                        builder.Add(compound, BRepBuilderAPI_MakeFace(polygon.Wire()).Shape())
            return compound

        return {link.name: [make_shape(link.visual_meshes)] for link in links if link.visual_meshes}

    @staticmethod
    def _read_mesh_primitives(path: str, trimesh_module):
        """Read DAE primitives the same way as YuanZhuo's DaeImporter."""
        if Path(path).suffix.lower() != ".dae":
            loaded = trimesh_module.load(path, force="scene", process=False)
            return list(loaded.geometry.values()) if isinstance(loaded, trimesh_module.Scene) else [loaded]

        try:
            import collada
            dae = collada.Collada(path)
        except Exception as exc:
            raise UrdfRobotError(f"读取 DAE 网格失败：{path}\n{exc}") from exc

        meshes = []
        geometry_objects = dae.scene.objects("geometry") if dae.scene is not None else dae.geometries
        for geometry in geometry_objects:
            primitives = geometry.primitives() if hasattr(geometry, "primitives") and callable(geometry.primitives) else geometry.primitives
            for primitive in primitives:
                if primitive.__class__.__name__.endswith("Polylist"):
                    primitive = primitive.triangleset()
                vertices = getattr(primitive, "vertex", None)
                if vertices is None:
                    continue
                vertex_index = np.asarray(getattr(primitive, "vertex_index", []), dtype=int)
                if vertex_index.size:
                    expanded = np.asarray(vertices, dtype=float)[vertex_index.reshape(-1)]
                else:
                    expanded = np.asarray(vertices, dtype=float).reshape(-1, 3)
                if len(expanded) < 3 or len(expanded) % 3:
                    continue
                meshes.append(SimpleNamespace(
                    vertices=expanded,
                    faces=np.arange(len(expanded), dtype=int).reshape(-1, 3),
                ))
        if not meshes:
            raise UrdfRobotError(f"DAE 中没有可显示的三角网格：{path}")
        return meshes
