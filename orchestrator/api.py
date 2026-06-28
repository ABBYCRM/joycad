"""JoyCAD REST API.

Endpoints
---------
  GET  /                          → service banner + version
  GET  /health                    → liveness probe
  GET  /v1/info                   → version, defaults, runtime status
  GET  /v1/settings               → current effective settings
  POST /v1/settings/validate      → dry-run validate a Settings dict
  GET  /v1/capabilities           → what's wired RIGHT NOW (engines, validators)
  GET  /v1/engines                → legacy: CAD + CAM engines
  GET  /v1/machines               → list machine YAMLs (name + description)
  GET  /v1/materials              → list material YAMLs
  GET  /v1/processes              → list valid processes
  GET  /v1/presets                → list named setting presets
  GET  /v1/presets/{name}         → load a preset as full Settings
  GET  /v1/examples               → canned example intents
  POST /v1/run                    → legacy: minimal run request
  POST /v1/pipeline               → full pipeline from full Settings

Backward-compat: /v1/engines and /v1/run keep their old shapes.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .pipeline import Pipeline, PipelineConfig
from .settings import (PRESETS, Settings, get_preset, list_presets)
from .static_ui import router as static_ui_router


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    """Legacy minimal run request — backward compatible."""
    intent: str
    out_dir: str = "./out"
    machine: str = "linuxcnc_3axis"
    material: str = "6061-T6"
    cad_engine: str = "cadquery"
    cam_backend: str = "cadquery_cam"
    post_processor: str = "linuxcnc"
    process: str = "cnc_mill"
    skip_validation: bool = False
    context: str = ""


class PipelineRequest(BaseModel):
    """Full settings body for /v1/pipeline — every knob is exposed.

    All fields default to ``None`` so we can tell whether the caller
    actually sent them. Fields the caller didn't set fall back to the
    preset (if any) or to ``Settings.default()``.
    """
    # presence tracker — fields the user explicitly sent
    model_config = {"extra": "forbid"}

    intent: Optional[str] = None
    machine: Optional[str] = None
    material: Optional[str] = None
    process: Optional[str] = None
    cad_engine: Optional[str] = None
    cam_backend: Optional[str] = None
    post_processor: Optional[str] = None
    llm_provider: Optional[str] = None

    safe_z_mm: Optional[float] = None
    spindle_rpm: Optional[int] = None
    coolant: Optional[str] = None
    stock_padding_mm: Optional[float] = None
    work_offset: Optional[str] = None

    skip_validation: Optional[bool] = None
    validators_enabled: Optional[list[str]] = None
    collision_cutter_dia_mm: Optional[float] = None
    collision_cutter_len_mm: Optional[float] = None
    fea_force_n: Optional[float] = None

    export_formats: Optional[list[str]] = None
    write_pipeline_result_json: Optional[bool] = None
    write_3d_print_gcode: Optional[bool] = None

    log_level: Optional[str] = None
    cache_results: Optional[bool] = None
    graceful_degradation: Optional[bool] = None

    extra_context: Optional[str] = None
    preset: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _capability_status() -> dict:
    """What's actually wired in this runtime (some deps are optional)."""
    import importlib.util as iu
    def has(name: str) -> bool:
        try:
            return iu.find_spec(name) is not None
        except Exception:
            return False

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executables_on_path": {
            "freecadcmd": shutil.which("freecadcmd"),
            "ccx":        shutil.which("ccx"),
            "prusa-slicer": shutil.which("prusa-slicer"),
            "ollama":     shutil.which("ollama"),
        },
        "python_modules": {
            "cadquery":       has("cadquery"),
            "streamlit":      has("streamlit"),
            "fastapi":        has("fastapi"),
            "ezdxf":          has("ezdxf"),
            "sentence_transformers": has("sentence_transformers"),
            "faiss":          has("faiss"),
            "fcl":            has("fcl"),
            "openai":         has("openai"),
            "anthropic":      has("anthropic"),
            "trimesh":        has("trimesh"),
        },
        "llm_providers_available": [
            p for p, env_key, mod in [
                ("mock",      None,                       None),
                ("openai",    "OPENAI_API_KEY",           "openai"),
                ("anthropic", "ANTHROPIC_API_KEY",        "anthropic"),
                ("ollama",    "OLLAMA_BASE_URL",          None),
                ("openrouter","OPENROUTER_API_KEY",       "openai"),  # uses openai client
                ("vllm",      "VLLM_BASE_URL",            "openai"),
            ]
            if env_key is None
               or (mod is not None and has(mod))
               or os.getenv(env_key)
        ],
    }


