"""JoyCAD tests — quick smoke tests of every layer.

Run:
    pytest -q
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# allow tests to import the bundle modules regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# AI layer
# ---------------------------------------------------------------------------
def test_llm_factory_unknown_provider():
    from ai.llm_client import llm_factory
    with pytest.raises(ValueError):
        llm_factory("not-a-real-provider")


def test_tool_registry_has_core_tools():
    from ai.tool_definitions import ToolRegistry
    reg = ToolRegistry()
    names = {t.name for t in reg.list()}
    for must in ("refine_design_intent", "generate_cad_script",
                 "run_cam", "post_process_gcode", "check_dfm"):
        assert must in names, f"missing tool {must}"


def test_rag_store_seeds():
    from ai.rag_store import seed_default_corpus
    store = seed_default_corpus()
    snippets = store.query("L-bracket", k=3, engine="cadquery")
    assert isinstance(snippets, list)
    assert all(isinstance(s, str) for s in snippets)


def test_prompt_refiner_template_fallback():
    """If the LLM provider is unknown (no key, no mock), refiner must raise."""
    import os
    os.environ["JOYCAD_LLM_PROVIDER"] = "definitely-not-a-provider"
    try:
        with pytest.raises(Exception):
            from ai.prompt_refiner import PromptRefiner
            PromptRefiner()
    finally:
        os.environ.pop("JOYCAD_LLM_PROVIDER", None)


# ---------------------------------------------------------------------------
# CAM layer
# ---------------------------------------------------------------------------
def test_tool_db_default():
    from cam.tool_db import default_tool_db
    db = default_tool_db()
    assert any(t.id == "T1" for t in db.tools)
    assert any(t.id == "T3" for t in db.tools)


def test_gcode_validator_handles_minimal_file():
    from cam.gcode_validator import GCodeValidator
    g = Path(tempfile.mktemp(suffix=".gcode"))
    g.write_text("""
G21 G90
G0 X0 Y0 Z5
G1 X10 Y0 Z-1 F500
G2 X20 Y0 Z-1 I5 J0 F300
M5
M2
""")
    rep = GCodeValidator().validate(g)
    assert rep.line_count > 0
    assert rep.has_tool_changes is False
    assert rep.status in ("pass", "warn")


def test_linuxcnc_post_emits_known_opener():
    from cam.linuxcnc_post import LinuxCNCPost
    from cam.base import RawToolpaths, Toolpath
    raw = RawToolpaths(moves=[
        Toolpath("face", "T1", "rapid", 0, 0, 5),
        Toolpath("face", "T1", "feed", 10, 0, -1, feed_mm_min=500),
    ])
    out = Path(tempfile.mktemp(suffix=".ngc"))
    LinuxCNCPost().post(raw, out, {"coolant": "flood"})
    text = out.read_text()
    assert "G21 G90" in text
    assert "M8" in text            # flood coolant
    assert "T1 M6" in text
    assert "M2" in text


# ---------------------------------------------------------------------------
# Validation layer
# ---------------------------------------------------------------------------
def test_tolerance_validator_pass():
    from validation.tolerance_stack import ToleranceValidator
    v = ToleranceValidator()
    rep = v.validate(stack=[
        {"name": "a", "nominal": 10, "plus_tol": 0.1, "minus_tol": 0.1},
        {"name": "b", "nominal": 20, "plus_tol": 0.1, "minus_tol": 0.1},
    ], target_tolerance_mm=1.0)
    assert rep.status == "pass"
    assert rep.metrics["worst_case_mm"] == pytest.approx(0.4)


def test_tolerance_validator_fail():
    from validation.tolerance_stack import ToleranceValidator
    v = ToleranceValidator()
    rep = v.validate(stack=[
        {"name": "a", "nominal": 10, "plus_tol": 0.5, "minus_tol": 0.5},
        {"name": "b", "nominal": 20, "plus_tol": 0.5, "minus_tol": 0.5},
    ], target_tolerance_mm=1.0)
    assert rep.status == "fail"


def test_dfm_rules_load():
    from validation.dfm import DFMRules
    rules = DFMRules()
    assert rules.min_wall_thickness_mm > 0


# ---------------------------------------------------------------------------
# Outputs layer
# ---------------------------------------------------------------------------
def test_bom_extract_with_brief():
    from outputs.bom import extract_bom
    from ai.prompt_refiner import StructuredBrief, FeatureSpec
    brief = StructuredBrief(
        name="bracket-001",
        part_type="bracket",
        description="L-bracket",
        material="6061-T6",
        bbox_mm={"length": 50, "width": 30, "thickness": 6},
        features=[],
    )
    bom = extract_bom(Path("/tmp/fake.step"), brief=brief)
    assert bom.items[0].material == "6061-T6"
    assert "53.0 x 33.0 x 9.0" in bom.items[0].stock_size_mm


def test_mfg_notes_template_fallback():
    from outputs.manufacturing_notes import generate_manufacturing_notes
    from ai.prompt_refiner import StructuredBrief
    brief = StructuredBrief(name="bracket-001", part_type="bracket",
                            description="L-bracket", material="6061-T6",
                            bbox_mm={"length": 50, "width": 30, "thickness": 6})
    notes = generate_manufacturing_notes(brief=brief, reports=[])
    assert "Manufacturing Notes" in notes.markdown


# ---------------------------------------------------------------------------
# Orchestrator (with a stubbed CAD engine so no LLM/key is needed)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not shutil.which("freecadcmd"),
                       reason="FreeCAD not installed")
def test_orchestrator_synthetic_path(tmp_path):
    """Run the pipeline end-to-end with no LLM, using a pre-baked brief + script."""
    import shutil
    from orchestrator.pipeline import Pipeline, PipelineConfig
    from ai.prompt_refiner import StructuredBrief, FeatureSpec

    out_dir = tmp_path / "out"
    cfg = PipelineConfig(
        intent="L-bracket test", out_dir=out_dir,
        cad_engine="cadquery", cam_backend="freecad_path",
        post_processor="linuxcnc", process="cnc_mill",
        skip_validation=True,
    )
    # Manually populate the pipeline state to skip LLM-dependent steps.
    pipe = Pipeline(cfg)
    pipe.result.brief = StructuredBrief(
        name="bracket", part_type="bracket", description="test",
        material="6061-T6", bbox_mm={"length": 50, "width": 30, "thickness": 6},
        features=[
            FeatureSpec(kind="through_hole", diameter_mm=6.6,
                        position_mm={"x": 10, "y": 15}),
            FeatureSpec(kind="through_hole", diameter_mm=6.6,
                        position_mm={"x": 40, "y": 15}),
        ],
    )
    # Copy in the reference CadQuery script
    ref = Path(__file__).resolve().parent.parent / "examples" / "bracket" / \
        "reference_cadquery.py"
    script_path = out_dir / "part.cadquery.py"
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ref, script_path)
    pipe.result.script_path = script_path

    # run only from CAD-onwards
    from cad import get_engine
    pipe.result.geometry = get_engine("cadquery").execute(script_path, out_dir)
    pipe._step_convert_geometry()
    pipe._step_run_cam()
    pipe._step_post_process()
    pipe._step_validate_gcode()
    pipe._step_outputs()

    assert (out_dir / "part.step").exists()
    assert (out_dir / "part.gcode").exists()
    assert (out_dir / "bom.csv").exists()
    assert (out_dir / "manufacturing_notes.md").exists()
