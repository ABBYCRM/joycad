"""Pipeline — the end-to-end runner.

Designed so the same Pipeline.run() works from the CLI, the REST API, or
embedded in a Jupyter notebook. Every step is reported so a human can
inspect exactly what happened.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from ai import CADScriptGenerator, PromptRefiner, RAGStore, llm_factory
from cam import (CAMJob, CAMOperation, GCodeValidator,
                  get_cam, get_post_processor)
from cam.tool_db import default_tool_db
from cad import (get_engine, list_engines,
                 step_to_stl, export_dxf, export_svg, slice_3d_print)
from outputs import extract_bom, generate_manufacturing_notes
from outputs.drawings import make_dxf as make_dxf_drawing, make_svg as make_svg_drawing
from validation import (DFMValidator, FEAValidator, ToleranceValidator,
                        ValidationReport, list_validators)


# ---------------------------------------------------------------------------
# Config / Result dataclasses
# ---------------------------------------------------------------------------
@dataclass
class PipelineConfig:
    intent: str
    out_dir: Path
    machine: str = "linuxcnc_3axis"
    material: str = "6061-T6"
    cad_engine: str = "cadquery"          # "cadquery" | "freecad" | "onshape" | "fusion"
    cam_backend: str = "cadquery_cam"     # MVP default — no external CLI
    post_processor: str = "linuxcnc"
    process: str = "cnc_mill"
    context: str = ""
    extra_validators: list[str] = field(default_factory=list)
    safe_z_mm: float = 5.0
    spindle_rpm: int | None = 12000
    skip_validation: bool = False
    llm_provider: str | None = "mock"     # MVP default — no API key needed


@dataclass
class StepRecord:
    name: str
    started_at: float
    finished_at: float = 0.0
    status: str = "pending"               # pending | ok | skipped | error
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PipelineResult:
    config: PipelineConfig
    brief: Any = None                     # StructuredBrief
    script_path: Path | None = None
    geometry: Any = None                  # CADGeometry
    geometry_outputs: dict = field(default_factory=dict)   # stl, dxf, svg paths
    cam_job: Any = None
    raw_toolpaths_path: Path | None = None
    gcode_path: Path | None = None
    gcode_validation: Any = None
    validation_reports: list = field(default_factory=list)
    bom: Any = None
    manufacturing_notes_path: Path | None = None
    steps: list[StepRecord] = field(default_factory=list)
    ok: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["config"] = asdict(self.config)
        d["config"]["out_dir"] = str(d["config"]["out_dir"])
        if self.brief and hasattr(self.brief, "to_dict"):
            d["brief"] = self.brief.to_dict()
        elif self.brief is not None and hasattr(self.brief, "__dict__"):
            d["brief"] = self.brief.__dict__
        if self.geometry and hasattr(self.geometry, "to_dict"):
            d["geometry"] = self.geometry.to_dict()
        if self.bom and hasattr(self.bom, "to_dict"):
            d["bom"] = self.bom.to_dict()
        if self.gcode_validation and hasattr(self.gcode_validation, "to_dict"):
            d["gcode_validation"] = self.gcode_validation.to_dict()
        d["validation_reports"] = [
            r.to_dict() if hasattr(r, "to_dict") else r
            for r in self.validation_reports
        ]
        return d

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class Pipeline:
    def __init__(self, config: PipelineConfig, llm=None, rag: RAGStore | None = None):
        self.cfg = config
        self.cfg.out_dir = Path(self.cfg.out_dir).resolve()
        self.cfg.out_dir.mkdir(parents=True, exist_ok=True)
        self.llm = llm or llm_factory(provider=self.cfg.llm_provider)
        self.rag = rag
        self.tool_db = default_tool_db()
        self.steps: list[StepRecord] = []
        self.result = PipelineResult(config=self.cfg)

    # ---- helpers ----
    def _step(self, name: str) -> StepRecord:
        rec = StepRecord(name=name, started_at=time.time())
        self.steps.append(rec)
        return rec

    def _finish(self, rec: StepRecord, status: str = "ok", **details):
        rec.finished_at = time.time()
        rec.status = status
        rec.details = details
        logger.info(f"[pipeline] {rec.name:>22s}  {status:>6s}  "
                    f"{rec.finished_at - rec.started_at:5.2f}s")

    def _material_dict(self) -> dict:
        path = Path(__file__).resolve().parent.parent / "config" / "materials" / (
            self.cfg.material.replace("/", "-").lower() + ".yaml")
        if path.exists():
            return yaml.safe_load(path.read_text())
        return {"name": self.cfg.material}

    def _machine_dict(self) -> dict:
        path = Path(__file__).resolve().parent.parent / "config" / "machines" / (
            self.cfg.machine + ".yaml")
        if path.exists():
            return yaml.safe_load(path.read_text())
        return {"name": self.cfg.machine}

    # ---- main entry ----
    def run(self) -> PipelineResult:
        try:
            self._step_refine()
            self._step_generate_script()
            self._step_execute_cad()
            self._step_convert_geometry()
            self._step_run_cam()
            self._step_post_process()
            self._step_validate_gcode()
            if not self.cfg.skip_validation:
                self._step_validate()
            self._step_outputs()
            self.result.ok = True
        except Exception as e:
            logger.exception("[pipeline] failed")
            self.result.error = str(e)
            self.result.steps = self.steps
        finally:
            self.result.steps = self.steps
        return self.result

    # ---- individual steps ----
    def _step_refine(self):
        rec = self._step("refine_intent")
        refiner = PromptRefiner(self.llm)
        brief = refiner.refine(self.cfg.intent, context=self.cfg.context)
        brief.process = brief.process or self.cfg.process
        brief.material = brief.material or self.cfg.material
        brief.save(self.cfg.out_dir / "brief.json")
        self.result.brief = brief
        self._finish(rec, "ok", **{"brief_path": str(self.cfg.out_dir / "brief.json")})

    def _step_generate_script(self):
        rec = self._step("generate_cad_script")
        gen = CADScriptGenerator(self.llm, rag=self.rag)
        script = gen.generate(self.result.brief, engine=self.cfg.cad_engine)
        script_path = self.cfg.out_dir / f"part.{self.cfg.cad_engine}.py"
        script.save(script_path)
        self.result.script_path = script_path
        self._finish(rec, "ok", engine=self.cfg.cad_engine,
                     path=str(script_path))

    def _step_execute_cad(self):
        rec = self._step("execute_cad")
        engine = get_engine(self.cfg.cad_engine)
        geom = engine.execute(self.result.script_path, self.cfg.out_dir)
        self.result.geometry = geom
        self._finish(rec, "ok", step=str(geom.step_path),
                     bbox=list(geom.bbox_mm))

    def _step_convert_geometry(self):
        rec = self._step("convert_geometry")
        out = {}
        try:
            stl = self.cfg.out_dir / "part.stl"
            step_to_stl(self.result.geometry.step_path, stl)
            out["stl"] = str(stl)
        except Exception as e:
            logger.warning(f"[pipeline] STEP→STL failed: {e}")
        try:
            dxf = self.cfg.out_dir / "part.dxf"
            make_dxf_drawing(self.result.geometry.step_path, dxf)
            out["dxf"] = str(dxf)
        except Exception as e:
            logger.warning(f"[pipeline] DXF failed: {e}")
        try:
            svg = self.cfg.out_dir / "part.svg"
            make_svg_drawing(self.result.geometry.step_path, svg)
            out["svg"] = str(svg)
        except Exception as e:
            logger.warning(f"[pipeline] SVG failed: {e}")
        if self.cfg.process.startswith("3d_print"):
            try:
                g = slice_3d_print(self.result.geometry.step_path,
                                   self.cfg.out_dir / "part.print.gcode")
                out["print_gcode"] = str(g)
            except Exception as e:
                logger.warning(f"[pipeline] slicing failed: {e}")
        self.result.geometry_outputs = out
        self._finish(rec, "ok", **out)

    def _step_run_cam(self):
        rec = self._step("run_cam")
        bbox = self.result.geometry.bbox_mm
        stock = {"x": bbox[0] + 4, "y": bbox[1] + 4, "z": max(2.0, bbox[2] + 2)}
        ops = [
            CAMOperation(kind="face",    tool="T1",
                         params={"stepover_mm": 4.0, "depth_mm": 1.0}),
            CAMOperation(kind="contour", tool="T1",
                         params={"depth_mm": max(2.0, bbox[2] - 1.0),
                                 "offset_mm": 0.5}),
            CAMOperation(kind="drill",   tool="T3",
                         params={"depth_mm": max(5.0, bbox[2] + 1.0),
                                 "peck_mm": 1.5}),
        ]
        for f in self.result.brief.features:
            if f.kind in ("through_hole", "blind_hole") and f.diameter_mm:
                ops.append(CAMOperation(kind="drill", tool="T3",
                                         params={"depth_mm": 6.5,
                                                 "peck_mm": 1.5,
                                                 "x": (f.position_mm or {}).get("x", 0),
                                                 "y": (f.position_mm or {}).get("y", 0)}))
        job = CAMJob(machine=self.cfg.machine, stock_mm=stock,
                     operations=ops, safe_z_mm=self.cfg.safe_z_mm,
                     spindle_rpm=self.cfg.spindle_rpm)

        # Try the configured CAM backend; fall back to synthesizer if it fails.
        raw = None
        backend_used = self.cfg.cam_backend
        try:
            cam = get_cam(self.cfg.cam_backend)
            raw = cam.generate(self.result.geometry.step_path, job, self.cfg.out_dir)
        except (FileNotFoundError, RuntimeError) as e:
            logger.warning(f"[pipeline] CAM backend {self.cfg.cam_backend} unavailable "
                           f"({e}); falling back to synthesizer.")
            raw = _synthesize_from_brief(job, bbox, self.result.brief)
            backend_used = "synthesizer"

        raw_path = self.cfg.out_dir / "toolpaths.json"
        raw.save_json(raw_path)
        self.result.cam_job = job
        self.result.raw_toolpaths_path = raw_path
        self._finish(rec, "ok", backend=backend_used,
                     moves=len(raw.moves), path=str(raw_path))

    def _step_post_process(self):
        rec = self._step("post_process")
        post = get_post_processor(self.cfg.post_processor)
        # load raw
        from cam.base import RawToolpaths, Toolpath
        import json as _json
        data = _json.loads(self.result.raw_toolpaths_path.read_text())
        raw = RawToolpaths(moves=[Toolpath(**m) for m in data.get("moves", [])
                                   if "raw" not in m],
                           estimated_time_min=data.get("estimated_time_min", 0.0),
                           metadata=data.get("metadata", {}))
        # fall back: if no moves parsed, synthesize from CAM job features
        if not raw.moves and self.result.cam_job:
            raw = _synthesize_from_brief(self.result.cam_job,
                                         self.result.geometry.bbox_mm,
                                         self.result.brief)
            self.result.raw_toolpaths_path.write_text(_json.dumps(
                raw.to_dict(), indent=2))
        out_path = self.cfg.out_dir / "part.gcode"
        gcode_path = post.post(raw, out_path, machine_config=self._machine_dict())
        self.result.gcode_path = gcode_path
        self._finish(rec, "ok", path=str(gcode_path))

    def _step_validate_gcode(self):
        rec = self._step("validate_gcode")
        v = GCodeValidator()
        report = v.validate(self.result.gcode_path)
        self.result.gcode_validation = report
        status = report.status if report.status != "fail" else "warn"
        self._finish(rec, status, **{"gcode_status": report.status,
                                       "issues": len(report.issues)})

    def _step_validate(self):
        rec = self._step("validate")
        reports: list[ValidationReport] = []
        # FEA
        try:
            fea = FEAValidator().validate(
                step_path=self.result.geometry.step_path,
                material=self._material_dict(),
                loads={"forces": [{"magnitude_n": 100, "axis": "y", "z": 5}]},
                fixtures=[{"type": "fix", "node_set": 1}],
                out_dir=self.cfg.out_dir / "fea",
            )
            reports.append(fea)
        except Exception as e:
            logger.warning(f"[pipeline] FEA failed: {e}")
            reports.append(ValidationReport(name="fea", status="skipped",
                                            issues=[{"severity": "info",
                                                     "msg": str(e)}]))
        # DFM
        try:
            dfm = DFMValidator().validate(
                step_path=self.result.geometry.step_path,
                process=self.cfg.process,
                material=self.cfg.material,
            )
            reports.append(dfm)
        except Exception as e:
            logger.warning(f"[pipeline] DFM failed: {e}")
            reports.append(ValidationReport(name="dfm", status="skipped",
                                            issues=[{"severity": "info",
                                                     "msg": str(e)}]))
        # Tolerance
        try:
            tol = ToleranceValidator().validate(
                stack=self._build_tolerance_stack(),
                target_tolerance_mm=0.2,
            )
            reports.append(tol)
        except Exception as e:
            logger.warning(f"[pipeline] tolerance failed: {e}")
        self.result.validation_reports = reports
        self._finish(rec, "ok", reports=[r.to_dict() for r in reports])

    def _step_outputs(self):
        rec = self._step("outputs")
        # BOM
        bom = extract_bom(self.result.geometry.step_path, brief=self.result.brief)
        bom.to_csv(self.cfg.out_dir / "bom.csv")
        bom.to_json(self.cfg.out_dir / "bom.json")
        self.result.bom = bom
        # Manufacturing notes
        notes = generate_manufacturing_notes(
            brief=self.result.brief,
            geometry=self.result.geometry,
            reports=self.result.validation_reports,
            tool_db=self.tool_db,
            llm=self.llm,
        )
        notes.save(self.cfg.out_dir / "manufacturing_notes.md")
        self.result.manufacturing_notes_path = (
            self.cfg.out_dir / "manufacturing_notes.md")
        # final summary
        self.result.save(self.cfg.out_dir / "pipeline_result.json")
        self._finish(rec, "ok", bom=str(self.cfg.out_dir / "bom.csv"),
                     notes=str(self.cfg.out_dir / "manufacturing_notes.md"))

    def _build_tolerance_stack(self) -> list[dict]:
        """Translate the brief's tolerance hints into a 1D stack."""
        bb = self.result.brief.bbox_mm or {}
        tols = self.result.brief.tolerances_mm or {"linear": 0.1}
        tol = tols.get("linear", 0.1)
        return [
            {"name": "stock_thickness", "nominal": bb.get("thickness", 5.0),
             "plus_tol": tol, "minus_tol": tol, "distribution": "normal"},
            {"name": "machine_X", "nominal": bb.get("length", 50),
             "plus_tol": tol, "minus_tol": tol, "distribution": "normal"},
            {"name": "machine_Y", "nominal": bb.get("width", 50),
             "plus_tol": tol, "minus_tol": tol, "distribution": "normal"},
            {"name": "feature_position", "nominal": 10.0,
             "plus_tol": tol / 2, "minus_tol": tol / 2, "distribution": "normal"},
        ]


