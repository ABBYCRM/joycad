"""JoyCAD outputs layer — what the bundle ships to the shop.

    • CNC G-code (post-processed, validated)
    • 3D print files (sliced)
    • Laser / plasma DXF (2D projection)
    • BOM (CSV + JSON)
    • Manufacturing notes (LLM-generated markdown)
    • 2D drawings (DXF + SVG)
"""
from .bom import extract_bom, BOMItem, BOM
from .manufacturing_notes import generate_manufacturing_notes, MfgNotes
from .drawings import make_dxf, make_svg

__all__ = [
    "extract_bom", "BOMItem", "BOM",
    "generate_manufacturing_notes", "MfgNotes",
    "make_dxf", "make_svg",
]
