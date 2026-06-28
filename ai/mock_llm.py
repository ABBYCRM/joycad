"""MockLLM — deterministic LLM that produces real, working output without an API key.

The MVP needs to be runnable end-to-end without anyone signing up for OpenAI or
spinning up Ollama. So we ship a small deterministic intent classifier + brief
generator + CadQuery script emitter that handles the common shapes:

    bracket | plate | enclosure | flange | shaft | gear | generic

Anything that doesn't match falls through to a generic box — which still produces
a real, machinable, downloadable artifact.

The mock LLM honours the LLMClient interface so the rest of the pipeline doesn't
know or care that it's not talking to GPT-4.
"""
from __future__ import annotations

import json
import re
import math
from dataclasses import asdict
from typing import Any

from .base import LLMClient, LLMMessage, LLMResponse, LLMRole
from .prompt_refiner import StructuredBrief, FeatureSpec


# ---------------------------------------------------------------------------
# Intent classifier — matches shapes to templates
# ---------------------------------------------------------------------------
SHAPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("l_bracket",  ["l-bracket", "l bracket", "lbracket", "angle bracket"]),
    ("flat_bracket", ["flat bracket", "flat-bracket", "mounting plate", "tab"]),
    ("enclosure",  ["enclosure", "box", "case", "housing"]),
    ("flange",     ["flange", "round plate", "disc", "mounting flange"]),
    ("shaft",      ["shaft", "axle", "spindle", "rod"]),
    ("gear",       ["gear", "cog", "sprocket"]),
    ("plate",      ["plate", "panel", "board", "strip"]),
]


def classify(intent: str) -> str:
    s = intent.lower()
    for shape, pats in SHAPE_PATTERNS:
        if any(p in s for p in pats):
            return shape
    return "generic"


def _parse_dimensions(intent: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(mm)?",
        intent)
    if m:
        out["length"], out["width"], out["thickness"] = (
            float(m.group(1)), float(m.group(2)), float(m.group(3)))
    for label, pat in [
        ("length",   r"(?:length|L|long)\s*=?\s*(\d+(?:\.\d+)?)\s*mm"),
        ("width",    r"(?:width|W|wide)\s*=?\s*(\d+(?:\.\d+)?)\s*mm"),
        ("thickness", r"(?:thickness|T|thick)\s*=?\s*(\d+(?:\.\d+)?)\s*mm"),
        ("height",   r"(?:height|H|tall)\s*=?\s*(\d+(?:\.\d+)?)\s*mm"),
        ("diameter", r"(?:diameter|dia|Ø|phi)\s*=?\s*(\d+(?:\.\d+)?)\s*mm"),
        ("radius",   r"(?:radius|R)\s*=?\s*(\d+(?:\.\d+)?)\s*mm"),
    ]:
        m = re.search(pat, intent, re.IGNORECASE)
        if m:
            out[label] = float(m.group(1))
    out["bolts"] = []
    for m in re.finditer(r"M(\d+(?:\.\d+)?)", intent):
        out["bolts"].append({"size": float(m.group(1)),
                             "clearance_mm": float(m.group(1)) + 0.6})
    return out


def _default_material(intent: str) -> str:
    s = intent.lower()
    for m in ["steel", "stainless", "brass", "copper", "abs", "petg",
             "pla", "tpu", "nylon", "aluminum", "aluminium"]:
        if m in s:
            return {"aluminum": "6061-T6", "aluminium": "6061-T6",
                    "steel": "1018", "stainless": "316",
                    "abs": "ABS", "petg": "PETG", "pla": "PLA",
                    "tpu": "TPU", "nylon": "PA12",
                    "brass": "C360", "copper": "C110"}[m]
    return "6061-T6"


def _process(intent: str, dims: dict) -> str:
    s = intent.lower()
    if "3d print" in s or "fdm" in s or "sla" in s:
        if "sla" in s: return "3d_print_sla"
        return "3d_print_fdm"
    if "laser" in s: return "laser_cut"
    if "plasma" in s: return "plasma_cut"
    if "sheet" in s or "bend" in s: return "sheet_metal"
    if "lathe" in s or dims.get("diameter"): return "cnc_lathe"
    return "cnc_mill"


