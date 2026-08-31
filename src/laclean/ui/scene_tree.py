"""Project scene hierarchy widget."""

from __future__ import annotations

from uuid import UUID

from PyQt5.QtCore import QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAction,
    QHeaderView,
    QMenu,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
)

from laclean.core.scene import NodeKind, SceneDocument, SceneNode


NODE_ID_ROLE = Qt.UserRole
NODE_KIND_ROLE = Qt.UserRole + 1


class SceneTreeWidget(QTreeWidget):
    node_selected = pyqtSignal(object)
    action_requested = pyqtSignal(str, object)

    def __init__(self, document: SceneDocument, parent=None) -> None:
        super().__init__(parent)
        self._document = document
        self.setObjectName("sceneTree")
        self.setHeaderLabels(["对象", "状态"])
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.setColumnWidth(1, 54)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlternatingRowColors(True)
        self.setAnimated(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QTreeWidget.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_context_menu)
        self.itemSelectionChanged.connect(self._emit_selection)
        self.itemChanged.connect(self._on_item_changed)
        self.rebuild()

    @property
    def document(self) -> SceneDocument:
        return self._document

    def set_document(self, document: SceneDocument) -> None:
        self._document = document
        self.rebuild()

    def select_node(self, node_id: UUID) -> bool:
        target = str(node_id)
        for index in range(self.topLevelItemCount()):
            match = self._find_item(self.topLevelItem(index), target)
            if match is not None:
                self.setCurrentItem(match)
                self.scrollToItem(match)
                return True
        return False

    def _find_item(self, item: QTreeWidgetItem, node_id: str) -> QTreeWidgetItem | None:
        if item.data(0, NODE_ID_ROLE) == node_id:
            return item
        for index in range(item.childCount()):
            match = self._find_item(item.child(index), node_id)
            if match is not None:
                return match
        return None

    def rebuild(self) -> None:
        self.blockSignals(True)
        self.clear()
        root_item = self._make_item(self._document.root)
        self.addTopLevelItem(root_item)
        self._populate(root_item, self._document.root)
        root_item.setExpanded(True)
        for index in range(root_item.childCount()):
            root_item.child(index).setExpanded(True)
        self.blockSignals(False)
        self.setCurrentItem(root_item)

    def _populate(self, parent_item: QTreeWidgetItem, parent_node: SceneNode) -> None:
        for child_node in parent_node.children:
            child_item = self._make_item(child_node)
            parent_item.addChild(child_item)
            self._populate(child_item, child_node)

    def _make_item(self, node: SceneNode) -> QTreeWidgetItem:
        item = QTreeWidgetItem([node.name, self._status_text(node)])
        item.setData(0, NODE_ID_ROLE, str(node.node_id))
        item.setData(0, NODE_KIND_ROLE, node.kind.value)
        item.setIcon(0, self._icon_for(node.kind))

        if node.kind not in {NodeKind.PROJECT, NodeKind.GROUP}:
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if node.visible else Qt.Unchecked)
        if node.metadata.get("placeholder"):
            item.setForeground(0, Qt.gray)
        return item

    @staticmethod
    def _status_text(node: SceneNode) -> str:
        if node.metadata.get("placeholder"):
            return "预留"
        if node.kind in {NodeKind.PROJECT, NodeKind.GROUP}:
            return ""
        return "显示" if node.visible else "隐藏"

    def _icon_for(self, kind: NodeKind) -> QIcon:
        style = self.style()
        mapping = {
            NodeKind.PROJECT: QStyle.SP_DirHomeIcon,
            NodeKind.GROUP: QStyle.SP_DirIcon,
            NodeKind.POINT_CLOUD: QStyle.SP_FileIcon,
            NodeKind.CAD_MODEL: QStyle.SP_FileIcon,
            NodeKind.ROBOT: QStyle.SP_ComputerIcon,
            NodeKind.TOOL: QStyle.SP_DriveNetIcon,
            NodeKind.COORDINATE_FRAME: QStyle.SP_ArrowUp,
            NodeKind.PATH: QStyle.SP_FileDialogDetailedView,
        }
        return style.standardIcon(mapping[kind])

    def _node_for_item(self, item: QTreeWidgetItem | None) -> SceneNode | None:
        if item is None:
            return None
        raw_id = item.data(0, NODE_ID_ROLE)
        if not raw_id:
            return None
        return self._document.find(UUID(raw_id))

    def _emit_selection(self) -> None:
        self.node_selected.emit(self._node_for_item(self.currentItem()))

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        node = self._node_for_item(item)
        if node is None or node.kind in {NodeKind.PROJECT, NodeKind.GROUP}:
            return
        node.visible = item.checkState(0) == Qt.Checked
        item.setText(1, self._status_text(node))
        self.action_requested.emit("visibility_changed", node)

    def _open_context_menu(self, position: QPoint) -> None:
        item = self.itemAt(position)
        node = self._node_for_item(item)
        if node is None:
            return

        menu = QMenu(self)
        group = node.metadata.get("group")

        if node.kind is NodeKind.POINT_CLOUD:
            self._add_action(menu, "设置点云位置", "set_point_cloud_pose", node)
            menu.addSeparator()
            self._add_action(menu, "基本点云处理", "process_point_cloud", node)
            self._add_action(menu, "手动矩形裁剪", "crop_point_cloud", node)
        elif node.kind is NodeKind.ROBOT:
            self._add_action(menu, "正运动学", "forward_kinematics", node)
            self._add_action(menu, "逆运动学", "inverse_kinematics", node)
            menu.addSeparator()
            self._add_action(menu, "碰撞检测", "collision_check", node)
        elif group == "point_clouds":
            self._add_action(menu, "导入点云…", "import_point_cloud", node)
        elif group == "cad_models":
            self._add_action(menu, "导入数模…", "import_cad", node)
        elif group == "robots":
            self._add_action(menu, "导入机械臂 STEP…", "import_robot", node)
        elif node.kind is NodeKind.PROJECT:
            self._add_action(menu, "保存项目", "save_project", node)

        if node.kind not in {NodeKind.PROJECT, NodeKind.GROUP}:
            menu.addSeparator()
            self._add_action(menu, "重命名", "rename_node", node)
            self._add_action(menu, "删除", "delete_node", node)

        if not menu.isEmpty():
            menu.exec_(self.viewport().mapToGlobal(position))

    def _add_action(self, menu: QMenu, text: str, action_id: str, node: SceneNode) -> QAction:
        action = menu.addAction(text)
        action.triggered.connect(
            lambda checked=False, requested=action_id, target=node: self.action_requested.emit(
                requested, target
            )
        )
        return action
