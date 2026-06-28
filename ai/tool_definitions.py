"""ToolRegistry — function-call / tool-use definitions for tool-using LLMs.

A modern tool-using LLM (Claude, GPT-4o, function-calling Ollama models) can
call these tools mid-conversation. Each tool maps 1:1 to a method on the
orchestrator — so the LLM can drive the pipeline by itself if you want.
"""
from __future__ import annotations

from .base import ToolSpec


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="refine_design_intent",
        description="Convert a natural-language design intent into a structured "
                    "design brief (dimensions, features, material, tolerances).",
        parameters={
            "type": "object",
            "properties": {
                "intent": {"type": "string",
                           "description": "Free-form user description of the part."},
                "context": {"type": "string",
                            "description": "Optional extra context the user gave."},
            },
            "required": ["intent"],
        },
        required=["intent"],
    ),
    ToolSpec(
        name="generate_cad_script",
        description="Generate an executable CAD script (FreeCAD / CadQuery / "
                    "FeatureScript) from a structured brief.",
        parameters={
            "type": "object",
            "properties": {
                "brief_json": {"type": "object",
                               "description": "Output of refine_design_intent."},
                "engine": {"type": "string",
                           "enum": ["freecad", "cadquery", "onshape", "fusion"]},
            },
            "required": ["brief_json", "engine"],
        },
        required=["brief_json", "engine"],
    ),
    ToolSpec(
        name="execute_cad_script",
        description="Run the generated CAD script headlessly and produce a STEP file.",
        parameters={
            "type": "object",
            "properties": {
                "script_path": {"type": "string"},
                "out_dir":    {"type": "string"},
            },
            "required": ["script_path", "out_dir"],
        },
        required=["script_path", "out_dir"],
    ),
    ToolSpec(
        name="convert_geometry",
        description="Convert STEP to STL, or extract 2D DXF/SVG projection.",
        parameters={
            "type": "object",
            "properties": {
                "step_path": {"type": "string"},
                "out_formats": {"type": "array",
                                "items": {"type": "string",
                                          "enum": ["stl", "dxf", "svg"]}},
            },
            "required": ["step_path", "out_formats"],
        },
        required=["step_path", "out_formats"],
    ),
    ToolSpec(
        name="run_cam",
        description="Generate raw toolpaths from a STEP file using FreeCAD Path "
                    "or OpenCAMLib.",
        parameters={
            "type": "object",
            "properties": {
                "step_path": {"type": "string"},
                "machine":   {"type": "string"},
                "operations": {"type": "array",
                               "items": {"type": "string",
                                         "enum": ["face", "pocket", "drill",
                                                  "contour", "adaptive"]}},
            },
            "required": ["step_path", "machine"],
        },
        required=["step_path", "machine"],
    ),
    ToolSpec(
        name="post_process_gcode",
        description="Run a machine-specific post-processor on raw toolpaths to "
                    "emit a final G-code file.",
        parameters={
            "type": "object",
            "properties": {
                "toolpaths_path": {"type": "string"},
                "machine":         {"type": "string"},
                "out_path":        {"type": "string"},
            },
            "required": ["toolpaths_path", "machine", "out_path"],
        },
        required=["toolpaths_path", "machine", "out_path"],
    ),
    ToolSpec(
        name="run_fea",
        description="Run static FEA (CalculiX) on the STEP file under a given load case.",
        parameters={
            "type": "object",
            "properties": {
                "step_path":   {"type": "string"},
                "material":    {"type": "string"},
                "load_case":   {"type": "object"},
            },
            "required": ["step_path", "material", "load_case"],
        },
        required=["step_path", "material", "load_case"],
    ),
    ToolSpec(
        name="check_collision",
        description="Check tool-vs-part or part-vs-fixture collisions for the "
                    "given toolpath set.",
        parameters={
            "type": "object",
            "properties": {
                "step_path":      {"type": "string"},
                "toolpaths_path": {"type": "string"},
            },
            "required": ["step_path", "toolpaths_path"],
        },
        required=["step_path", "toolpaths_path"],
    ),
    ToolSpec(
        name="check_dfm",
        description="Run manufacturability rules (min wall thickness, hole spacing, "
                    "internal radii, draft angles, etc.) against the STEP.",
        parameters={
            "type": "object",
            "properties": {
                "step_path":  {"type": "string"},
                "process":    {"type": "string"},
                "material":   {"type": "string"},
            },
            "required": ["step_path", "process"],
        },
        required=["step_path", "process"],
    ),
    ToolSpec(
        name="generate_bom",
        description="Walk the assembly tree and emit a BOM (CSV + JSON).",
        parameters={
            "type": "object",
            "properties": {
                "step_path": {"type": "string"},
                "out_dir":    {"type": "string"},
            },
            "required": ["step_path", "out_dir"],
        },
        required=["step_path", "out_dir"],
    ),
    ToolSpec(
        name="generate_manufacturing_notes",
        description="Use the LLM to write human-readable manufacturing notes given "
                    "the brief, geometry, and validation reports.",
        parameters={
            "type": "object",
            "properties": {
                "brief_json": {"type": "object"},
                "reports":    {"type": "object"},
            },
            "required": ["brief_json", "reports"],
        },
        required=["brief_json", "reports"],
    ),
]


class ToolRegistry:
    def __init__(self):
        self._tools = {t.name: t for t in TOOLS}

    def list(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def to_openai(self) -> list[dict]:
        return [
            {"type": "function",
             "function": {"name": t.name, "description": t.description,
                          "parameters": t.parameters}}
            for t in self._tools.values()
        ]
