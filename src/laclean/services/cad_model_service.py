"""STEP import, portable project copying, and Open CASCADE metadata extraction."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from laclean.core.cad_model import CadModelData
from laclean.core.error_handling import ensure_free_disk_space
from laclean.core.scene import NodeKind, SceneNode


SUPPORTED_CAD_SUFFIXES = {".step", ".stp"}


class CadModelError(RuntimeError):
    """User-facing CAD import or restoration failure."""


@dataclass(slots=True)
class ImportedCadModel:
    node: SceneNode
    data: CadModelData


class CadModelService:
    def import_to_project(
        self,
        source_path: str | Path,
        project_file_path: str | Path,
        node_kind: NodeKind = NodeKind.CAD_MODEL,
    ) -> ImportedCadModel:
        if node_kind not in {NodeKind.CAD_MODEL, NodeKind.ROBOT}:
            raise CadModelError("STEP 只能导入为数模或机械臂模型。")
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise CadModelError(f"STEP 文件不存在：\n{source}")
        if source.suffix.lower() not in SUPPORTED_CAD_SUFFIXES:
            raise CadModelError(f"不支持的数模格式：{source.suffix or '<无扩展名>'}")

        node_id = uuid4()
        project_directory = Path(project_file_path).expanduser().resolve().parent
        category = "robots" if node_kind is NodeKind.ROBOT else "cad"
        asset_directory = project_directory / "assets" / category / str(node_id)
        asset_file = asset_directory / source.name
        try:
            ensure_free_disk_space(project_directory, source.stat().st_size)
        except OSError as exc:
            raise CadModelError(f"项目磁盘空间不足：{exc}") from exc

        data = self._read_step(source, node_id=node_id, name=source.stem)
        try:
            asset_directory.mkdir(parents=True, exist_ok=False)
            shutil.copy2(source, asset_file)
        except OSError as exc:
            if asset_directory.exists():
                shutil.rmtree(asset_directory, ignore_errors=True)
            raise CadModelError(f"复制 STEP 到项目目录失败：{exc}") from exc

        relative_asset = asset_file.relative_to(project_directory).as_posix()
        node = SceneNode(
            name=source.stem,
            kind=node_kind,
            node_id=node_id,
            metadata={
                "asset": relative_asset,
                "source_name": source.name,
                "format": "STEP",
                "model_type": "robot" if node_kind is NodeKind.ROBOT else "cad",
                "file_size": data.file_size,
                "root_count": data.root_count,
                "solid_count": data.solid_count,
                "face_count": data.face_count,
                "mesh_deflection": data.mesh_deflection,
                "bounds_min": list(data.bounds_min),
                "bounds_max": list(data.bounds_max),
                "display_color": [0.72, 0.76, 0.82],
            },
        )
        data.asset_path = asset_file
        return ImportedCadModel(node, data)

    def load_project_asset(
        self, node: SceneNode, project_file_path: str | Path
    ) -> CadModelData:
        if node.kind not in {NodeKind.CAD_MODEL, NodeKind.ROBOT}:
            raise CadModelError(f"节点“{node.name}”不是 CAD 或机械臂模型。")
        if node.metadata.get("placeholder"):
            raise CadModelError(f"节点“{node.name}”只是预留接口，没有 STEP 资产。")
        raw_asset = node.metadata.get("asset")
        if not isinstance(raw_asset, str) or not raw_asset:
            raise CadModelError(f"模型“{node.name}”缺少项目资产路径。")

        project_directory = Path(project_file_path).expanduser().resolve().parent
        asset_path = (project_directory / Path(raw_asset)).resolve()
        if not asset_path.is_relative_to(project_directory):
            raise CadModelError(f"模型“{node.name}”的资产路径越出了项目目录。")
        if not asset_path.is_file():
            raise CadModelError(f"STEP 资产不存在：\n{asset_path}")
        return self._read_step(asset_path, node.node_id, node.name)

    def _read_step(self, path: Path, node_id: UUID, name: str) -> CadModelData:
        try:
            from OCC.Core.Bnd import Bnd_Box
            from OCC.Core.BRepBndLib import brepbndlib
            from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
            from OCC.Core.IFSelect import IFSelect_RetDone
            from OCC.Core.STEPControl import STEPControl_Reader
            from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_SOLID
            from OCC.Core.TopExp import TopExp_Explorer
        except ImportError as exc:
            raise CadModelError("当前环境缺少 pythonocc-core，无法读取 STEP。") from exc

        try:
            reader = STEPControl_Reader()
            status = reader.ReadFile(str(path))
            if status != IFSelect_RetDone:
                raise CadModelError(f"STEP 文件读取失败，OCCT 状态码：{int(status)}")
            root_count = int(reader.NbRootsForTransfer())
            transferred = int(reader.TransferRoots())
            shape = reader.OneShape()
            if transferred <= 0 or shape.IsNull():
                raise CadModelError("STEP 文件中没有可转换的几何形状。")

            solid_count = self._count_subshapes(shape, TopAbs_SOLID, TopExp_Explorer)
            face_count = self._count_subshapes(shape, TopAbs_FACE, TopExp_Explorer)
            box = Bnd_Box()
            brepbndlib.Add(shape, box)
            if box.IsVoid():
                raise CadModelError("STEP 几何没有有效包围盒。")
            xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
            diagonal = (
                (xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2
            ) ** 0.5
            mesh_deflection = max(0.05, float(diagonal) * 0.0005)
            mesher = BRepMesh_IncrementalMesh(
                shape, mesh_deflection, False, 0.5, True
            )
            if not mesher.IsDone():
                raise CadModelError("STEP 几何三角化失败。")
        except CadModelError:
            raise
        except MemoryError:
            raise
        except Exception as exc:
            raise CadModelError(f"解析 STEP 失败：{exc}") from exc

        return CadModelData(
            node_id=node_id,
            name=name,
            asset_path=path,
            shape=shape,
            file_size=path.stat().st_size,
            root_count=root_count,
            solid_count=solid_count,
            face_count=face_count,
            mesh_deflection=mesh_deflection,
            bounds_min=(float(xmin), float(ymin), float(zmin)),
            bounds_max=(float(xmax), float(ymax), float(zmax)),
        )

    @staticmethod
    def _count_subshapes(shape: object, shape_type: object, explorer_type: type) -> int:
        explorer = explorer_type(shape, shape_type)
        count = 0
        while explorer.More():
            count += 1
            explorer.Next()
        return count