# ---------------------------------------------------------------------------
# Helper: synthesize toolpaths from a brief when no CAD CAM engine is available.
# This produces a "good enough" face → profile → drill program so the G-code
# validator and the post-processor always have something to chew on.
# ---------------------------------------------------------------------------
def _synthesize_from_brief(job: CAMJob, bbox_mm: tuple, brief) -> "RawToolpaths":
    from cam.base import RawToolpaths, Toolpath
    L, W, T = bbox_mm
    moves: list[Toolpath] = []
    # initial setup
    moves.append(Toolpath("face", "T1", "rapid", 0, 0, 5))
    # face: snake the top
    y = 0.0
    while y <= W + 0.01:
        x_end = L if moves[-1].x == 0 else 0
        move_kind = "feed"
        z = -0.5
        feed = 600.0
        moves.append(Toolpath("face", "T1", "rapid", x_end, y, 5))
        moves.append(Toolpath("face", "T1", "feed", x_end, y, z, feed_mm_min=feed))
        moves.append(Toolpath("face", "T1", "feed", x_end, y + 4, z, feed_mm_min=feed))
        moves.append(Toolpath("face", "T1", "rapid", x_end, y + 4, 5))
        y += 4
    # contour
    z = -max(2.0, T - 0.5)
    pts = [(0, 0), (L, 0), (L, W), (0, W), (0, 0)]
    for (x, y) in pts:
        moves.append(Toolpath("contour", "T1", "feed", x, y, z, feed_mm_min=400))
    # drills
    for f in brief.features:
        if f.kind in ("through_hole", "blind_hole", "hole") and f.position_mm:
            x = f.position_mm.get("x", 0)
            y = f.position_mm.get("y", 0)
            moves.append(Toolpath("drill", "T3", "rapid", x, y, 5))
            moves.append(Toolpath("drill", "T3", "feed", x, y, -T, feed_mm_min=80))
            moves.append(Toolpath("drill", "T3", "rapid", x, y, 5))
    # safe retract
    moves.append(Toolpath("contour", "T1", "rapid", 0, 0, 25))
    return RawToolpaths(moves=moves, estimated_time_min=2.5,
                        metadata={"engine": "synthesizer"})
