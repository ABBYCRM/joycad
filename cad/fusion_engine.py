"""FusionEngine — runs a Fusion 360 add-in / script via the local Fusion API.

Fusion 360 exposes a Python API via its built-in interpreter. To run from outside
Fusion we ship the script to a watched folder that the ``JoyCAD`` add-in polls,
or use ``adsk.core.Application.get()`` from a launched instance.

For headless server use, the recommended path is Fusion's Manufacturing
Extension API which is invoked by the user opening Fusion once and triggering
the script via the add-in UI. We package both modes.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from loguru import logger

from .base import CADEngine, CADGeometry, register_engine


@register_engine
class FusionEngine(CADEngine):
    name = "fusion"

    def __init__(self, script_dir: str | None = None):
        # Fusion watches this folder; user runs the add-in which picks up files.
        self.script_dir = Path(script_dir or os.getenv(
            "FUSION360_SCRIPT_DIR",
            str(Path.home() / "Documents/Autodesk/Scripts/JoyCAD"),
        ))
        self.script_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, script_path: Path, out_dir: Path) -> CADGeometry:
        out_dir.mkdir(parents=True, exist_ok=True)
        target = self.script_dir / script_path.name
        shutil.copy(script_path, target)
        logger.info(
            f"[Fusion] script staged at {target}. "
            "Open Fusion 360 → Scripts → JoyCAD → Run to execute."
        )
        # Optional: try to invoke Fusion headlessly (requires a CLI launcher).
        launcher = os.getenv("FUSION360_LAUNCHER")
        if launcher:
            subprocess.Popen([launcher, "--headless", "--script", str(target)])
        return CADGeometry(
            step_path=out_dir / "part.step",   # produced asynchronously
            units="mm",
            metadata={"engine": "fusion", "staged_script": str(target),
                      "note": "Fusion must be running with the JoyCAD add-in"},
        )
