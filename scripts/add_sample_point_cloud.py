"""Add a colored wave-surface PLY to an existing Laclean project."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
import open3d as o3d

from laclean.services.point_cloud_service import PointCloudService
from laclean.services.project_service import ProjectService


SAMPLE_FILE_NAME = "colored_wave_surface.ply"


def add_sample(project_path: Path) -> None:
    project_service = ProjectService()
    loaded = project_service.load_project(project_path)
    document = loaded.document
    point_group = next(
        node
        for node in document.root.children
        if node.metadata.get("group") == "point_clouds"
    )
    if any(
        node.metadata.get("source_name") == SAMPLE_FILE_NAME
        for node in point_group.children
    ):
        raise RuntimeError("The sample point cloud already exists in this project.")

    x_values = np.linspace(-150.0, 150.0, 120)
    y_values = np.linspace(-100.0, 100.0, 90)
    x_grid, y_grid = np.meshgrid(x_values, y_values)
    z_grid = (
        13.0 * np.sin(x_grid / 34.0) * np.cos(y_grid / 27.0)
        + 22.0
        * np.exp(-((x_grid - 35.0) ** 2 + (y_grid + 12.0) ** 2) / 3200.0)
    )
    points = np.column_stack((x_grid.ravel(), y_grid.ravel(), z_grid.ravel()))

    z_normalized = (z_grid.ravel() - z_grid.min()) / (z_grid.max() - z_grid.min())
    colors = np.column_stack(
        (
            (x_grid.ravel() - x_grid.min()) / (x_grid.max() - x_grid.min()),
            (y_grid.ravel() - y_grid.min()) / (y_grid.max() - y_grid.min()),
            1.0 - 0.65 * z_normalized,
        )
    )

    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    cloud.colors = o3d.utility.Vector3dVector(np.clip(colors, 0.0, 1.0))
    cloud.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=12.0, max_nn=30)
    )

    with tempfile.TemporaryDirectory() as temporary_directory:
        source_path = Path(temporary_directory) / SAMPLE_FILE_NAME
        if not o3d.io.write_point_cloud(str(source_path), cloud, write_ascii=False):
            raise RuntimeError("Failed to write sample PLY file.")
        imported = PointCloudService().import_to_project(source_path, project_path)

    point_group.add_child(imported.node)
    project_service.save_project(document, ui_state=loaded.ui_state)

    print(f"NODE_UUID={imported.node.node_id}")
    print(f"POINT_COUNT={imported.data.point_count}")
    print(f"HAS_COLORS={imported.data.has_colors}")
    print(f"HAS_NORMALS={imported.data.has_normals}")
    print(f"ASSET={imported.node.metadata['asset']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path, help="Path to project.lcp")
    args = parser.parse_args()
    add_sample(args.project.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
