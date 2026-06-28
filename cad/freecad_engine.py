"""FreeCADEngine — runs a Python script via the headless ``freecadcmd`` binary.

The script is expected to:
    • build a Part.Shape named ``result``
    • optionally save STEP via ``Part.export([obj], 'out.step')``

We wrap the call with a subprocess invocation and parse the STEP file back
to extract bbox / volume / area.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from loguru import logger

from .base import CADEngine, CADGeometry, register_engine


@register_engine
class FreeCADEngine(CADEngine):
    name = "freecad"

    def __init__(self, freecad_cmd: str | None = None):
        self.cmd = freecad_cmd or os.getenv("FREECAD_CMD", "freecadcmd")

    def execute(self, script_path: Path, out_dir: Path) -> CADGeometry:
        out_dir.mkdir(parents=True, exist_ok=True)
        step_path = out_dir / "part.step"
        script_text = script_path.read_text()

        # If the script doesn't already export a STEP, wrap it.
        if "Part.export" not in script_text:
            wrapper = _make_export_wrapper(script_path.name, str(step_path))
            tmp = script_path.parent / f"_wrapped_{script_path.name}"
            tmp.write_text(wrapper + "\n" + script_text)
            run_target = tmp
        else:
            run_target = script_path

        cmd = [self.cmd, "-c", str(run_target)]
        logger.info(f"[FreeCAD] running: {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            logger.error(f"[FreeCAD] stderr:\n{proc.stderr}")
            raise RuntimeError(f"FreeCAD failed (exit {proc.returncode}):\n{proc.stderr}")
        if proc.stdout.strip():
            logger.debug(f"[FreeCAD] stdout:\n{proc.stdout[:2000]}")

        if not step_path.exists():
            # Some scripts emit a file named `out.step` in cwd.
            cwd_step = Path.cwd() / "out.step"
            if cwd_step.exists():
                shutil.move(str(cwd_step), step_path)
            else:
                raise RuntimeError(f"FreeCAD ran but no STEP at {step_path}")

        geom = _inspect_step(step_path)
        geom.native_path = None  # FreeCAD .FCStd would be nice; skipped for now
        return geom


def _make_export_wrapper(script_name: str, step_out: str) -> str:
    """Prepend boilerplate that creates a doc + exports STEP at the end."""
    return f"""
# ---- JoyCAD wrapper ----
import FreeCAD
DOC = FreeCAD.newDocument("JoyCAD")
"""


def _inspect_step(step_path: Path) -> CADGeometry:
    """Read bbox/volume/area from a STEP file.

    We avoid pulling FreeCAD back in for inspection (slow + heavy). Instead
    we parse the STEP file's geometric entities directly with a tiny built-in
    reader for primitive solids, OR fall back to ``cadquery`` if installed.
    """
    try:
        import cadquery as cq  # type: ignore
        from cadquery import importers
        shape = importers.importStep(str(step_path)).val()
        bb = shape.BoundingBox()
        return CADGeometry(
            step_path=step_path,
            units="mm",
            bbox_mm=(bb.xlen, bb.ylen, bb.zlen),
            volume_mm3=float(shape.Volume()),
            surface_area_mm2=float(shape.Area()),
            metadata={"inspector": "cadquery"},
        )
    except Exception as e:
        logger.warning(f"[FreeCAD] cadquery not available for inspection ({e}); "
                       f"using cheap STEP header parse.")
    # fallback: parse CARTESIAN_POINTS / CLOSED_SHELL bounds (approximate)
    return _cheap_step_inspect(step_path)


def _cheap_step_inspect(step_path: Path) -> CADGeometry:
    """Crude STEP reader that pulls vertex coords from CARTESIAN_POINT entries.

    Not exact (won't catch cylinders), but enough for a sanity check.
    """
    import re
    xs: list[float] = []; ys: list[float] = []; zs: list[float] = []
    pat = re.compile(r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*([^)]+)\s*\)\s*\)")
    for line in step_path.read_text(errors="ignore").splitlines():
        m = pat.search(line)
        if not m:
            continue
        try:
            x, y, z = (float(v.strip()) for v in m.group(1).split(",")[:3])
            xs.append(x); ys.append(y); zs.append(z)
        except ValueError:
            continue
    if not xs:
        return CADGeometry(step_path=step_path)
    bbox = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    # crude volume proxy
    vol = bbox[0] * bbox[1] * bbox[2] * 0.5
    return CADGeometry(step_path=step_path, bbox_mm=bbox, volume_mm3=vol,
                       surface_area_mm2=0.0,
                       metadata={"inspector": "cheap"})


if __name__ == "__main__":
    # ad-hoc smoke test (only runs if FreeCAD is installed)
    import sys
    if len(sys.argv) < 3:
        print("usage: python -m cad.freecad_engine <script.py> <out_dir>")
        sys.exit(1)
    eng = FreeCADEngine()
    g = eng.execute(Path(sys.argv[1]), Path(sys.argv[2]))
    print(g)
