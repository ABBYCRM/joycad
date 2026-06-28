"""PromptRefiner — turns messy natural-language intent into a clean StructuredBrief.

Why: LLMs are great at writing parametric CAD scripts **iff** the brief is precise.
This step forces the LLM to extract: dimensions, features, tolerances, material,
finish — and to ASK for missing critical information.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from loguru import logger

from .base import LLMClient, LLMMessage, LLMRole
from .llm_client import llm_factory


@dataclass
class FeatureSpec:
    """One geometric feature (hole, pocket, fillet, etc.) on the part."""
    kind: Literal["hole", "through_hole", "blind_hole", "pocket", "slot",
                  "fillet", "chamfer", "boss", "rib", "counterbore", "countersink"]
    role: Literal["mounting", "clearance", "threaded", "fastener", "feature",
                  "decorative", "other"] = "feature"
    quantity: int = 1
    diameter_mm: float | None = None
    depth_mm: float | None = None
    position_mm: dict[str, float] | None = None      # {x,y,z} or {x,y}
    notes: str = ""
    standard: str | None = None                      # e.g. "ISO 7380" for bolts


@dataclass
class StructuredBrief:
    """Machine-readable design brief. Single source of truth across layers."""
    name: str
    part_type: str                                    # bracket, plate, enclosure, ...
    description: str
    material: str = ""                                # "6061-T6", "ABS", ...
    process: Literal["cnc_mill", "cnc_lathe", "3d_print_sla", "3d_print_fdm",
                     "3d_print_sls", "laser_cut", "plasma_cut", "sheet_metal",
                     "injection_mold", "unknown"] = "cnc_mill"
    units: Literal["mm", "in"] = "mm"

    # bounding box
    bbox_mm: dict[str, float] = field(default_factory=dict)        # {length,width,height}
    thickness_mm: float | None = None

    # feature list
    features: list[FeatureSpec] = field(default_factory=list)

    # tolerances
    tolerances_mm: dict[str, float] = field(default_factory=dict)
    surface_finish_um_ra: float | None = None

    # quantities & finish
    quantity: int = 1
    finish: str = "as-machined"                       # anodized, powder_coat, ...
    cosmetic: bool = False

    # open questions the AI can't infer — surfaced for human review
    clarifying_questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2))


SYSTEM_PROMPT = """You are a senior mechanical engineer writing a Structured Design Brief.

You receive a user's intent (sometimes vague, sometimes specific). Your job:

1. Parse the request into a precise structured brief with these exact fields:
   name, part_type, description, material, process, units,
   bbox_mm (length/width/thickness), thickness_mm,
   features[] (each with kind/role/quantity/diameter_mm/depth_mm/position_mm/notes/standard),
   tolerances_mm, surface_finish_um_ra,
   quantity, finish, cosmetic,
   clarifying_questions[] (questions you cannot answer),
   assumptions[] (assumptions you made — be explicit!)

2. Use process:
   cnc_mill | cnc_lathe | 3d_print_sla | 3d_print_fdm | 3d_print_sls |
   laser_cut | plasma_cut | sheet_metal | injection_mold | unknown

3. features[].kind MUST be one of:
   hole | through_hole | blind_hole | pocket | slot | fillet | chamfer |
   boss | rib | counterbore | countersink

4. For mounting holes, give standard (e.g. "M6", "1/4-20", "ISO 7380").

5. ALWAYS return JSON only — no prose, no markdown fences.

6. If the user is vague on critical dimensions, add them to
   clarifying_questions AND assume conservative defaults, listing them in assumptions.

7. parts are in millimetres unless the user explicitly says inches."""


class PromptRefiner:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or llm_factory()

    def refine(self, intent: str, *, context: str = "") -> StructuredBrief:
        user = intent if not context else f"{intent}\n\nAdditional context:\n{context}"
        logger.info(f"[PromptRefiner] refining intent: {intent[:80]!r}")
        resp = self.llm.complete(
            messages=[
                LLMMessage(LLMRole.SYSTEM, SYSTEM_PROMPT),
                LLMMessage(LLMRole.USER, user),
            ],
            temperature=0.1,
            max_tokens=3000,
            json_mode=True,
        )
        try:
            data = json.loads(resp.content)
        except json.JSONDecodeError as e:
            logger.error(f"[PromptRefiner] bad JSON from LLM: {resp.content[:300]}…")
            raise RuntimeError(
                f"LLM did not return valid JSON for the brief: {e}"
            ) from e

        # Re-hydrate FeatureSpec objects
        feats = [FeatureSpec(**f) for f in data.pop("features", [])]
        return StructuredBrief(features=feats, **data)


if __name__ == "__main__":
    import sys
    intent = " ".join(sys.argv[1:]) or (
        "An L-bracket, 50 mm tall, 50 mm long, 6 mm thick 6061-T6 aluminum, "
        "two M6 clearance holes on the vertical face and two on the horizontal face."
    )
    brief = PromptRefiner().refine(intent)
    print(json.dumps(brief.to_dict(), indent=2))