def _make_bracket_brief(intent, dims, material, process):
    L = dims.get("length", 50); W = dims.get("width", 30)
    H = dims.get("height", 50); T = dims.get("thickness", 6)
    bolts = dims.get("bolts") or [{"size": 6, "clearance_mm": 6.6}]
    bsz = bolts[0]["size"]; bcl = bolts[0]["clearance_mm"]
    return StructuredBrief(
        name="bracket-001", part_type="bracket", description=intent.strip(),
        material=material, process=process,
        bbox_mm={"length": L, "width": W, "thickness": T, "height": H},
        thickness_mm=T,
        features=[
            FeatureSpec(kind="through_hole", role="mounting", quantity=1,
                        diameter_mm=bcl,
                        position_mm={"x": T/2 + 8, "y": T/2, "z": 15},
                        standard=f"M{bsz} clearance"),
            FeatureSpec(kind="through_hole", role="mounting", quantity=1,
                        diameter_mm=bcl,
                        position_mm={"x": L - T/2 - 8, "y": T/2, "z": 15},
                        standard=f"M{bsz} clearance"),
            FeatureSpec(kind="through_hole", role="mounting", quantity=1,
                        diameter_mm=bcl,
                        position_mm={"x": T/2 + 8, "y": T/2 + (W-T)/2, "z": T/2},
                        standard=f"M{bsz} clearance"),
            FeatureSpec(kind="through_hole", role="mounting", quantity=1,
                        diameter_mm=bcl,
                        position_mm={"x": L - T/2 - 8, "y": T/2 + (W-T)/2, "z": T/2},
                        standard=f"M{bsz} clearance"),
        ],
        tolerances_mm={"linear": 0.1, "hole": 0.1},
        surface_finish_um_ra=1.6, finish="as-machined", cosmetic=False,
        assumptions=[f"Defaults: 4 mounting holes, M{bsz}, chamfered edges."],
    )


def _make_plate_brief(intent, dims, material, process):
    L = dims.get("length", 80); W = dims.get("width", 40); T = dims.get("thickness", 6)
    bolts = dims.get("bolts") or [{"size": 6, "clearance_mm": 6.6}]
    bcl = bolts[0]["clearance_mm"]
    return StructuredBrief(
        name="plate-001", part_type="plate", description=intent.strip(),
        material=material, process=process,
        bbox_mm={"length": L, "width": W, "thickness": T},
        thickness_mm=T,
        features=[
            FeatureSpec(kind="through_hole", role="mounting", quantity=4,
                        diameter_mm=bcl,
                        position_mm={"x": T/2 + 5, "y": T/2 + 5},
                        standard=f"M{bolts[0]['size']} clearance"),
        ],
        tolerances_mm={"linear": 0.1, "hole": 0.1},
        surface_finish_um_ra=1.6, finish="as-machined",
        assumptions=["Defaults: 4 corner mounting holes."],
    )


def _make_enclosure_brief(intent, dims, material, process):
    L = dims.get("length", 100); W = dims.get("width", 60)
    H = dims.get("height", 20)
    # wall thickness defaults to 3 mm unless explicitly given as a small value
    T = dims.get("thickness", 3)
    if T >= H / 2:
        T = 3                                   # user gave overall dims, not wall
    return StructuredBrief(
        name="enclosure-001", part_type="enclosure", description=intent.strip(),
        material=material, process=process,
        bbox_mm={"length": L, "width": W, "thickness": H},
        thickness_mm=T,
        features=[
            FeatureSpec(kind="pocket", role="feature", quantity=1,
                        diameter_mm=None,
                        position_mm={"x": T + 5, "y": T + 5, "z": H - T - 5},
                        notes=f"interior pocket {L-2*T-10} x {W-2*T-10} x {H-T-5}"),
            FeatureSpec(kind="fillet", role="feature",
                        notes=f"3 mm internal fillets"),
        ],
        tolerances_mm={"linear": 0.2, "hole": 0.2},
        surface_finish_um_ra=3.2, finish="as-printed",
        assumptions=["Defaults: 3 mm walls, top-open pocket, filleted inside corners."],
    )


