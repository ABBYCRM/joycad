"""JoyCAD CAD engine layer.

Engines (all expose ``CADEngine`` protocol):
    • FreeCADEngine       — runs a Python script via freecadcmd headless
    • CadQueryEngine      — runs CadQuery directly in-process (OCCT)
    • OnshapeEngine       — pushes a FeatureScript via Onshape REST
    • FusionEngine        — runs a Fusion add-in via the local Fusion API
"""
from .base import CADEngine, CADGeometry, register_engine, get_engine, list_engines
from .freecad_engine import FreeCADEngine
from .cadquery_engine import CadQueryEngine
from .onshape_engine import OnshapeEngine
from .fusion_engine import FusionEngine
from .geometry_io import (
    step_to_stl, stl_to_step, export_dxf, export_svg, slice_3d_print,
)

__all__ = [
    "CADEngine", "CADGeometry", "register_engine", "get_engine", "list_engines",
    "FreeCADEngine", "CadQueryEngine", "OnshapeEngine", "FusionEngine",
    "step_to_stl", "stl_to_step", "export_dxf", "export_svg", "slice_3d_print",
]
