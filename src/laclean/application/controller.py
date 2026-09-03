"""UI-independent application state and scene mutation operations."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from laclean.core.cad_model import CadModelData
from laclean.core.point_cloud import PointCloudData
from laclean.core.point_cloud_editing import (
    EditCommandHistory,
    PointCloudEditCommand,
    PointCloudEditState,
    apply_edit_state,
    metadata_for_cropped_data,
)
from laclean.core.scene import NodeKind, SceneDocument, SceneNode
from laclean.services.cad_model_service import CadModelService
from laclean.services.point_cloud_service import PointCloudService
from laclean.services.project_service import ProjectService

if TYPE_CHECKING:
    from laclean.services.point_cloud_processing_service import (
        PersistedPointCloud,
        ProcessedPointCloud,
    )


class ApplicationController:
    """Own application state and coordinate domain services without widgets."""

    def __init__(self) -> None:
        self.project_service = ProjectService()
        self.point_cloud_service = PointCloudService()
        self.cad_model_service = CadModelService()
        self.document = SceneDocument.create_default()
        self.point_clouds: dict[UUID, PointCloudData] = {}
        self.cad_models: dict[UUID, CadModelData] = {}
        self.edit_history = EditCommandHistory(limit=20)

    def replace_document(self, document: SceneDocument) -> None:
        self.document = document
        self.point_clouds.clear()
        self.cad_models.clear()
        self.edit_history.clear()

    def find_node(self, node_id: UUID) -> SceneNode | None:
        return self.document.find(node_id)

    def set_visibility(self, node: SceneNode, visible: bool) -> bool:
        if node.kind in {NodeKind.PROJECT, NodeKind.GROUP}:
            return False
        node.visible = bool(visible)
        self.document.modified = True
        return True

    def update_transform(self, node_id: UUID, matrix: object) -> SceneNode | None:
        node = self.find_node(node_id)
        if node is None or node.kind not in {NodeKind.POINT_CLOUD, NodeKind.CAD_MODEL}:
            return None
        node.metadata["transform"] = deepcopy(matrix)
        if node.kind is NodeKind.POINT_CLOUD:
            node.metadata["coordinate_mode"] = "local"
        self.document.modified = True
        return node

    def register_point_cloud(self, node: SceneNode, data: PointCloudData) -> None:
        self.point_clouds[node.node_id] = data

    def register_cad_model(self, node: SceneNode, data: CadModelData) -> None:
        self.cad_models[node.node_id] = data

    def add_point_cloud(self, node: SceneNode, data: PointCloudData) -> bool:
        group = self.point_cloud_group()
        if group is None or node.kind is not NodeKind.POINT_CLOUD:
            return False
        group.add_child(node)
        self.register_point_cloud(node, data)
        self.document.modified = True
        return True

    def add_cad_model(self, node: SceneNode, data: CadModelData) -> bool:
        group = self.robot_group() if node.kind is NodeKind.ROBOT else self.cad_model_group()
        if group is None or node.kind not in {NodeKind.CAD_MODEL, NodeKind.ROBOT}:
            return False
        if node.kind is NodeKind.ROBOT:
            group.children = [
                child for child in group.children if not child.metadata.get("placeholder")
            ]
        group.add_child(node)
        self.register_cad_model(node, data)
        self.document.modified = True
        return True

    def apply_processed_result(
        self,
        node: SceneNode,
        preview: ProcessedPointCloud,
        persisted: PersistedPointCloud,
    ) -> None:
        data = preview.data
        data.asset_path = persisted.asset_path
        metadata = node.metadata
        metadata.setdefault("original_asset", metadata.get("asset"))
        metadata["asset"] = persisted.relative_asset
        metadata["point_count"] = data.point_count
        metadata["display_point_count"] = len(data.display_arrays()[0])
        metadata["has_colors"] = data.has_colors
        metadata["has_normals"] = data.has_normals
        metadata["bounds_min"] = data.bounds_min.astype(float).tolist()
        metadata["bounds_max"] = data.bounds_max.astype(float).tolist()
        metadata["memory_bytes"] = data.memory_bytes
        history = metadata.setdefault("processing_history", [])
        if not isinstance(history, list):
            history = []
            metadata["processing_history"] = history
        history.append(
            {
                "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "asset": persisted.relative_asset,
                "options": preview.options.to_dict(),
                "summary": preview.summary.to_dict(),
            }
        )
        self.point_clouds[node.node_id] = data
        self.edit_history.clear()
        self.document.modified = True

    def apply_cropped_result(
        self,
        node: SceneNode,
        before: PointCloudEditState,
        cropped: object,
        persisted: PersistedPointCloud,
    ) -> tuple[PointCloudEditCommand, int]:
        after_metadata = metadata_for_cropped_data(
            node,
            cropped,
            persisted.relative_asset,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        after = PointCloudEditState(cropped.data, after_metadata)
        command_text = (
            "矩形裁剪（保留框内）"
            if cropped.mode == "keep"
            else "矩形裁剪（删除框内）"
        )
        command = PointCloudEditCommand(node.node_id, command_text, before, after)
        self.apply_edit_state(node, after)
        trimmed = self.edit_history.push(command)
        return command, trimmed

    def apply_edit_state(self, node: SceneNode, state: PointCloudEditState) -> None:
        apply_edit_state(node, state)
        self.point_clouds[node.node_id] = state.data
        self.document.modified = True

    def undo_edit(self) -> PointCloudEditCommand | None:
        return self.edit_history.undo()

    def redo_edit(self) -> PointCloudEditCommand | None:
        return self.edit_history.redo()

    def point_cloud_group(self) -> SceneNode | None:
        return self._group_by_name("point_clouds")

    def cad_model_group(self) -> SceneNode | None:
        return self._group_by_name("cad_models")

    def robot_group(self) -> SceneNode | None:
        return self._group_by_name("robots")

    def point_cloud_nodes(self) -> list[SceneNode]:
        group = self.point_cloud_group()
        return [] if group is None else [
            node for node in group.children if node.kind is NodeKind.POINT_CLOUD
        ]

    def cad_model_nodes(self) -> list[SceneNode]:
        nodes: list[SceneNode] = []
        cad_group = self.cad_model_group()
        robot_group = self.robot_group()
        if cad_group is not None:
            nodes.extend(node for node in cad_group.children if node.kind is NodeKind.CAD_MODEL)
        if robot_group is not None:
            nodes.extend(
                node
                for node in robot_group.children
                if node.kind is NodeKind.ROBOT and not node.metadata.get("placeholder")
            )
        return nodes

    def _group_by_name(self, group_name: str) -> SceneNode | None:
        return next(
            (
                node
                for node in self.document.root.children
                if node.metadata.get("group") == group_name
            ),
            None,
        )
