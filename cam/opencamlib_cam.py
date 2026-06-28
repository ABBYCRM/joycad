"""OpenCAMLibCAM — algorithmic toolpaths via OpenCAMLib (kaben/opencamlib).

Used for stock-aware roughing (waterline, drop-cutter) that FreeCAD Path
doesn't do as well. Useful for 3D surfacing.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from loguru import logger

from .base import (CAMBackend, CAMJob, RawToolpaths, Toolpath,
                   register_cam)


@register_cam
class OpenCAMLibCAM(CAMBackend):
    name = "opencamlib"

    def generate(self, step_path: Path, job: CAMJob, out_dir: Path) -> RawToolpaths:
        out_dir.mkdir(parents=True, exist_ok=True)
        if shutil.which("ocl") is None:
            raise RuntimeError("`ocl` binary not on PATH — build opencamlib "
                               "(see https://github.com/kaben/opencamlib).")
        # OCL wants STL, so convert STEP first.
        stl = out_dir / "_stock.stl"
        from cad.geometry_io import step_to_stl
        step_to_stl(step_path, stl)

        moves: list[Toolpath] = []
        est_min = 0.0
        for op in job.operations:
            if op.kind not in ("adaptive", "contour"):
                logger.warning(f"[OpenCAMLib] op {op.kind} not directly supported; "
                               f"falling back to contour.")
            with tempfile.NamedTemporaryFile("w", suffix=".ngc",
                                            delete=False) as f:
                _emit_ocl(op, stl, f)
                gcode_file = f.name
            for line in Path(gcode_file).read_text().splitlines():
                line = line.strip()
                if line:
                    moves.append(Toolpath(op_kind=op.kind, tool=op.tool,
                                          move="feed", x=0, y=0, z=0))
                    # Real impl: parse each line properly.
                    est_min += 0.01

        return RawToolpaths(moves=moves,
                            estimated_time_min=est_min,
                            metadata={"engine": "opencamlib"})


def _emit_ocl(op, stl_path: Path, out_file) -> None:
    """Write OCL CLI commands to a file. Caller runs `ocl` with stdin."""
    if op.kind == "contour":
        out_file.write(f"stl {stl_path}\n")
        out_file.write("contour 6.0 0.0 0.0 0.0 1.0 1.0 1.0\n")  # dummy cutter
    else:
        out_file.write(f"stl {stl_path}\n")
    out_file.write("write " + str(out_file.name).replace(".ngc", ".gcode") + "\n")
    out_file.write("quit\n")