def _make_flange_brief(intent, dims, material, process):
    D = dims.get("diameter", 80); T = dims.get("thickness", 10)
    bolts = dims.get("bolts") or [{"size": 6, "clearance_mm": 6.6}]
    bcl = bolts[0]["clearance_mm"]
    nb = 6
    return StructuredBrief(
        name="flange-001", part_type="flange", description=intent.strip(),
        material=material, process=process,
        bbox_mm={"length": D, "width": D, "thickness": T},
        thickness_mm=T,
        features=[
            FeatureSpec(kind="through_hole", role="clearance", quantity=1,
                        diameter_mm=D/3,
                        position_mm={"x": 0, "y": 0},
                        notes="central bore"),
            FeatureSpec(kind="through_hole", role="mounting", quantity=nb,
                        diameter_mm=bcl,
                        position_mm={"x": D*0.37, "y": 0},
                        standard=f"M{bolts[0]['size']} clearance on {nb}-hole bolt circle"),
            FeatureSpec(kind="chamfer", role="feature", notes="1 mm chamfer on all edges"),
        ],
        tolerances_mm={"linear": 0.1, "hole": 0.1, "diameter": 0.05},
        surface_finish_um_ra=1.6, finish="as-machined",
        assumptions=[f"Defaults: {nb}-hole bolt circle at 0.37 D, 1 mm chamfer."],
    )


def _make_shaft_brief(intent, dims, material, process):
    D = dims.get("diameter", 10); L = dims.get("length", 80)
    return StructuredBrief(
        name="shaft-001", part_type="shaft", description=intent.strip(),
        material=material, process=process,
        bbox_mm={"length": L, "width": D, "thickness": D},
        features=[
            FeatureSpec(kind="slot", role="feature",
                        notes=f"keyway 5 mm wide x 20 mm long centered"),
        ],
        tolerances_mm={"linear": 0.05, "diameter": 0.02},
        surface_finish_um_ra=0.8, finish="ground",
        assumptions=[f"Defaults: cylinder dia {D} mm, length {L} mm, single keyway."],
    )


def _make_gear_brief(intent, dims, material, process):
    D = dims.get("diameter", 40); T = dims.get("thickness", 6)
    teeth = max(8, int(D / 2))
    return StructuredBrief(
        name="gear-001", part_type="gear", description=intent.strip(),
        material=material, process=process,
        bbox_mm={"length": D, "width": D, "thickness": T},
        thickness_mm=T,
        features=[
            FeatureSpec(kind="through_hole", role="clearance", quantity=1,
                        diameter_mm=5,
                        position_mm={"x": 0, "y": 0},
                        notes=f"bore for 5 mm shaft"),
        ],
        tolerances_mm={"diameter": 0.05, "linear": 0.1},
        surface_finish_um_ra=1.6, finish="as-machined",
        assumptions=[f"Defaults: spur gear, {teeth} teeth, module 2, 5 mm bore."],
    )


def _make_generic_brief(intent, dims, material, process):
    L = dims.get("length", 50); W = dims.get("width", 50); T = dims.get("thickness", 10)
    return StructuredBrief(
        name="part-001", part_type="generic", description=intent.strip(),
        material=material, process=process,
        bbox_mm={"length": L, "width": W, "thickness": T},
        thickness_mm=T,
        features=[
            FeatureSpec(kind="through_hole", role="mounting", quantity=4,
                        diameter_mm=3.3,
                        position_mm={"x": T + 5, "y": T + 5},
                        standard="M3 clearance"),
        ] if dims.get("bolts") else [],
        tolerances_mm={"linear": 0.2, "hole": 0.2},
        surface_finish_um_ra=3.2, finish="as-machined",
        assumptions=["Generic box fallback; refine the intent for richer features."],
    )


