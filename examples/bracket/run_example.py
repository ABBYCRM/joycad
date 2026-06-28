"""Run the JoyCAD pipeline on the bracket example — without an LLM.

Uses the reference CadQuery script as the CAD output so you can see the
full pipeline run and inspect every artifact.

With an LLM API key set, replace `_run_no_llm()` with `_run_with_llm()`.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.pipeline import Pipeline, PipelineConfig
from ai.prompt_refiner import StructuredBrief, FeatureSpec
from ai import llm_factory


def _populate_brief_no_llm() -> StructuredBrief:
    """Hand-built brief for the bracket example (no LLM)."""
    return StructuredBrief(
        name="bracket-001",
        part_type="bracket",
        description=("L-bracket for small motor mount. Vertical face 50mm "
                     "x 50mm x 6mm, horizontal face 50mm x 30mm x 6mm, four "
                     "M6 mounting holes (two on each face)."),
        material="6061-T6",
        process="cnc_mill",
        bbox_mm={"length": 50, "width": 30, "thickness": 6},
        thickness_mm=6.0,
        features=[
            FeatureSpec(kind="through_hole", role="mounting",
                        quantity=2, diameter_mm=6.6,
                        position_mm={"x": 10, "y": 15},
                        standard="M6 clearance"),
            FeatureSpec(kind="through_hole", role="mounting",
                        quantity=2, diameter_mm=6.6,
                        position_mm={"x": 40, "y": 15},
                        standard="M6 clearance"),
            FeatureSpec(kind="through_hole", role="mounting",
                        quantity=2, diameter_mm=6.6,
                        position_mm={"x": 10, "y": 10},
                        standard="M6 clearance"),
            FeatureSpec(kind="through_hole", role="mounting",
                        quantity=2, diameter_mm=6.6,
                        position_mm={"x": 40, "y": 10},
                        standard="M6 clearance"),
        ],
        tolerances_mm={"linear": 0.1, "hole": 0.1},
        surface_finish_um_ra=1.6,
        quantity=1,
        finish="as-machined",
        cosmetic=False,
    )


def run_no_llm(out_dir: Path):
    """Run the full pipeline using a hand-built brief + reference script."""
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = PipelineConfig(
        intent="L-bracket for motor mount",
        out_dir=out_dir,
        machine="linuxcnc_3axis",
        material="6061-T6",
        cad_engine="cadquery",
        cam_backend="freecad_path",        # falls back to synthesizer if no FreeCAD
        post_processor="linuxcnc",
        process="cnc_mill",
        skip_validation=False,
    )
    pipe = Pipeline(cfg)

    # Override LLM steps with hand-built brief + reference script.
    pipe.result.brief = _populate_brief_no_llm()
    (out_dir / "brief.json").write_text(json.dumps(pipe.result.brief.to_dict(), indent=2))

    ref_script = Path(__file__).parent / "reference_cadquery.py"
    script_path = out_dir / "part.cadquery.py"
    shutil.copy(ref_script, script_path)
    pipe.result.script_path = script_path

    # Now run the downstream steps (CAD → CAM → post → outputs)
    pipe._step_execute_cad()
    pipe._step_convert_geometry()
    pipe._step_run_cam()
    pipe._step_post_process()
    pipe._step_validate_gcode()
    pipe._step_validate()
    pipe._step_outputs()
    pipe.result.ok = True
    return pipe.result


def run_with_llm(out_dir: Path):
    """Full LLM-driven run — needs an API key in env."""
    intent_path = Path(__file__).parent / "intent.json"
    data = json.loads(intent_path.read_text())
    cfg = PipelineConfig(
        intent=data["intent"],
        out_dir=out_dir,
        machine=data.get("machine", "linuxcnc_3axis"),
        material=data.get("material", "6061-T6"),
        cad_engine=data.get("cad_engine", "cadquery"),
        cam_backend="freecad_path",
        post_processor="linuxcnc",
        process="cnc_mill",
        context=data.get("context", ""),
    )
    return Pipeline(cfg).run()


def main():
    out_dir = Path(__file__).parent / "outputs"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    if (os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_API_KEY") != "sk-no-key") \
       or os.getenv("ANTHROPIC_API_KEY"):
        result = run_with_llm(out_dir)
    else:
        print("no LLM key set; running reference example without LLM…")
        result = run_no_llm(out_dir)

    print()
    print("=" * 72)
    print(f"JoyCAD bracket example — OK: {result.ok}")
    print("=" * 72)
    for s in result.steps:
        elapsed = s.finished_at - s.started_at if s.finished_at else 0
        print(f"  {s.name:<22s}  {s.status:<6s}  {elapsed:5.2f}s")
    print()
    print("Artifacts:")
    for f in sorted(out_dir.iterdir()):
        size = f.stat().st_size
        print(f"  {size:>8d}  {f.relative_to(out_dir)}")


if __name__ == "__main__":
    main()
