"""Create, serialize, validate, and load portable Laclean projects."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from laclean import __version__
from laclean.core.scene import NodeKind, SceneDocument, SceneNode


PROJECT_FORMAT = "laclean-project"
PROJECT_SCHEMA_VERSION = 1
PROJECT_FILE_NAME = "project.lcp"
MAX_PROJECT_FILE_BYTES = 64 * 1024 * 1024
INVALID_PROJECT_NAME_CHARS = set('<>:"/\\|?*')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ProjectError(RuntimeError):
    """Base error shown to the user for project operations."""


class InvalidProjectError(ProjectError):
    """Raised when a project file is malformed or unsupported."""


@dataclass(slots=True)
class LoadedProject:
    document: SceneDocument
    ui_state: dict[str, Any]


class ProjectService:
    """Filesystem boundary for the versioned ``.lcp`` project format."""

    @staticmethod
    def validate_project_name(name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise ProjectError("项目名称不能为空。")
        if any(char in INVALID_PROJECT_NAME_CHARS for char in cleaned):
            raise ProjectError('项目名称不能包含 < > : " / \\ | ? *。')
        if any(ord(char) < 32 for char in cleaned):
            raise ProjectError("项目名称不能包含控制字符。")
        if cleaned.endswith((" ", ".")):
            raise ProjectError("项目名称不能以空格或句点结尾。")
        if cleaned.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            raise ProjectError(f"“{cleaned}”是 Windows 保留名称，不能用作项目名称。")
        return cleaned

    def create_project(self, name: str, parent_directory: str | Path) -> SceneDocument:
        project_name = self.validate_project_name(name)
        parent = Path(parent_directory).expanduser().resolve()
        project_directory = parent / project_name

        try:
            if project_directory.exists() and any(project_directory.iterdir()):
                raise ProjectError(f"目标文件夹不是空文件夹：\n{project_directory}")
            project_directory.mkdir(parents=True, exist_ok=True)
            self._ensure_directories(project_directory)
        except ProjectError:
            raise
        except OSError as exc:
            raise ProjectError(f"无法创建项目目录：{exc}") from exc

        document = SceneDocument.create_default(project_name)
        document.file_path = str(project_directory / PROJECT_FILE_NAME)
        self.save_project(document)
        return document

    def save_project(
        self,
        document: SceneDocument,
        ui_state: dict[str, Any] | None = None,
        target_path: str | Path | None = None,
    ) -> Path:
        raw_path = target_path if target_path is not None else document.file_path
        if raw_path is None:
            raise ProjectError("项目尚未指定保存位置。")

        project_file = Path(raw_path).expanduser().resolve()
        if project_file.suffix.lower() != ".lcp":
            project_file = project_file.with_suffix(".lcp")

        payload = {
            "format": PROJECT_FORMAT,
            "schema_version": PROJECT_SCHEMA_VERSION,
            "application_version": __version__,
            "project": {
                "name": document.root.name,
                "root": self._serialize_node(document.root),
            },
            "ui": ui_state or {},
        }

        temporary_file = project_file.with_name(f".{project_file.name}.tmp")
        try:
            project_file.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_directories(project_file.parent)
            with temporary_file.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_file, project_file)
        except (OSError, TypeError, ValueError) as exc:
            temporary_file.unlink(missing_ok=True)
            raise ProjectError(f"保存项目失败：{exc}") from exc

        document.file_path = str(project_file)
        document.modified = False
        return project_file

    def load_project(self, project_path: str | Path) -> LoadedProject:
        project_file = Path(project_path).expanduser().resolve()
        try:
            if project_file.stat().st_size > MAX_PROJECT_FILE_BYTES:
                raise InvalidProjectError(
                    "项目文件超过 64 MB，可能已损坏或不是 Laclean 项目。"
                )
            with project_file.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except InvalidProjectError:
            raise
        except FileNotFoundError as exc:
            raise ProjectError(f"项目文件不存在：\n{project_file}") from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InvalidProjectError(f"无法读取项目文件：{exc}") from exc

        if not isinstance(payload, dict) or payload.get("format") != PROJECT_FORMAT:
            raise InvalidProjectError("所选文件不是有效的 Laclean 项目。")

        schema_version = payload.get("schema_version")
        if schema_version != PROJECT_SCHEMA_VERSION:
            raise InvalidProjectError(
                f"不支持的项目格式版本：{schema_version}；当前支持版本：{PROJECT_SCHEMA_VERSION}。"
            )

        project_data = payload.get("project")
        if not isinstance(project_data, dict):
            raise InvalidProjectError("项目文件缺少 project 数据。")

        root = self._deserialize_node(project_data.get("root"), location="project.root")
        if root.kind is not NodeKind.PROJECT:
            raise InvalidProjectError("项目根节点类型必须为 project。")
        self._validate_scene(root)

        ui_state = payload.get("ui", {})
        if not isinstance(ui_state, dict):
            raise InvalidProjectError("项目 ui 数据必须是对象。")

        document = SceneDocument(root=root, file_path=str(project_file), modified=False)
        return LoadedProject(document=document, ui_state=ui_state)

    def _validate_scene(self, root: SceneNode) -> None:
        seen: set[UUID] = set()

        def visit(node: SceneNode, location: str) -> None:
            if node.node_id in seen:
                raise InvalidProjectError(f"{location} 使用了重复的节点 UUID。")
            seen.add(node.node_id)
            is_asset_node = node.kind in {NodeKind.POINT_CLOUD, NodeKind.CAD_MODEL} or (
                node.kind is NodeKind.ROBOT and not node.metadata.get("placeholder")
            )
            if is_asset_node:
                asset = node.metadata.get("asset")
                if not isinstance(asset, str) or not asset.strip():
                    raise InvalidProjectError(f"{location} 缺少有效的项目资产路径。")
                asset_path = Path(asset)
                if asset_path.is_absolute() or ".." in asset_path.parts:
                    raise InvalidProjectError(f"{location} 的项目资产路径不安全。")
                for key in ("bounds_min", "bounds_max"):
                    value = node.metadata.get(key)
                    if value is not None and not self._is_finite_vector3(value):
                        raise InvalidProjectError(f"{location}.{key} 必须是三维数字向量。")
            if node.kind is NodeKind.POINT_CLOUD:
                for key in ("point_count", "display_point_count", "memory_bytes"):
                    value = node.metadata.get(key)
                    if value is not None and (
                        isinstance(value, bool) or not isinstance(value, int) or value < 0
                    ):
                        raise InvalidProjectError(f"{location}.{key} 必须是非负整数。")
                transform = node.metadata.get("transform")
                if transform is not None and not self._is_matrix4(transform):
                    raise InvalidProjectError(f"{location}.transform 必须是 4×4 数字矩阵。")
                for key in ("processing_history", "crop_history"):
                    value = node.metadata.get(key)
                    if value is not None and not isinstance(value, list):
                        raise InvalidProjectError(f"{location}.{key} 必须是数组。")
            if node.kind in {NodeKind.CAD_MODEL, NodeKind.ROBOT} and not node.metadata.get(
                "placeholder"
            ):
                for key in ("file_size", "root_count", "solid_count", "face_count"):
                    value = node.metadata.get(key)
                    if value is not None and (
                        isinstance(value, bool) or not isinstance(value, int) or value < 0
                    ):
                        raise InvalidProjectError(f"{location}.{key} 必须是非负整数。")
            for index, child in enumerate(node.children):
                visit(child, f"{location}.children[{index}]")

        visit(root, "project.root")

    @staticmethod
    def _is_matrix4(value: Any) -> bool:
        if not isinstance(value, list) or len(value) != 4:
            return False
        for row in value:
            if not isinstance(row, list) or len(row) != 4:
                return False
            for item in row:
                if (
                    isinstance(item, bool)
                    or not isinstance(item, (int, float))
                    or not math.isfinite(float(item))
                ):
                    return False
        return True

    @staticmethod
    def _is_finite_vector3(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) == 3
            and all(
                not isinstance(item, bool)
                and isinstance(item, (int, float))
                and math.isfinite(float(item))
                for item in value
            )
        )

    @staticmethod
    def _ensure_directories(project_directory: Path) -> None:
        for relative_path in (
            "assets/pointclouds",
            "assets/cad",
            "assets/robots",
            "cache",
            "autosave",
        ):
            (project_directory / relative_path).mkdir(parents=True, exist_ok=True)

    def _serialize_node(self, node: SceneNode) -> dict[str, Any]:
        return {
            "id": str(node.node_id),
            "name": node.name,
            "kind": node.kind.value,
            "visible": node.visible,
            "metadata": node.metadata,
            "children": [self._serialize_node(child) for child in node.children],
        }

    def _deserialize_node(self, raw: Any, location: str) -> SceneNode:
        if not isinstance(raw, dict):
            raise InvalidProjectError(f"{location} 必须是对象。")

        try:
            node_id = UUID(str(raw["id"]))
            name = raw["name"]
            kind = NodeKind(raw["kind"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidProjectError(f"{location} 的节点标识、名称或类型无效。") from exc

        if not isinstance(name, str) or not name.strip():
            raise InvalidProjectError(f"{location}.name 必须是非空字符串。")

        visible = raw.get("visible", True)
        metadata = raw.get("metadata", {})
        children = raw.get("children", [])
        if not isinstance(visible, bool):
            raise InvalidProjectError(f"{location}.visible 必须是布尔值。")
        if not isinstance(metadata, dict):
            raise InvalidProjectError(f"{location}.metadata 必须是对象。")
        if not isinstance(children, list):
            raise InvalidProjectError(f"{location}.children 必须是数组。")

        node = SceneNode(
            name=name,
            kind=kind,
            node_id=node_id,
            visible=visible,
            metadata=metadata,
        )
        for index, child in enumerate(children):
            node.add_child(self._deserialize_node(child, f"{location}.children[{index}]"))
        return node
