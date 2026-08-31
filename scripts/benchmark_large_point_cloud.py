"""Repeatable large-point-cloud benchmark for selection, LOD, and streaming PLY."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import numpy as np

from laclean.core.point_cloud import PointCloudData
from laclean.core.point_cloud_editing import select_points_in_screen_rectangle
from laclean.services.point_cloud_processing_service import PointCloudProcessingService


def resident_memory_bytes() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    return int(psutil.Process(os.getpid()).memory_info().rss)


def run(point_count: int, write_asset: bool) -> dict[str, object]:
    started = perf_counter()
    points = np.empty((point_count, 3), dtype=np.float32)
    points[:, 0] = np.linspace(-1.0, 1.0, point_count, dtype=np.float32)
    points[:, 1] = np.sin(np.arange(point_count, dtype=np.float32) * 0.0001)
    points[:, 2] = 0.0
    data = PointCloudData(uuid4(), "benchmark", Path("benchmark.ply"), points)
    generated_seconds = perf_counter() - started

    started = perf_counter()
    display_points, _ = data.display_arrays()
    display_seconds = perf_counter() - started

    started = perf_counter()
    selection = select_points_in_screen_rectangle(
        data,
        (250, 250, 750, 750),
        np.eye(4),
        (1000, 1000),
        np.eye(4),
    )
    selection_seconds = perf_counter() - started

    write_seconds = None
    written_bytes = None
    if write_asset:
        with tempfile.TemporaryDirectory(prefix="laclean-benchmark-") as directory:
            project_file = Path(directory) / "project.lcp"
            started = perf_counter()
            persisted = PointCloudProcessingService().persist(data, project_file)
            write_seconds = perf_counter() - started
            written_bytes = persisted.asset_path.stat().st_size

    return {
        "point_count": point_count,
        "data_memory_bytes": data.memory_bytes,
        "resident_memory_bytes": resident_memory_bytes(),
        "display_point_count": len(display_points),
        "selected_count": selection.selected_count,
        "generated_seconds": round(generated_seconds, 4),
        "display_proxy_seconds": round(display_seconds, 4),
        "rectangle_selection_seconds": round(selection_seconds, 4),
        "stream_write_seconds": None if write_seconds is None else round(write_seconds, 4),
        "written_bytes": written_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--points", type=int, default=5_000_000)
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    if arguments.points < 1:
        parser.error("--points must be positive")
    print(json.dumps(run(arguments.points, arguments.write), indent=2))


if __name__ == "__main__":
    main()
