"""JoyCAD settings — every knob in one place.

Used by:
    - CLI defaults
    - REST API request body (extended RunRequest)
    - Streamlit sidebar (advanced settings)
    - Default YAML config

Anything tunable lives here. ``Settings.default()`` reads env + YAML defaults.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml
from loguru import logger


# ---------------------------------------------------------------------------
# Enums (string-valued for YAML/JSON safety)
# ---------------------------------------------------------------------------
LLMProvider = Literal["mock", "openai", "anthropic", "ollama", "openrouter",
                    "vllm", "nvidia"]
CADEngine = Literal["cadquery", "freecad", "onshape", "fusion"]
CAMBackend = Literal["cadquery_cam", "freecad_path", "opencamlib", "blendercam"]
PostProcessor = Literal["linuxcnc", "grbl", "marlin"]
Process = Literal["cnc_mill", "cnc_lathe", "3d_print_sla", "3d_print_fdm",
                 "3d_print_sls", "laser_cut", "plasma_cut", "sheet_metal",
                 "injection_mold", "unknown"]
Coolant = Literal["flood", "mist", "off"]
ValidatorName = Literal["fea", "dfm", "collision", "tolerance"]
ExportFormat = Literal["step", "stl", "dxf", "svg", "gcode", "print_gcode", "bom", "notes"]
SlicerName = Literal["inline", "prusa-slicer", "orca-slicer", "cura",
                     "bambu-studio", "simplify3d"]
Adhesion = Literal["none", "brim", "raft"]


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    """Every JoyCAD knob in one object.

    Loaded from (in order of precedence):
        1. explicit constructor args
        2. function arguments to ``Pipeline.run()`` / ``PipelineConfig(...)``
        3. ``config/default_settings.yaml``
        4. env vars (JOYCAD_*)
        5. hard-coded defaults below
    """
    # --- core run ---
    intent: str = ""
    machine: str = "linuxcnc_3axis"
    material: str = "6061-T6"
    process: Process = "cnc_mill"
    cad_engine: CADEngine = "cadquery"
    cam_backend: CAMBackend = "cadquery_cam"
    post_processor: PostProcessor = "linuxcnc"
    llm_provider: LLMProvider = "mock"

    # --- toolpath knobs ---
    safe_z_mm: float = 5.0
    spindle_rpm: int = 12000
    coolant: Coolant = "flood"
    stock_padding_mm: float = 3.0          # extra stock around bbox
    work_offset: str = "G54"
    tool_overrides: dict = field(default_factory=dict)   # {"T1": {"rpm": 10000}}

    # --- validation toggles ---
    skip_validation: bool = False
    validators_enabled: list[ValidatorName] = field(
        default_factory=lambda: ["fea", "dfm", "tolerance"])
    collision_cutter_dia_mm: float = 6.0
    collision_cutter_len_mm: float = 25.0
    fea_force_n: float = 100.0

    # --- output toggles ---
    export_formats: list[ExportFormat] = field(
        default_factory=lambda: ["step", "stl", "dxf", "svg",
                                 "gcode", "bom", "notes"])
    write_pipeline_result_json: bool = True
    write_3d_print_gcode: bool = False

    # --- slicer (for 3d_print_fdm / sla / sls) ---
    slicer: SlicerName = "inline"
    slicer_settings: dict = field(default_factory=lambda: {
        "layer_height_mm": 0.2,
        "first_layer_height_mm": 0.3,
        "infill_percent": 20,
        "perimeters": 3,
        "top_layers": 4,
        "bottom_layers": 3,
        "print_speed_mm_s": 60,
        "travel_speed_mm_s": 150,
        "nozzle_temp_c": 220,
        "bed_temp_c": 60,
        "supports": False,
        "adhesion": "brim",
        "retraction_mm": 0.8,
        "retraction_speed_mm_s": 35,
    })

    # --- behaviour ---
    log_level: str = "INFO"
    cache_results: bool = True             # used by Streamlit @st.cache_data
    graceful_degradation: bool = True     # if True, fall back on errors

    # --- free-form context ---
    extra_context: str = ""               # free-text passed to LLM

    # -----------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False))

    # -----------------------------------------------------------------
    @classmethod
    def default(cls) -> "Settings":
        """Build a Settings with env-var + YAML defaults applied."""
        s = cls()
        # YAML
        yaml_path = (Path(__file__).resolve().parent.parent /
                     "config" / "default_settings.yaml")
        if yaml_path.exists():
            try:
                data = yaml.safe_load(yaml_path.read_text())
                if isinstance(data, dict):
                    for k, v in data.items():
                        if hasattr(s, k) and v is not None:
                            setattr(s, k, v)
            except Exception as e:
                logger.warning(f"[settings] YAML load failed: {e}")
        # env overrides (JOYCAD_LLM_PROVIDER, JOYCAD_CAD_ENGINE, etc.)
        env_map = {
            "JOYCAD_LLM_PROVIDER": "llm_provider",
            "JOYCAD_CAD_ENGINE": "cad_engine",
            "JOYCAD_CAM_BACKEND": "cam_backend",
            "JOYCAD_DEFAULT_MACHINE": "machine",
            "JOYCAD_LOG_LEVEL": "log_level",
            "JOYCAD_POST_PROCESSOR": "post_processor",
            "JOYCAD_PROCESS": "process",
            "JOYCAD_SLICER": "slicer",
        }
        for env_key, attr in env_map.items():
            v = os.getenv(env_key)
            if v:
                setattr(s, attr, v)
        return s

    @classmethod
    def from_request(cls, request: dict) -> "Settings":
        """Build a Settings from a dict (e.g. a FastAPI request body).

        Only known fields are applied — extra keys are stored in
        ``extra_context`` as JSON for round-trip safety.
        """
        import json
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in request.items() if k in known}
        extras = {k: v for k, v in request.items() if k not in known}
        s = cls.default()
        for k, v in clean.items():
            setattr(s, k, v)
        if extras:
            s.extra_context = (s.extra_context + "\n\n--- extras ---\n" +
                                json.dumps(extras, indent=2)).strip()
        return s


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------
PRESETS: dict[str, dict] = {
    "mvp-mock": {
        "label": "MVP demo (no API key)",
        "description": "Mock LLM, CadQuery CAD+CAM, linuxcnc_3axis. Works offline.",
        "settings": {
            "llm_provider": "mock",
            "cad_engine": "cadquery",
            "cam_backend": "cadquery_cam",
            "machine": "linuxcnc_3axis",
            "post_processor": "linuxcnc",
        },
    },
    "ollama-local": {
        "label": "Local Ollama (Llama 3.1)",
        "description": "Use a local Ollama model. Requires `ollama serve` running.",
        "settings": {
            "llm_provider": "ollama",
            "cad_engine": "cadquery",
            "cam_backend": "cadquery_cam",
            "machine": "linuxcnc_3axis",
        },
    },
    "openai-cloud": {
        "label": "OpenAI cloud (GPT-4o)",
        "description": "Real OpenAI. Needs OPENAI_API_KEY in env.",
        "settings": {
            "llm_provider": "openai",
            "cad_engine": "cadquery",
            "cam_backend": "cadquery_cam",
        },
    },
    "nvidia-cloud": {
        "label": "NVIDIA NIM cloud (Llama 3.1 70B)",
        "description": "NVIDIA build.nvidia.com NIM API. Needs NVIDIA_API_KEY. "
                       "Strong at code generation (CadQuery scripts).",
        "settings": {
            "llm_provider": "nvidia",
            "cad_engine": "cadquery",
            "cam_backend": "cadquery_cam",
            "machine": "linuxcnc_3axis",
        },
    },
    "hobby-grbl": {
        "label": "Hobby CNC (grbl 3018)",
        "description": "Smaller mill, lower feeds, no ATC.",
        "settings": {
            "machine": "grbl_3018",
            "spindle_rpm": 8000,
            "coolant": "off",
            "safe_z_mm": 3.0,
            "cam_backend": "cadquery_cam",
        },
    },
    "fdm-print": {
        "label": "FDM 3D printer (Marlin)",
        "description": "Plastic printer, sliced G-code.",
        "settings": {
            "machine": "marlin_fdm",
            "process": "3d_print_fdm",
            "write_3d_print_gcode": True,
        },
    },
}


def get_preset(name: str) -> Optional[Settings]:
    """Return a Settings pre-filled from a named preset, or None."""
    if name not in PRESETS:
        return None
    s = Settings.default()
    for k, v in PRESETS[name]["settings"].items():
        setattr(s, k, v)
    return s


def list_presets() -> list[dict]:
    """Return [{name, label, description}, ...] for the API."""
    return [{"name": k, "label": v["label"], "description": v["description"]}
            for k, v in PRESETS.items()]
