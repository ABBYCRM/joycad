# JoyCAD Architecture

## Pipeline contract

Every artifact that flows between layers is a Pydantic model from `orchestrator.pipeline`.
This is what makes the bundle swappable: each layer can be re-implemented as long as it
honors the input/output schema.

```
DesignIntent  ─► StructuredBrief  ─► CADScript
                                       │
                                       ▼
CADScript   ─► CADGeometry (STEP + native)
                  │
                  ├──► Mesh (STL)
                  ├──► 2D Projection (DXF / SVG)
                  └──► CAMJob
                            │
                            ▼
                      RawToolpaths
                            │
                            ├──► PostProcessor  →  G-code (.nc)
                            └──► Slicer         →  PrintGcode (.gcode.3mf)

In parallel:
  CADGeometry ─► FEA (CalculiX)        ─► FEAReport
  CADGeometry ─► Collision (FCL)       ─► CollisionReport
  CADGeometry ─► DFM rules             ─► DFMReport
  CADGeometry ─► Tolerance (TolStack)  ─► ToleranceReport
  CADGeometry ─► BOM extraction        ─► BOM
  StructuredBrief + reports            ─► ManufacturingNotes (LLM)
```

## Layer interfaces

### AI → CAD
```python
@dataclass
class StructuredBrief:
    name: str
    part_type: str                  # "bracket" | "enclosure" | "gear" | ...
    material: str                   # "6061-T6"
    dimensions_mm: dict[str, float] # length, width, height, thickness, ...
    features: list[FeatureSpec]     # holes, pockets, fillets, chamfers, ...
    tolerances: dict[str, str]
    finish: str                     # "as-milled", "anodized", ...
    notes: str

@dataclass
class CADScript:
    engine: Literal["freecad", "cadquery", "onshape", "fusion"]
    source: str                     # executable python or feature-script
    parameters: dict                # bound from brief
```

### CAD engine (uniform interface)
```python
class CADEngine(Protocol):
    name: str
    def execute(self, script: CADScript, out_dir: Path) -> CADGeometry: ...

@dataclass
class CADGeometry:
    step_path: Path
    native_path: Path | None        # .FCStd / .brep / Onshape doc id
    units: Literal["mm"]
    bbox_mm: tuple[float, float, float]
    volume_mm3: float
    surface_area_mm2: float
```

### CAM
```python
@dataclass
class CAMJob:
    machine: str                    # ref to config/machines/*.yaml
    operations: list[CAMOperation]  # face, pocket, drill, contour, ...

@dataclass
class RawToolpaths:
    operations: list[dict]          # neutral format
    estimated_time_min: float
```

### Validation reports (uniform)
```python
@dataclass
class FEAReport:        status: Literal["pass","warn","fail"]; max_vonmises_mpa: float; ...
@dataclass
class CollisionReport:  status: Literal["pass","warn","fail"]; contacts: list[dict]; ...
@dataclass
class DFMReport:        status: Literal["pass","warn","fail"]; violations: list[dict]; ...
@dataclass
class ToleranceReport:  status: Literal["pass","warn","fail"]; worst_case: float; ...
```

## Extending

- new CAD engine  → subclass `cad.base.CADEngine`, register in `cad/__init__.py`
- new CAM post    → subclass `cam.post.PostProcessor`, drop YAML into `config/machines/`
- new LLM         → subclass `ai.base.LLMClient`, set `JOYCAD_LLM_PROVIDER`
- new DFM rule    → add YAML rule to `config/dfm_rules.yaml`

## Why this split?

1. **Every layer is independently testable.** You can unit-test the DFM rule engine without
   firing up an LLM.
2. **You can swap engines per machine.** Need Fusion for a customer? Plug it in without
   touching the rest of the pipeline.
3. **RAG reuses across runs.** Knowledge base is versioned alongside config.
4. **Each layer has a single, narrow job.** Same philosophy as Unix pipes.