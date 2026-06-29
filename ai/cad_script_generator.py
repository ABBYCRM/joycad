"""CADScriptGenerator — turns a StructuredBrief into an executable CAD script.

Two output modes:
  1. FreeCAD Python script (via freecadcmd headless)
  2. CadQuery Python script (pure OCCT, no GUI)

The generator pulls RAG snippets for the chosen engine so the LLM has concrete
examples to ground its output (this is what giuliano-t's pipeline proved works).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

from .base import LLMClient, LLMMessage, LLMRole
from .llm_client import llm_factory
from .prompt_refiner import StructuredBrief
from .rag_store import RAGStore


@dataclass
class CADScript:
    engine: Literal["freecad", "cadquery", "onshape", "fusion"]
    source: str
    parameters: dict
    notes: str = ""

    def save(self, path: Path) -> None:
        path.write_text(self.source)
        if self.parameters:
            (path.parent / f"{path.stem}.params.json").write_text(
                json.dumps(self.parameters, indent=2)
            )


SYSTEM_PROMPT_FREECAD = """You generate a single self-contained Python script for FreeCAD
(runnable via `freecadcmd -c script.py`).

Rules:
- Use `import FreeCAD, Part` (and optionally `Draft`, `MeshPart`).
- The script must create a single Part.Shape named `result` in the active document.
- All units are millimetres.
- Use OCC primitives directly: Part.makeBox, Part.makeCylinder, Part.makeFillet,
  etc. Compose with cut/fuse/common from Part.
- Use the parametric values given to you exactly.
- Hole positions are in the part's local coordinate system (centred on origin
  unless told otherwise).
- DO NOT add FreeCAD GUI code. DO NOT use FreeCAD.Gui. The script is headless.
- After geometry is built, set `result = shape` and call
  `FreeCAD.ActiveDocument.addObject("Part::Feature", "Part").Shape = result`
  then save the doc as STEP: `Part.export([obj], "out.step")`.
- Output ONLY the script — no prose, no fences."""


SYSTEM_PROMPT_CADQUERY = """You generate a single self-contained Python script for CadQuery
(https://cadquery.readthedocs.io).

Rules:
- ALWAYS start the script with `import cadquery as cq` (and `import math`
  if you need trig). Even though the runtime pre-loads these in scope,
  include the imports so the script is also runnable standalone.
- The script must end with a variable named `result` containing a CQ object.
- Use millimetres.
- Use cq.Workplane, .box, .cylinder, .hole, .faces, .edges, .fillet, .chamfer.
- Don't open a GUI. Don't call show_object.
- Output ONLY the script — no prose, no fences."""


SYSTEM_PROMPT_FUSION = """You generate a Fusion 360 CAM setup script (Python).

Rules:
- Use the `adsk.core`, `adsk.fusion`, `adsk.cam` modules.
- The script must be runnable inside Fusion 360's Scripts and Add-Ins dialog.
- All dimensions in millimetres.
- Output ONLY the script — no prose, no fences."""


SYSTEM_PROMPT_FEATURESCRIPT = """You generate Onshape FeatureScript code.

Rules:
- Define a single feature with `feature@name(...) { ... }` and a preview.
- Use millimetres.
- The script must be self-contained and standard-feature compatible.
- Output ONLY the script — no prose, no fences."""


ENGINE_SYSTEM = {
    "freecad":   SYSTEM_PROMPT_FREECAD,
    "cadquery":  SYSTEM_PROMPT_CADQUERY,
    "fusion":    SYSTEM_PROMPT_FUSION,
    "onshape":   SYSTEM_PROMPT_FEATURESCRIPT,
}


class CADScriptGenerator:
    def __init__(self, llm: LLMClient | None = None,
                 rag: RAGStore | None = None):
        self.llm = llm or llm_factory()
        self.rag = rag

    def generate(self, brief: StructuredBrief,
                 engine: Literal["freecad", "cadquery", "onshape", "fusion"] = "freecad",
                 *, k_rag: int = 4) -> CADScript:
        assert engine in ENGINE_SYSTEM, f"unsupported engine {engine!r}"
        logger.info(f"[CADScriptGenerator] engine={engine}  parts={brief.bbox_mm}")

        # Build the prompt with RAG retrieval if available
        rag_block = ""
        if self.rag is not None:
            query = (f"{brief.part_type} {brief.material} "
                     f"{' '.join(f.kind for f in brief.features)}")
            snippets = self.rag.query(query, k=k_rag, engine=engine)
            if snippets:
                rag_block = "\n\nReference snippets (use patterns, adapt to brief):\n\n"
                rag_block += "\n\n---\n\n".join(snippets)

        user_msg = (
            "Structured Brief (JSON):\n"
            f"```json\n{json.dumps(brief.to_dict(), indent=2)}\n```"
            f"{rag_block}\n\n"
            "Now generate the executable script. Return ONLY the script source. "
            "No commentary."
        )

        resp = self.llm.complete(
            messages=[
                LLMMessage(LLMRole.SYSTEM, ENGINE_SYSTEM[engine]),
                LLMMessage(LLMRole.USER, user_msg),
            ],
            temperature=0.1,
            max_tokens=5000,
        )
        src = _strip_code_fences(resp.content)
        return CADScript(
            engine=engine,
            source=src,
            parameters=_extract_params(brief),
            notes=f"generated by {self.llm.name}",
        )


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # drop first line ("```python" etc.) and trailing fence
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return s


def _extract_params(brief: StructuredBrief) -> dict:
    return {
        "name": brief.name,
        "material": brief.material,
        "process": brief.process,
        "bbox_mm": brief.bbox_mm,
        "thickness_mm": brief.thickness_mm,
        "tolerances_mm": brief.tolerances_mm,
        "finish": brief.finish,
        "features": [vars(f) for f in brief.features],
    }


if __name__ == "__main__":
    import sys
    from .prompt_refiner import PromptRefiner
    intent = " ".join(sys.argv[1:]) or "A 50x30x10mm aluminum plate with four M6 holes."
    brief = PromptRefiner().refine(intent)
    script = CADScriptGenerator().generate(brief, engine="cadquery")
    print(script.source)
