"""JoyCAD orchestrator — the pipeline runner + UI + API.

    Pipeline
        intent  →  StructuredBrief
                →  CADScript         (LLM via RAG)
                →  CADGeometry       (CAD engine)
                →  geometry formats  (STEP / STL / DXF / SVG)
                →  toolpaths         (CAM backend)
                →  G-code            (post-processor)
                →  validation        (FEA, collision, DFM, tolerance)
                →  outputs           (BOM, mfg notes, drawings)

    Entry points
        Pipeline.run()              programmatic
        joycad run / joycad serve   CLI
        joycad demo                  Streamlit web UI
        POST /v1/pipeline            REST API
"""
from .pipeline import Pipeline, PipelineConfig, PipelineResult
from .settings import Settings, get_preset, list_presets, PRESETS
from .cli import app
from .api import create_app

__all__ = [
    "Pipeline", "PipelineConfig", "PipelineResult",
    "Settings", "get_preset", "list_presets", "PRESETS",
    "app", "create_app",
]
