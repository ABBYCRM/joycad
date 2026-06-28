"""JoyCAD orchestrator — the pipeline runner.

    Pipeline
        intent  →  StructuredBrief
                →  CADScript         (LLM via RAG)
                →  CADGeometry       (CAD engine)
                →  geometry formats  (STEP / STL / DXF / SVG)
                →  toolpaths         (CAM backend)
                →  G-code            (post-processor)
                →  validation        (FEA, collision, DFM, tolerance)
                →  outputs           (BOM, mfg notes, drawings)

    Two entry points:
        Pipeline.run()              programmatic
        joycad run / joycad serve   CLI / REST
"""
from .pipeline import Pipeline, PipelineConfig, PipelineResult
from .cli import app
from .api import create_app

__all__ = ["Pipeline", "PipelineConfig", "PipelineResult", "app", "create_app"]