SHAPE_TO_BRIEF = {
    "l_bracket":   _make_bracket_brief,
    "flat_bracket": _make_bracket_brief,
    "plate":       _make_plate_brief,
    "enclosure":   _make_enclosure_brief,
    "flange":      _make_flange_brief,
    "shaft":       _make_shaft_brief,
    "gear":        _make_gear_brief,
    "generic":     _make_generic_brief,
}


def mock_brief(intent: str):
    dims = _parse_dimensions(intent)
    material = _default_material(intent)
    process = _process(intent, dims)
    shape = classify(intent)
    return SHAPE_TO_BRIEF[shape](intent, dims, material, process), shape


# ---------------------------------------------------------------------------
# CadQuery script emitter — one per shape, all produce `result = ...`
# ---------------------------------------------------------------------------
CQ_BRACKET = """\
import cadquery as cq

# L-bracket: vertical face + horizontal face, with mounting holes
L, W, H, T = {L}, {W}, {H}, {T}
HOLE = {hole}

vertical   = cq.Workplane("XY").box(L, T, H, centered=(True, False, False))
horizontal = cq.Workplane("XY").box(L, W, T, centered=(True, False, False))

result = vertical.union(horizontal)

# vertical face holes
result = (result.faces("<Y").workplane(centerOption="CenterOfBoundBox")
          .pushPoints([({vx1}, 15), ({vx2}, 15)])
          .hole(HOLE))

# horizontal face holes
result = (result.faces(">Z").workplane(centerOption="CenterOfBoundBox")
          .pushPoints([({hx1}, {hy1}), ({hx2}, {hy2})])
          .hole(HOLE))

result = result.edges("|Z").chamfer(0.5)
"""


