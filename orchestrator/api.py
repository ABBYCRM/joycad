"""JoyCAD REST API.

    POST /v1/run       run the full pipeline from a JSON body
    GET  /v1/engines   list available engines
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .pipeline import Pipeline, PipelineConfig


class RunRequest(BaseModel):
    intent: str
    out_dir: str = "./out"
    machine: str = "linuxcnc_3axis"
    material: str = "6061-T6"
    cad_engine: str = "cadquery"
    cam_backend: str = "freecad_path"
    post_processor: str = "linuxcnc"
    process: str = "cnc_mill"
    skip_validation: bool = False
    context: str = ""


def create_app() -> FastAPI:
    app = FastAPI(title="JoyCAD", version="0.1.0",
                  description="AI-driven CAD/CAM bundle")

    @app.get("/v1/engines")
    def engines():
        from cad import list_engines
        from cam import list_cams
        from validation import list_validators
        return {"cad": list_engines(),
                "cam": list_cams(),
                "validation": list_validators()}

    @app.post("/v1/run")
    def run(req: RunRequest) -> dict[str, Any]:
        cfg = PipelineConfig(
            intent=req.intent,
            out_dir=Path(req.out_dir),
            machine=req.machine,
            material=req.material,
            cad_engine=req.cad_engine,
            cam_backend=req.cam_backend,
            post_processor=req.post_processor,
            process=req.process,
            skip_validation=req.skip_validation,
            context=req.context,
        )
        try:
            result = Pipeline(cfg).run()
        except Exception as e:
            raise HTTPException(500, str(e))
        if not result.ok:
            raise HTTPException(500, result.error or "pipeline failed")
        return result.to_dict()

    return app
