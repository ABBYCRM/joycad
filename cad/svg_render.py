"""Pure-Python SVG renderer for STEP top-down projections.

Doesn't depend on ezdxf's SVG backend (which broke in 1.4+). Reads
the STEP via CadQuery and emits a clean, hand-rolled SVG with:

    • all visible edges as <line> or <path> (for arcs/circles)
    • proper viewBox from bounding box
    • reasonable stroke width

The result is browser-renderable and prints correctly.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from loguru import logger


def render_svg(step_path: Path, svg_path: Path | None = None,
               *, margin_px: int = 20, stroke: str = "#1a1a1a",
               fill: str = "none", stroke_width: float = 0.4) -> Path:
    """Render the top-down (XY) projection of a STEP file as SVG."""
    svg_path = svg_path or step_path.with_suffix(".svg")
    try:
        import cadquery as cq
        from cadquery import importers
    except ImportError as e:
        raise RuntimeError("cadquery required for SVG rendering") from e

    shape = importers.importStep(str(step_path)).val()
    bb = shape.BoundingBox()

    paths: list[str] = []
    for edge in shape.Edges():
        gt = edge.geomType()
        if gt == "LINE":
            pts = [(v.X, v.Y) for v in edge.Vertices()]
            if len(pts) >= 2:
                paths.append(_line_path(pts[0], pts[1]))
        elif gt == "CIRCLE":
            c = edge.Center(); r = edge.radius()
            paths.append(_circle_path(c.x, c.y, r))
        elif gt == "ARC":
            c = edge.Center(); r = edge.radius()
            a1 = edge.startAngle(); a2 = edge.endAngle()
            paths.append(_arc_path(c.x, c.y, r, a1, a2))
        elif gt == "ELLIPSE":
            c = edge.Center(); rx = edge.majorRadius(); ry = edge.minorRadius()
            paths.append(_ellipse_path(c.x, c.y, rx, ry))
        elif gt in ("BSPLINE", "SPLINE", "BEZIER"):
            pts = [(v.X, v.Y) for v in edge.Vertices()]
            paths.append(_polyline_path(pts))
        else:
            pts = [(v.X, v.Y) for v in edge.Vertices()]
            if len(pts) >= 2:
                paths.append(_polyline_path(pts))

    w = max(1.0, bb.xlen) + 2 * margin_px
    h = max(1.0, bb.ylen) + 2 * margin_px
    view = f"{bb.xmin - margin_px} {-(bb.ymax + margin_px)} {w} {h}"

    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{view}" width="600" height="{600 * h / w:.0f}" '
        f'stroke="{stroke}" fill="{fill}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n'
    )
    body = "\n".join(f'  <path d="{p}"/>' for p in paths)
    foot = "\n</svg>\n"
    svg_path.write_text(head + body + foot + "\n")
    logger.info(f"[svg_render] wrote {svg_path} ({len(paths)} edges)")
    return svg_path


# --- primitive path builders --------------------------------------------------

def _line_path(p1, p2) -> str:
    return f"M {p1[0]:.3f} {-p1[1]:.3f} L {p2[0]:.3f} {-p2[1]:.3f}"


def _polyline_path(pts: Iterable[tuple[float, float]]) -> str:
    pts = list(pts)
    if len(pts) < 2:
        return ""
    cmds = [f"M {pts[0][0]:.3f} {-pts[0][1]:.3f}"]
    for p in pts[1:]:
        cmds.append(f"L {p[0]:.3f} {-p[1]:.3f}")
    return " ".join(cmds)


def _circle_path(cx: float, cy: float, r: float) -> str:
    # SVG y is flipped, so we negate y; arc flags are tricky but a
    # full circle is two semicircle arcs.
    return (
        f"M {cx - r:.3f} {-cy:.3f} "
        f"A {r:.3f} {r:.3f} 0 1 0 {cx + r:.3f} {-cy:.3f} "
        f"A {r:.3f} {r:.3f} 0 1 0 {cx - r:.3f} {-cy:.3f} Z"
    )


def _arc_path(cx: float, cy: float, r: float, a1: float, a2: float) -> str:
    # OCC uses radians; SVG uses degrees. Sweep is from a1 to a2.
    d1 = math.degrees(a1); d2 = math.degrees(a2)
    p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
    p2 = (cx + r * math.cos(a2), cy + r * math.sin(a2))
    # normalise sweep to <= 2pi
    sweep = (d2 - d1) % 360
    large_arc = 1 if sweep > 180 else 0
    sweep_flag = 1 if d2 > d1 else 0
    return (
        f"M {p1[0]:.3f} {-p1[1]:.3f} "
        f"A {r:.3f} {r:.3f} 0 {large_arc} {sweep_flag} {p2[0]:.3f} {-p2[1]:.3f}"
    )


def _ellipse_path(cx: float, cy: float, rx: float, ry: float) -> str:
    return _circle_path(cx, cy, max(rx, ry))      # crude — show as circle
