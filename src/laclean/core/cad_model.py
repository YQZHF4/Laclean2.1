"""In-memory Open CASCADE shape and extracted CAD metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(slots=True)
class CadModelData:
    node_id: UUID
    name: str
    asset_path: Path
    shape: object
    file_size: int
    root_count: int
    solid_count: int
    face_count: int
    mesh_deflection: float
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
