"""Dialog for creating a portable project directory."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QStandardPaths
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from laclean.services.project_service import ProjectError, ProjectService


class NewProjectDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建项目")
        self.setModal(True)
        self.setMinimumWidth(560)

        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        default_parent = Path(documents or str(Path.home())) / "Laclean Projects"

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        heading = QLabel("创建激光清洗离线编程项目")
        heading.setProperty("section", True)
        root_layout.addWidget(heading)

        description = QLabel(
            "项目将保存为独立文件夹，点云和后续数模资产会复制到项目目录中。"
        )
        description.setProperty("muted", True)
        description.setWordWrap(True)
        root_layout.addWidget(description)

        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit("新建项目")
        self.name_edit.selectAll()
        self.parent_edit = QLineEdit(str(default_parent))

        browse_button = QPushButton("浏览…")
        browse_button.clicked.connect(self._browse_parent)
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(self.parent_edit, 1)
        path_row.addWidget(browse_button)

        form.addRow("项目名称", self.name_edit)
        form.addRow("保存位置", path_row)
        root_layout.addLayout(form)

        self.target_label = QLabel()
        self.target_label.setProperty("muted", True)
        self.target_label.setWordWrap(True)
        root_layout.addWidget(self.target_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("创建")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root_layout.addWidget(buttons)

        self.name_edit.textChanged.connect(self._update_target)
        self.parent_edit.textChanged.connect(self._update_target)
        self._update_target()

    @property
    def project_name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def parent_directory(self) -> Path:
        return Path(self.parent_edit.text().strip()).expanduser()

    def _browse_parent(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择项目保存位置",
            self.parent_edit.text(),
            QFileDialog.ShowDirsOnly,
        )
        if directory:
            self.parent_edit.setText(directory)

    def _update_target(self) -> None:
        name = self.name_edit.text().strip() or "<项目名称>"
        parent = self.parent_edit.text().strip() or "<保存位置>"
        self.target_label.setText(f"项目目录：{Path(parent) / name}")

    def _validate_and_accept(self) -> None:
        try:
            ProjectService.validate_project_name(self.project_name)
            if not self.parent_edit.text().strip():
                raise ProjectError("请选择项目保存位置。")
            target = self.parent_directory / self.project_name
            if target.exists() and any(target.iterdir()):
                raise ProjectError(f"目标文件夹不是空文件夹：\n{target}")
        except (ProjectError, OSError) as exc:
            QMessageBox.warning(self, "无法创建项目", str(exc))
            return
        self.accept()