def _script_for_shape(shape: str, brief: StructuredBrief) -> str:
    bb = brief.bbox_mm
    if shape in ("l_bracket", "flat_bracket"):
        L = bb.get("length", 50); W = bb.get("width", 30)
        H = bb.get("height", 50); T = bb.get("thickness", 6)
        hole = 6.6 if not brief.features else brief.features[0].diameter_mm or 6.6
        return CQ_BRACKET.format(
            L=L, W=W, H=H, T=T, hole=hole,
            vx1=T/2 + 8, vx2=L - T/2 - 8,
            hx1=T/2 + 8, hy1=T/2 + (W-T)/2,
            hx2=L - T/2 - 8, hy2=T/2 + (W-T)/2,
        )

    if shape == "plate":
        L = bb.get("length", 80); W = bb.get("width", 40); T = bb.get("thickness", 6)
        hole = 6.6
        return f"""\
import cadquery as cq

L, W, T = {L}, {W}, {T}
result = (
    cq.Workplane("XY").box(L, W, T)
      .faces(">Z").workplane()
      .rect(L - 2*T, W - 2*T, forConstruction=True)
      .vertices()
      .hole({hole})
      .edges("|Z").chamfer(0.5)
)
"""

    if shape == "enclosure":
        L = bb.get("length", 100); W = bb.get("width", 60)
        H = bb.get("height", 20)
        T = brief.thickness_mm or 3
        return f"""\
import cadquery as cq

L, W, H, T = {L}, {W}, {H}, {T}
result = (
    cq.Workplane("XY").box(L, W, H)
      .faces(">Z").workplane()
      .rect(L - 2*T, W - 2*T).cutBlind(-(H - T))
      .edges("|Z").chamfer(0.5)
)
"""

    if shape == "flange":
        D = bb.get("length", 80); T = bb.get("thickness", 10)
        hole = 6.6; nb = 6; r_bolt = D * 0.37 / 2
        bore = D / 3
        pts = [(r_bolt * math.cos(2*math.pi*i/nb), r_bolt * math.sin(2*math.pi*i/nb))
               for i in range(nb)]
        return f"""\
import cadquery as cq

D, T = {D}, {T}
BORE = {bore}
HOLE = {hole}
N = {nb}
R = D * 0.37 / 2

result = (
    cq.Workplane("XY").circle(D/2).extrude(T)
      .faces(">Z").workplane()
      .circle(BORE/2).cutThruAll()
      .pushPoints({pts!r})
      .circle(HOLE/2).cutThruAll()
      .edges().chamfer(1.0)
)
"""

    if shape == "shaft":
        D = bb.get("diameter", 10); L = bb.get("length", 80)
        return f"""\
import cadquery as cq

D, L = {D}, {L}
result = (
    cq.Workplane("XY").circle(D/2).extrude(L)
      .faces(">Z").workplane(centerOption="CenterOfBoundBox")
      .rect(5, 4).cutBlind(-20)
)
"""

    if shape == "gear":
        D = bb.get("length", 40); T = bb.get("thickness", 6)
        teeth = max(8, int(D / 2))
        bore = 5
        return f"""\
import cadquery as cq, math

D, T = {D}, {T}
teeth = {teeth}
bore = {bore}
r_pitch = D / 2
m = (2 * math.pi * r_pitch) / teeth
addendum = m
dedendum = 1.25 * m
r_outer = r_pitch + addendum
r_root = r_pitch - dedendum

# build teeth by sweeping a trapezoidal profile around the centre
result = cq.Workplane("XY").circle(r_outer).extrude(T)

# subtract the root circle (between teeth) — simpler & always works
result = (result.faces(">Z").workplane()
                .circle(r_root).cutThruAll())

# cut a small tooth gap for visual: square notch at each tooth
import math
for i in range(teeth):
    angle = 2 * math.pi * i / teeth
    cx = r_pitch * math.cos(angle)
    cy = r_pitch * math.sin(angle)
    result = (result.faces(">Z").workplane(offset=-0.5)
                    .center(cx, cy)
                    .rect(m * 0.5, addendum * 2)
                    .cutThruAll())

# bore
result = (result.faces(">Z").workplane()
                .circle(bore/2).cutThruAll())

result = result.edges().chamfer(0.3)
"""

    L = bb.get("length", 50); W = bb.get("width", 50); T = bb.get("thickness", 10)
    return f"""\
import cadquery as cq

L, W, T = {L}, {W}, {T}
result = cq.Workplane("XY").box(L, W, T).edges("|Z").chamfer(1.0)
"""


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------
class MockLLMClient(LLMClient):
    """Deterministic LLM. Plug it in by setting JOYCAD_LLM_PROVIDER=mock."""
    name = "mock"

    def complete(self, messages, *, temperature=0.0, max_tokens=4096,
                 tools=None, tool_choice=None, json_mode=False):
        system = next((m.content for m in messages if m.role == LLMRole.SYSTEM), "")
        user = next((m.content for m in messages if m.role == LLMRole.USER), "")
        sys_lc = system.lower()

        # IMPORTANT: check manufacturing notes FIRST — its system prompt
        # contains "structured design brief" which would otherwise trigger
        # the brief branch.
        if "manufacturing notes" in sys_lc or "manufacturing note" in sys_lc:
            return LLMResponse(content=_fake_mfg_notes(user), provider=self.name)

        if "structured design brief" in sys_lc or "structured brief" in sys_lc:
            brief, _shape = mock_brief(user.split("\nAdditional")[0])
            return LLMResponse(content=json.dumps(brief.to_dict()),
                               provider=self.name)

        if "freecad" in sys_lc or "cadquery" in sys_lc or "featurescript" in sys_lc:
            m = re.search(r"```json\s*(\{.*?\})\s*```", user, re.DOTALL)
            if m:
                brief_dict = json.loads(m.group(1))
                brief = StructuredBrief(
                    name=brief_dict.get("name", "part-001"),
                    part_type=brief_dict.get("part_type", "generic"),
                    description=brief_dict.get("description", ""),
                    material=brief_dict.get("material", "6061-T6"),
                    process=brief_dict.get("process", "cnc_mill"),
                    bbox_mm=brief_dict.get("bbox_mm", {}),
                    thickness_mm=brief_dict.get("thickness_mm"),
                    tolerances_mm=brief_dict.get("tolerances_mm", {}),
                    surface_finish_um_ra=brief_dict.get("surface_finish_um_ra"),
                    finish=brief_dict.get("finish", "as-machined"),
                    features=[FeatureSpec(**f) for f in brief_dict.get("features", [])],
                )
                shape = classify(brief.description)
                src = _script_for_shape(shape, brief)
                return LLMResponse(content="```python\n" + src + "\n```",
                                   provider=self.name)
            intent = re.search(r"intent['\"]?\s*[:=]\s*['\"]?([^'\"\\n]+)", user)
            intent = intent.group(1) if intent else user
            brief, shape = mock_brief(intent)
            src = _script_for_shape(shape, brief)
            return LLMResponse(content="```python\n" + src + "\n```",
                               provider=self.name)

        return LLMResponse(content="(mock: no handler for system: "
                                   + sys_lc[:60] + ")",
                           provider=self.name)


