"""BlenderCAM — operational stub.

The real BlenderCAM ships as a Blender add-in. From outside Blender we
stage the operation config into a watched folder; Blender's
``bpy.ops``-driven add-in picks it up.

Reference: https://github.com/SpectralVectors/blendercam
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from loguru import logger

from .base import (CAMBackend, CAMJob, RawToolpaths, register_cam)


@register_cam
class BlenderCAMStub(CAMBackend):
    name = "blendercam"

    def __init__(self, watch_dir: str | None = None):
        self.watch = Path(watch_dir or os.getenv(
            "BLENDERCAM_WATCH",
            str(Path.home() / "Documents/JoyCAD/blendercam_jobs"),
        ))
        self.watch.mkdir(parents=True, exist_ok=True)

    def generate(self, step_path: Path, job: CAMJob, out_dir: Path) -> RawToolpaths:
        payload = {
            "step": str(step_path),
            "machine": job.machine,
            "stock": job.stock_mm,
            "ops": [vars(o) for o in job.operations],
            "safe_z": job.safe_z_mm,
            "spindle_rpm": job.spindle_rpm,
            "coolant": job.coolant,
        }
        out = self.watch / f"{step_path.stem}.json"
        out.write_text(json.dumps(payload, indent=2))
        logger.info(f"[BlenderCAM] job staged at {out}; open Blender, run the "
                    "JoyCAD add-in to execute.")
        return RawToolpaths(
            moves=[],
            estimated_time_min=0.0,
            metadata={"engine": "blendercam", "staged_job": str(out),
                      "note": "Blender must be running with JoyCAM add-in"},
        )
