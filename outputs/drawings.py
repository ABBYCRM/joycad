"""2D drawings — DXF and SVG output of the part's top projection.

For full 2D drawings with title block, dimensions, etc., see the
``cam/drawings.py`` module (TODO). This module is the simple shop-floor
projection needed for laser cutting and quick-look SVGs.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from cad.geometry_io import export_dxf, export_svg


def make_dxf(step_path: Path, out_path: Path | None = None) -> Path:
    """Top-down projection of the STEP as a DXF file."""
    try:
        return export_dxf(step_path, out_path)
    except Exception as e:
        logger.error(f"[drawings] DXF failed: {e}")
        raise


def make_svg(step_path: Path, out_path: Path | None = None) -> Path:
    """Top-down projection as SVG."""
    try:
        return export_svg(step_path, out_path)
    except Exception as e:
        logger.error(f"[drawings] SVG failed: {e}")
        raise
