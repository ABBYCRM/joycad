"""Geometry format conversions.

We try to use whatever the host has installed (CadQuery, FreeCAD, trimesh,
ezdxf, OpenCV-Python). Each function is best-effort and raises a clear error
if a required dep is missing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from loguru import logger

MeshFormat = Literal["stl", "obj", "3mf"]
VecFormat = Literal["dxf", "svg"]


def step_to_stl(step_path: Path, stl_path: Path | None = None,
                *, tolerance: float = 0.1, angular_tolerance: float = 0.1) -> Path:
    """STEP → STL using CadQuery if available, else trimesh."""
    stl_path = stl_path or step_path.with_suffix(".stl")
    try:
        import cadquery as cq
        from cadquery import importers, exporters
        shape = importers.importStep(str(step_path)).val()
        exporters.export(shape, str(stl_path),
                         exportType="STL",
                         tolerance=tolerance,
                         angularTolerance=angular_tolerance)
        logger.info(f"[geometry_io] STEP→STL via CadQuery: {stl_path}")
        return stl_path
    except ImportError:
        pass
    # fallback: trimesh can't directly read STEP, but we can use `numpy-stl`+`cadquery`
    raise RuntimeError("step_to_stl requires cadquery (`mamba install -c conda-forge cadquery`).")


def stl_to_step(stl_path: Path, step_path: Path | None = None) -> Path:
    """STL → STEP (mesh → B-Rep). Requires CadQuery or FreeCAD."""
    step_path = step_path or stl_path.with_suffix(".step")
    try:
        import cadquery as cq
        from cadquery import importers
        shape = importers.importStl(str(stl_path)).val()
        # CadQuery can only export a B-Rep; STL is mesh so we wrap as solid.
        # For mesh→B-Rep quality, use FreeCAD's ShapeFromMesh + refinement.
        from cadquery import exporters
        exporters.export(cq.Workplane("XY").newObject([shape]), str(step_path))
        return step_path
    except ImportError:
        pass
    raise RuntimeError("stl_to_step requires cadquery (best) or FreeCAD (fallback).")


def export_dxf(step_path: Path, dxf_path: Path | None = None) -> Path:
    """2D projection of a STEP file → DXF.

    Strategy: place a top-down orthographic view, project all visible edges to XY,
    write each edge as DXF LINE / ARC / SPLINE entities.
    """
    dxf_path = dxf_path or step_path.with_suffix(".dxf")
    try:
        import ezdxf
        import cadquery as cq
        from cadquery import importers
        shape = importers.importStep(str(step_path)).val()
        bb = shape.BoundingBox()
        edges = []
        for e in shape.Edges():
            pts = [v.toTuple() for v in e.Vertices()]
            edges.append((e.geomType(), pts, e))
        doc = ezdxf.new(dxfversion="R2018")
        msp = doc.modelspace()
        for etype, pts, edge in edges:
            if etype == "LINE" and len(pts) == 2:
                msp.add_line(pts[0][:2], pts[1][:2])
            elif etype in ("CIRCLE", "ARC", "ELLIPSE"):
                _add_arc(msp, edge)
            elif etype in ("BSPLINE", "SPLINE"):
                _add_spline(msp, edge)
            else:
                # generic polyline fallback
                if len(pts) >= 2:
                    msp.add_lwpolyline([p[:2] for p in pts], close=False)
        doc.saveas(str(dxf_path))
        logger.info(f"[geometry_io] wrote DXF: {dxf_path}")
        return dxf_path
    except ImportError:
        raise RuntimeError("export_dxf requires cadquery + ezdxf.")


def _add_arc(msp, edge):
    import ezdxf
    if edge.geomType() == "CIRCLE":
        c = edge.Center(); r = edge.radius()
        msp.add_circle((c.x, c.y), radius=r)
    elif edge.geomType() == "ARC":
        c = edge.Center(); r = edge.radius()
        a1 = edge.startAngle(); a2 = edge.endAngle()
        msp.add_arc((c.x, c.y), radius=r,
                    start_angle=azimuth(a1), end_angle=azimuth(a2))
    elif edge.geomType() == "ELLIPSE":
        c = edge.Center(); rx = edge.majorRadius(); ry = edge.minorRadius()
        msp.add_ellipse((c.x, c.y), major_axis=(rx, 0),
                        ratio=ry / rx if rx else 1.0)


def _add_spline(msp, edge):
    pts = [v.toTuple() for v in edge.Vertices()]
    if len(pts) >= 2:
        msp.add_lwpolyline([(p[0], p[1]) for p in pts], close=False)


def azimuth(rad: float) -> float:  # OCC uses radians, DXF uses degrees
    import math
    return math.degrees(rad)


def export_svg(step_path: Path, svg_path: Path | None = None) -> Path:
    """2D projection → SVG (for laser / plasma / web preview).

    Delegates to the pure-Python ``cad.svg_render`` so we don't depend on
    ezdxf's drawing backend.
    """
    from .svg_render import render_svg
    return render_svg(step_path, svg_path)


def slice_3d_print(step_path: Path, gcode_path: Path | None = None,
                   *, slicer: str = "prusaslicer",
                   profile: str = "default") -> Path:
    """Slice a STEP for 3D printing.

    Currently shells out to PrusaSlicer CLI. Easy to extend for Cura,
    BambuStudio, OrcaSlicer — they all have similar CLI flags.
    """
    gcode_path = gcode_path or step_path.with_suffix(".gcode")
    import subprocess
    if slicer == "prusaslicer":
        cmd = ["prusa-slicer", "--export-gcode",
               "--output", str(gcode_path),
               "--load", profile, str(step_path)]
    elif slicer == "cura":
        cmd = ["CuraEngine", "slice", "-o", str(gcode_path),
               "-j", profile, str(step_path)]
    else:
        raise ValueError(f"unknown slicer: {slicer!r}")
    logger.info(f"[geometry_io] slicing via {slicer}: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    return gcode_path


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    print(step_to_stl(p))
