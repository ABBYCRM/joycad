"""FreeCADPathCAM — runs FreeCAD's Path Workbench headless to emit toolpaths.

This uses FreeCAD's own Python interpreter (`freecadcmd -c`) — same trick as
the FreeCAD engine — to keep dependency surface small.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from loguru import logger

from .base import (CAMBackend, CAMJob, RawToolpaths, Toolpath,
                   register_cam)


@register_cam
class FreeCADPathCAM(CAMBackend):
    name = "freecad_path"

    def __init__(self, freecad_cmd: str | None = None):
        self.cmd = freecad_cmd or os.getenv("FREECAD_CMD", "freecadcmd")

    def generate(self, step_path: Path, job: CAMJob, out_dir: Path) -> RawToolpaths:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Emit a FreeCAD Python script that does:
        #   1. import step
        #   2. create a Path job
        #   3. add each operation from `job.operations`
        #   4. dump moves as JSON
        script = _render_freecad_path_script(step_path, job, out_dir)
        script_path = out_dir / "_freecad_path_runner.py"
        script_path.write_text(script)
        logger.info(f"[FreeCADPathCAM] invoking {self.cmd} …")
        proc = subprocess.run([self.cmd, "-c", str(script_path)],
                              capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            logger.error(proc.stderr)
            raise RuntimeError(f"FreeCAD Path failed: {proc.stderr[-1000:]}")
        return _load_moves_json(out_dir / "toolpaths.json")


def _render_freecad_path_script(step_path: Path, job: CAMJob, out_dir: Path) -> str:
    """Generate a FreeCAD-Python script that emits the toolpath JSON."""
    import json as _json
    ops_json = _json.dumps([_op_to_freecad_dict(o) for o in job.operations])
    return f"""
import json, os, sys
import FreeCAD, FreeCADGui, Part, Path

DOC = FreeCAD.newDocument("JoyCAD_CAM")
Part.insert("{str(step_path)}", DOC.Name)
body = DOC.ActiveObject

# build a Path Job
job = Path.Job.Create([body], DOC, buildShapeList=False)
job.PostProcessor = "linuxcnc"
job.PostProcessorArgs = "--no-show-editor"

# stock
sx, sy, sz = {job.stock_mm.get('x', 100)}, {job.stock_mm.get('y', 100)}, {job.stock_mm.get('z', 10)}
job.Stock.setAllExpression(FreeCAD.Units.Quantity(sz, FreeCAD.Units.Length))

# ops
ops = {ops_json}
created_ops = []
for op in ops:
    kind = op['kind']
    if kind == 'face':
        o = Path.OpFace(Base.Object(body), tool_no=1, stepover=2.0, depth=1.0)
        o.addOp(obj=body)
    elif kind == 'pocket':
        o = Path.OpPocket(Base.Object(body))
        o.StepDown = op['params'].get('stepdown_mm', 1.0)
        o.Stepover = op['params'].get('stepover_mm', 1.0)
        o.FinalDepth = op['params'].get('depth_mm', 3.0)
        o.Tool = op.get('tool')
        o.addOp(body)
    elif kind == 'drill':
        o = Path.OpDrilling(Base.Object(body))
        o.Tool = op.get('tool')
        o.FinalDepth = op['params'].get('depth_mm', 5.0)
        o.PeckDepth = op['params'].get('peck_mm', 2.0)
        o.addOp(body)
    elif kind == 'contour':
        o = Path.OpContour(Base.Object(body))
        o.FinalDepth = op['params'].get('depth_mm', 3.0)
        o.addOp(body)
    else:
        print(f"[warn] unsupported op kind {{kind}}, skipping")
        continue
    created_ops.append(o)
    job.Operations.append(o)

Path.Preferences.suppressAllVisualisation(True)
for op in job.Operations:
    op.Path = Path.fromShape(body.Shape)

# emit neutral moves
moves = []
for op in job.Operations:
    cmds = op.Path.toGCode()
    for line in cmds.splitlines():
        line = line.strip()
        if not line or line.startswith('('):
            continue
        # very rough parser — production code uses full G-code lexer
        moves.append({{'raw': line}})

out_path = r"{out_dir / 'toolpaths.json'}"
with open(out_path, 'w') as f:
    json.dump({{'estimated_time_min': 0.0, 'moves': moves, 'metadata': {{'engine': 'freecad_path'}}}}, f)
print(f"[freecad_path] wrote {{out_path}}")
"""


def _op_to_freecad_dict(op) -> dict:
    return {"kind": op.kind, "tool": op.tool, "params": op.params}


def _load_moves_json(path: Path) -> RawToolpaths:
    import json
    data = json.loads(path.read_text())
    moves: list[Toolpath] = []
    for raw in data.get("moves", []):
        if "raw" in raw:
            moves.append(_parse_gcode_line(raw["raw"]))
        else:
            moves.append(Toolpath(**raw))
    return RawToolpaths(moves=moves,
                        estimated_time_min=data.get("estimated_time_min", 0.0),
                        metadata=data.get("metadata", {}))


def _parse_gcode_line(line: str) -> Toolpath:
    """Best-effort G-code → Toolpath. Good enough for verification, not for post."""
    import re
    out = Toolpath(op_kind="contour", tool="", move="feed",
                   x=0.0, y=0.0, z=0.0)
    m = re.match(r"G0?0?(\d)", line)
    if m:
        g = int(m.group(1))
        if g == 0: out.move = "rapid"
        elif g in (1, 2, 3):
            out.move = {"1": "feed", "2": "arc_cw", "3": "arc_ccw"}[str(g)]
    for tok in re.findall(r"([XYZFIJK])(-?\d+\.?\d*)", line):
        axis, val = tok
        v = float(val)
        if axis in "XYZ": setattr(out, axis.lower(), v)
        elif axis == "F": out.feed_mm_min = v
        elif axis in "IJK": setattr(out, axis.lower(), v)
    return out


# `Base` is imported inside the generated FreeCAD script as a late import;
# referenced for the linter only.
import_path_freecad_base_dummy = None  # noqa