def _fake_mfg_notes(user: str) -> str:
    m = re.search(r'"name":\s*"([^"]+)"', user)
    name = m.group(1) if m else "part"
    m = re.search(r'"material":\s*"([^"]+)"', user)
    mat = m.group(1) if m else "6061-T6"
    m = re.search(r'"process":\s*"([^"]+)"', user)
    process = m.group(1) if m else "cnc_mill"
    m = re.search(r'"length":\s*(\d+(?:\.\d+)?)', user)
    L = float(m.group(1)) if m else None
    m = re.search(r'"width":\s*(\d+(?:\.\d+)?)', user)
    W = float(m.group(1)) if m else None
    m = re.search(r'"thickness":\s*(\d+(?:\.\d+)?)', user)
    T = float(m.group(1)) if m else None
    L_stock = f"{L + 3:.1f}" if L else "?"
    W_stock = f"{W + 3:.1f}" if W else "?"
    T_stock = f"{T + 3:.1f}" if T else "?"
    return f"""# Manufacturing Notes -- {name}

> Generated by JoyCAD mock LLM. Verify with your machinist.

## 1. Setup and workholding

- Stock: {L_stock} x {W_stock} x {T_stock} mm (bbox + 3 mm cleanup)
- Material: **{mat}**
- Process: {process}
- Workholding: vise with soft jaws machined to stock profile, or vacuum for sheet.

## 2. Operation sequence

1. **Face** stock to clean datum (T1 6 mm endmill, 0.5 mm depth, 60 % stepover)
2. **Rough** pockets with adaptive clearing (T4 10 mm, 3 mm stepdown)
3. **Finish** walls (T1 6 mm, 0.5 mm stepdown)
4. **Drill** all holes (T3 6.6 mm for M6, T7 for M3 etc.)
5. **Chamfer** all external edges (T2 3 mm, 0.5 mm chamfer)

## 3. Tool list

- **T1** 6 mm carbide endmill -- facing, profiling
- **T2** 3 mm carbide endmill -- fine pockets
- **T3** 6.6 mm carbide drill -- M6 clearance
- **T4** 10 mm carbide endmill -- bulk roughing

## 4. Feeds and speeds (starting points, {mat})

| Tool | RPM | Feed (mm/min) | Plunge (mm/min) |
|------|-----|---------------|------------------|
| T1   | 10 000 | 600         | 200              |
| T2   | 12 000 | 300         | 100              |
| T3   |  3 000 | 200         | 80               |
| T4   |  8 000 | 1200        | 400              |

## 5. Inspection

- CMM or calipers per drawing
- Pin gage set for holes
- Surface finish profilometer (Ra 1.6 um)
- First-article dimensional report

## 6. Risks

- Confirm FEA safety factor > 1.5 before sign-off
- Verify DFM violations resolved
- Confirm stock dimensions before cutting
"""


if __name__ == "__main__":
    intent = ("An L-bracket, 50 mm long, 50 mm tall, 30 mm wide, 6 mm thick, "
              "with 4 M6 mounting holes, 6061-T6 aluminum.")
    brief, shape = mock_brief(intent)
    print(f"shape={shape}")
    print(json.dumps(brief.to_dict(), indent=2))
    print("---")
    print(_script_for_shape(shape, brief))
