# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Laclean Studio.

Build from the target conda environment, for example:
    pyinstaller --clean main.spec
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


block_cipher = None

ROOT = Path(SPECPATH).resolve()
SRC = ROOT / "src"
ENV_PREFIX = Path(sys.prefix).resolve()
CONDA_LIBRARY_BIN = ENV_PREFIX / "Library" / "bin"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def add_file_if_exists(items, source: Path, target: str = ".") -> None:
    if source.is_file():
        items.append((str(source), target))


def add_directory_if_exists(items, source: Path, target: str) -> None:
    if not source.is_dir():
        return
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            items.append((str(path), str(Path(target) / path.relative_to(source).parent)))


def add_conda_dll_patterns(items, *patterns: str) -> None:
    if not CONDA_LIBRARY_BIN.is_dir():
        return
    seen = {Path(source).resolve() for source, _ in items}
    for pattern in patterns:
        for dll in CONDA_LIBRARY_BIN.glob(pattern):
            resolved = dll.resolve()
            if resolved not in seen:
                items.append((str(dll), "."))
                seen.add(resolved)


datas = []
binaries = []
hiddenimports = []

# Application package and lazily imported native bindings.
hiddenimports += collect_submodules("laclean")
hiddenimports += collect_submodules("OCC")
hiddenimports += collect_submodules("pcl")
hiddenimports += collect_submodules("trimesh")
hiddenimports += collect_submodules("collada")

# Package metadata/data and extension modules discovered by PyInstaller hooks.
datas += collect_data_files("OCC")
datas += collect_data_files("PyQt5")
datas += collect_data_files("trimesh")
binaries += collect_dynamic_libs("trimesh")
binaries += collect_dynamic_libs("OCC")
binaries += collect_dynamic_libs("pcl")
binaries += collect_dynamic_libs("PyQt5")

# Project-side assets that are useful at runtime or as bundled examples.
add_directory_if_exists(datas, ROOT / "模型", "模型")
add_file_if_exists(datas, ROOT / "README.md")
add_file_if_exists(datas, ROOT / "pyproject.toml")

# Native DLLs used by conda-forge pythonocc-core / python-pcl stacks.
add_conda_dll_patterns(
    binaries,
    "TK*.dll",
    "TKernel.dll",
    "pcl_*.dll",
    "vtk*.dll",
    "boost_*.dll",
    "flann*.dll",
    "qhull*.dll",
    "OpenNI*.dll",
    "tbb*.dll",
    "freetype*.dll",
    "freeimage*.dll",
    "zlib*.dll",
    "libpng*.dll",
    "jpeg*.dll",
)


a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "tests",
        "IPython",
        "jupyter",
        "matplotlib.tests",
        "numpy.tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Laclean Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Laclean Studio",
)
