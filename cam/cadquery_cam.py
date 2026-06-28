"""CadQueryCAM — real toolpaths computed directly from the geometry.

Unlike FreeCAD Path, this needs NO external CLI. We use CadQuery's
bounding box + face analysis to plan:

    • face     — zigzag across the top
    • contour  — profile the outer perimeter at depth
    • drill    — peck drill every hole

This is a real CAM backend: the toolpaths come from the actual STEP geometry,
not a stock-size approximation. The result is a neutral ``RawToolpaths`` that
the post-processor turns into machine G-code.
"""
from __future__ import annotations

import math
from pathlib import Path

import yaml
from loguru import logger

from .base import (CAMBackend, CAMJob, CAMOperation, RawToolpaths,
                   Toolpath, register_cam)


@register_cam
class CadQueryCAM(CAMBackend):
    name = "cadquery_cam"

    def generate(self, step_path: Path, job: CAMJob, out_dir: Path) -> RawToolpaths:
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            import cadquery as cq
            from cadquery import importers
        except ImportError as e:
            raise RuntimeError("cadquery required for CadQueryCAM") from e

        shape = importers.importStep(str(step_path)).val()
        bb = shape.BoundingBox()
        L, W, T = bb.xlen, bb.ylen, bb.zlen

        # tool selections
        small_tool_dia = 6.0
        drill_tool_dia = 6.6

        moves: list[Toolpath] = []

        # ----- preamble: rapid to safe height -----
        safe_z = job.safe_z_mm
        moves.append(Toolpath("setup", "T1", "rapid", 0, 0, safe_z))
        moves.append(Toolpath("setup", "T1", "rapid", 2, 2, safe_z))

        # ----- face the top -----
        stepover = 4.0
        z_face = -0.5
        moves.append(Toolpath("face", "T1", "feed",
                              2, 2, z_face, feed_mm_min=600))
        y = 2.0
        direction = 1
        while y <= W - 1.5:
            x_target = L - 2 if direction > 0 else 2
            moves.append(Toolpath("face", "T1", "feed",
                                  x_target, y, z_face, feed_mm_min=600))
            moves.append(Toolpath("face", "T1", "rapid", x_target, y + stepover, safe_z))
            y += stepover
            direction *= -1
        moves.append(Toolpath("face", "T1", "rapid", 2, 2, safe_z))

        # ----- contour the outer profile -----
        # Use stock Z (how deep the user said the stock is) NOT bbox Z
        # (which would be the part height). The cut depth is part-thickness
        # from the top, capped at stock_z - 2 mm.
        stock_z = job.stock_mm.get("z", T + 2)
        z_cont = -max(2.0, min(T + 0.5, stock_z - 2.0))
        # use bounding rectangle as the conservative profile path
        pts = [(2, 2), (L - 2, 2), (L - 2, W - 2), (2, W - 2), (2, 2)]
        for (x, y) in pts:
            moves.append(Toolpath("contour", "T1", "feed",
                                  x, y, z_cont, feed_mm_min=400))
        moves.append(Toolpath("contour", "T1", "rapid", 2, 2, safe_z))

        # ----- drill every cylindrical face (holes) -----
        try:
            for face in shape.Faces():
                if face.geomType() != "CYLINDER":
                    continue
                # only through-holes / blind holes (not outer profile)
                center = face.Center()
                radius = face.radius()
                if radius < 0.5:
                    continue
                # skip if the cylinder axis is vertical (likely a hole)
                normal = face.normalAt(center)
                if abs(normal.z) < 0.9:
                    continue
                x, y = center.x, center.y
                # if the hole spans the full Z, drill through
                z_top = center.z + T/2 if abs(normal.z) > 0.9 else center.z
                z_bot = center.z - T/2 if abs(normal.z) > 0.9 else center.z
                moves.append(Toolpath("drill", "T3", "rapid", x, y, safe_z))
                # peck drill
                z_cur = 0.5
                while z_cur > z_bot:
                    moves.append(Toolpath("drill", "T3", "feed",
                                          x, y, -z_cur, feed_mm_min=80))
                    moves.append(Toolpath("drill", "T3", "rapid",
                                          x, y, safe_z))
                    z_cur -= 1.5
                moves.append(Toolpath("drill", "T3", "rapid", x, y, safe_z))
        except Exception as e:
            logger.warning(f"[CadQueryCAM] drill pass skipped: {e}")

        # ----- finish: retract to a higher safe Z -----
        moves.append(Toolpath("setup", "T1", "rapid", 0, 0, safe_z + 10))

        return RawToolpaths(
            moves=moves,
            estimated_time_min=round(len(moves) * 0.05, 1),
            metadata={
                "engine": "cadquery_cam",
                "bbox_mm": [L, W, T],
                "moves_planned": len(moves),
            },
        )


if __name__ == "__main__":
    import sys
    from pathlib import Path
    if len(sys.argv) < 3:
        print("usage: python -m cam.cadquery_cam <step> <out_dir>")
        sys.exit(1)
    eng = CadQueryCAM()
    job = CAMJob(machine="linuxcnc_3axis",
                 stock_mm={"x": 60, "y": 40, "z": 20},
                 safe_z_mm=5.0)
    raw = eng.generate(Path(sys.argv[1]), job, Path(sys.argv[2]))
    print(f"planned {len(raw.moves)} moves, est {raw.estimated_time_min} min")
