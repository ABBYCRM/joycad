"""CadQueryEngine — runs a CadQuery Python script in-process.

CadQuery is OCCT-based, pure Python, no GUI. Fast, reliable, and great for
parametric parts. This engine just exec()s the script and exports STEP.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

from loguru import logger

from .base import CADEngine, CADGeometry, register_engine


@register_engine
class CadQueryEngine(CADEngine):
    name = "cadquery"

    def execute(self, script_path: Path, out_dir: Path) -> CADGeometry:
        out_dir.mkdir(parents=True, exist_ok=True)
        step_path = out_dir / "part.step"

        try:
            import cadquery as cq  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "cadquery not installed — `mamba install -c conda-forge cadquery`"
            ) from e

        # Exec the script in a clean module namespace; expect a `result` CQ obj.
        ns: dict = {"__name__": "__joycad_script__"}
        try:
            with script_path.open() as f:
                code = f.read()
            exec(compile(code, str(script_path), "exec"), ns)
        except Exception as e:
            raise RuntimeError(f"CadQuery script failed: {e}") from e

        if "result" not in ns:
            raise RuntimeError("CadQuery script did not produce a `result` variable.")

        cq_obj = ns["result"]
        from cadquery import exporters
        exporters.export(cq_obj, str(step_path))
        logger.info(f"[CadQuery] wrote {step_path}")

        bb = cq_obj.val().BoundingBox()
        return CADGeometry(
            step_path=step_path,
            units="mm",
            bbox_mm=(bb.xlen, bb.ylen, bb.zlen),
            volume_mm3=float(cq_obj.val().Volume()),
            surface_area_mm2=float(cq_obj.val().Area()),
            metadata={"inspector": "cadquery", "engine": "cadquery"},
        )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: python -m cad.cadquery_engine <script.py> <out_dir>")
        sys.exit(1)
    eng = CadQueryEngine()
    g = eng.execute(Path(sys.argv[1]), Path(sys.argv[2]))
    print(g.to_dict())