def _info_payload() -> dict:
    from cam import list_cams
    from cad import list_engines
    from validation import list_validators

    return {
        "service": "JoyCAD",
        "version": "0.1.0",
        "tagline": "AI-driven CAD/CAM bundle",
        "docs": "https://github.com/ABBYCRM/joycad",
        "cad_engines":        list_engines(),
        "cam_backends":       list_cams(),
        "validators":         list_validators(),
        "processes":          ["cnc_mill", "cnc_lathe", "3d_print_sla",
                               "3d_print_fdm", "3d_print_sls", "laser_cut",
                               "plasma_cut", "sheet_metal", "injection_mold"],
        "machine_configs":    sorted(p.stem for p in
                                     Path(__file__).resolve().parents[1].glob(
                                         "config/machines/*.yaml")),
        "material_configs":   sorted(p.stem for p in
                                     Path(__file__).resolve().parents[1].glob(
                                         "config/materials/*.yaml")),
        "presets":            list_presets(),
    }


def _settings_payload(s: Settings) -> dict:
    return s.to_dict()


def _examples_payload() -> list[dict]:
    """Canned intents + the preset that fits each."""
    return [
        {"intent": "a 50 mm L-bracket, 6 mm thick, four M6 holes, 6061-T6",
         "preset": "mvp-mock",
         "expected_shape": "l_bracket",
         "expected_outputs": ["step", "stl", "dxf", "svg", "gcode", "bom", "notes"]},
        {"intent": "an 80 x 40 x 6 mm flat plate with four M6 corner holes, 1018 steel",
         "preset": "mvp-mock",
         "expected_shape": "plate"},
        {"intent": "a 100 x 60 x 20 mm enclosure with 3 mm walls, ABS, 3D print",
         "preset": "fdm-print",
         "expected_shape": "enclosure"},
        {"intent": "a 80 mm diameter flange, 10 mm thick, central bore, six M6 holes, 6061-T6",
         "preset": "mvp-mock",
         "expected_shape": "flange"},
        {"intent": "a 10 mm diameter shaft, 80 mm long, 5 mm keyway, 1018 steel",
         "preset": "mvp-mock",
         "expected_shape": "shaft"},
        {"intent": "a 40 mm diameter spur gear, 6 mm thick, 5 mm bore, 6061-T6",
         "preset": "mvp-mock",
         "expected_shape": "gear"},
    ]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(
        title="JoyCAD",
        version="0.1.0",
        description=(
            "AI-driven CAD/CAM bundle. "
            "POST a design intent, get back a STEP / STL / DXF / SVG / G-code / BOM. "
            "Works offline with the `mock` LLM (zero API key required)."
        ),
        contact={"name": "JoyCAD", "url": "https://github.com/ABBYCRM/joycad"},
        license_info={"name": "MIT"},
    )

    # ------------------------------------------------------------------
    # Static HTML UI (served at / and /ui)
    # ------------------------------------------------------------------
    app.include_router(static_ui_router)

    # ------------------------------------------------------------------
    # Top-level
    # ------------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/openapi.json")
    def openapi_alias():
        """Convenience: same as the auto-generated OpenAPI doc."""
        return app.openapi()

    # ------------------------------------------------------------------
    # v1 — info & introspection
    # ------------------------------------------------------------------
    @app.get("/v1/info")
    def info():
        return _info_payload()

    @app.get("/v1/capabilities")
    def capabilities():
        return _capability_status()

    @app.get("/v1/settings")
    def get_settings():
        return _settings_payload(Settings.default())

    @app.post("/v1/settings/validate")
    def validate_settings(req: dict):
        """Echo back a Settings built from the request body + report any issues."""
        try:
            s = Settings.from_request(req)
            return {"valid": True, "settings": s.to_dict(),
                    "diff_from_defaults": _diff(Settings.default().to_dict(),
                                                s.to_dict())}
        except Exception as e:
            return {"valid": False, "error": str(e)}, 422

    # ------------------------------------------------------------------
    # v1 — catalogs
    # ------------------------------------------------------------------
    @app.get("/v1/engines")
    def engines():
        return _info_payload()  # legacy alias

    @app.get("/v1/machines")
    def machines():
        from cam.tool_db import default_tool_db
        return {"machines": [
            {"id": "linuxcnc_3axis", "description": "Generic benchtop 3-axis mill"},
            {"id": "grbl_3018",      "description": "Hobby 3018-class CNC, no ATC"},
            {"id": "marlin_fdm",     "description": "Marlin FDM 3D printer"},
        ], "default_tool_db": [t.__dict__ for t in default_tool_db().tools]}

    @app.get("/v1/materials")
    def materials():
        root = Path(__file__).resolve().parents[1] / "config" / "materials"
        out = []
        for p in sorted(root.glob("*.yaml")):
            try:
                d = yaml_safe(p)
                out.append({"id": p.stem, **{k: d[k] for k in d
                                              if k in ("name", "category",
                                                       "yield_strength_mpa",
                                                       "density_g_cm3")}})
            except Exception:
                out.append({"id": p.stem})
        return {"materials": out}

    @app.get("/v1/processes")
    def processes():
        return {"processes": [
            {"id": "cnc_mill",      "label": "CNC milling (3-axis)"},
            {"id": "cnc_lathe",     "label": "CNC lathe / turning"},
            {"id": "3d_print_fdm",  "label": "FDM 3D printing"},
            {"id": "3d_print_sla",  "label": "SLA 3D printing"},
            {"id": "3d_print_sls",  "label": "SLS 3D printing"},
            {"id": "laser_cut",     "label": "Laser cutting (sheet)"},
            {"id": "plasma_cut",    "label": "Plasma cutting (sheet)"},
            {"id": "sheet_metal",   "label": "Sheet metal bending"},
            {"id": "injection_mold","label": "Injection molding"},
        ]}

    # ------------------------------------------------------------------
    # v1 — presets
    # ------------------------------------------------------------------
    @app.get("/v1/presets")
    def presets():
        return {"presets": list_presets()}

    @app.get("/v1/presets/{name}")
    def preset_detail(name: str):
        s = get_preset(name)
        if s is None:
            raise HTTPException(404, f"unknown preset: {name!r}")
        return s.to_dict()

    # ------------------------------------------------------------------
    # v1 — examples
    # ------------------------------------------------------------------
    @app.get("/v1/examples")
    def examples():
        return {"examples": _examples_payload()}

    # ------------------------------------------------------------------
    # v1 — run (legacy)
    # ------------------------------------------------------------------
    @app.post("/v1/run")
    def run_legacy(req: RunRequest):
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

    # ------------------------------------------------------------------
    # v1 — full pipeline (with all settings)
    # ------------------------------------------------------------------
    @app.post("/v1/pipeline")
    def run_full(req: PipelineRequest):
        # Load preset if specified, else defaults
        if req.preset:
            s = get_preset(req.preset)
            if s is None:
                raise HTTPException(400, f"unknown preset: {req.preset!r}")
        else:
            s = Settings.default()
        # Overlay ONLY fields the caller actually sent (Pydantic v2).
        # This lets a preset's machine=marlin_fdm survive when the caller
        # only sent intent + preset, without sending machine explicitly.
        for field_name in req.model_fields_set:
            if field_name == "preset":
                continue
            v = getattr(req, field_name)
            if v is not None and hasattr(s, field_name):
                setattr(s, field_name, v)
        if not s.intent:
            raise HTTPException(400, "`intent` is required")

        cfg = PipelineConfig(
            intent=s.intent,
            out_dir=Path("./out"),
            machine=s.machine,
            material=s.material,
            cad_engine=s.cad_engine,
            cam_backend=s.cam_backend,
            post_processor=s.post_processor,
            process=s.process,
            skip_validation=s.skip_validation,
            llm_provider=s.llm_provider,
            safe_z_mm=s.safe_z_mm,
            spindle_rpm=s.spindle_rpm,
            context=s.extra_context,
        )
        try:
            result = Pipeline(cfg).run()
        except Exception as e:
            raise HTTPException(500, str(e))
        if not result.ok:
            raise HTTPException(500, result.error or "pipeline failed")
        return {
            "ok": True,
            "settings_used": s.to_dict(),
            "result": result.to_dict(),
        }

    return app


# ---------------------------------------------------------------------------
# YAML helper (avoids pulling in pyyaml at import time for this module)
# ---------------------------------------------------------------------------
def yaml_safe(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text())


def _diff(a: dict, b: dict) -> dict:
    """Return only keys whose values differ between a and b."""
    out = {}
    for k, v in b.items():
        if a.get(k) != v:
            out[k] = {"default": a.get(k), "yours": v}
    return out
