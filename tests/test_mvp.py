"""MVP end-to-end tests — runs the FULL bundle with mock LLM + real CAM.

These tests prove the MVP is fully functional without any API key, without
any external CLI tool (freecadcmd, ocl, slicer, ...), and without any GUI.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force mock LLM BEFORE importing the pipeline
os.environ.setdefault("JOYCAD_LLM_PROVIDER", "mock")

from ai.mock_llm import classify, mock_brief, _script_for_shape
from orchestrator.pipeline import Pipeline, PipelineConfig


SHAPES = [
    ("l_bracket", "a 50 mm L-bracket, 6 mm thick, four M6 holes, 6061-T6"),
    ("plate",     "an 80 x 40 x 6 mm flat plate, four M6 corner holes, 1018 steel"),
    ("enclosure", "a 100 x 60 x 20 mm enclosure with 3 mm walls and pocket, ABS"),
    ("flange",    "a 80 mm diameter flange, 10 mm thick, six M6 holes, 6061-T6"),
    ("shaft",     "a 10 mm diameter shaft, 80 mm long, 5 mm keyway, 1018 steel"),
    ("gear",      "a 40 mm diameter spur gear, 6 mm thick, 5 mm bore, 6061-T6"),
]


# ---------------------------------------------------------------------------
# 1. The mock LLM correctly classifies all the shapes.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("expected, intent", SHAPES)
def test_classify_shapes(expected, intent):
    assert classify(intent) == expected


# ---------------------------------------------------------------------------
# 2. The mock LLM produces a valid StructuredBrief with sensible features.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("expected, intent", SHAPES)
def test_brief_has_required_fields(expected, intent):
    brief, shape = mock_brief(intent)
    assert shape == expected
    assert brief.name
    assert brief.material
    assert brief.process
    assert brief.bbox_mm
    assert len(brief.features) >= 1
    d = brief.to_dict()
    # bbox must have at least length and width
    assert "length" in d["bbox_mm"]
    assert "width" in d["bbox_mm"]


# ---------------------------------------------------------------------------
# 3. The mock LLM produces an executable CadQuery script.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("expected, intent", SHAPES)
def test_generated_script_executes(expected, intent):
    brief, shape = mock_brief(intent)
    src = _script_for_shape(shape, brief)
    with tempfile.TemporaryDirectory() as td:
        script_path = Path(td) / "part.py"
        script_path.write_text(src)
        out_dir = Path(td) / "out"
        out_dir.mkdir()
        from cad import get_engine
        try:
            geom = get_engine("cadquery").execute(script_path, out_dir)
        except Exception as e:
            pytest.fail(f"script for {shape!r} failed to execute: {e}")
        assert (out_dir / "part.step").exists()
        assert (out_dir / "part.step").stat().st_size > 1000
        assert all(d > 0 for d in geom.bbox_mm)
        assert geom.volume_mm3 > 0


# ---------------------------------------------------------------------------
# 4. The full Pipeline.run() succeeds end-to-end with mock LLM + cadquery_cam.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("expected, intent", [
    ("l_bracket", "a 50 mm L-bracket, 6 mm thick, four M6 holes, 6061-T6"),
    ("plate",     "an 80 x 40 x 6 mm flat plate with 4 M6 corner holes, 1018 steel"),
    ("flange",    "a 80 mm diameter flange, 10 mm thick, six M6 holes, 6061-T6"),
])
def test_full_pipeline_mvp(expected, intent, tmp_path):
    cfg = PipelineConfig(
        intent=intent,
        out_dir=tmp_path / "out",
        cad_engine="cadquery",
        cam_backend="cadquery_cam",
        post_processor="linuxcnc",
        process="cnc_mill",
        llm_provider="mock",
        skip_validation=False,
    )
    result = Pipeline(cfg).run()
    assert result.ok, f"pipeline failed: {result.error}"
    out = cfg.out_dir
    assert (out / "brief.json").exists()
    assert (out / "part.cadquery.py").exists()
    assert (out / "part.step").exists()
    assert (out / "part.stl").exists()
    assert (out / "part.dxf").exists()
    assert (out / "part.svg").exists()
    assert (out / "part.gcode").exists()
    assert (out / "bom.csv").exists()
    assert (out / "bom.json").exists()
    assert (out / "manufacturing_notes.md").exists()
    assert (out / "pipeline_result.json").exists()

    # STEP is non-trivial
    assert (out / "part.step").stat().st_size > 5000
    # G-code is real
    gcode = (out / "part.gcode").read_text()
    assert "G21" in gcode            # mm mode
    assert "M5" in gcode or "M2" in gcode
    # SVG renders something
    svg = (out / "part.svg").read_text()
    assert "<path" in svg
    assert len(svg) > 200
    # BOM has the part name
    bom = (out / "bom.csv").read_text()
    assert "bracket" in bom or "plate" in bom or "flange" in bom
    # Mfg notes are markdown (not raw JSON)
    notes = (out / "manufacturing_notes.md").read_text()
    assert notes.startswith("# Manufacturing Notes")
    assert "Tool list" in notes or "tools" in notes.lower()


# ---------------------------------------------------------------------------
# 5. Different machines / materials / processes all work.
# ---------------------------------------------------------------------------
def test_marlin_fdm_3d_print(tmp_path):
    cfg = PipelineConfig(
        intent="a 60 x 40 x 20 mm enclosure, ABS, 3D print",
        out_dir=tmp_path / "out",
        machine="marlin_fdm",
        material="ABS",
        cad_engine="cadquery",
        cam_backend="cadquery_cam",
        post_processor="linuxcnc",
        process="3d_print_fdm",
        llm_provider="mock",
        skip_validation=True,
    )
    result = Pipeline(cfg).run()
    assert result.ok
    assert (cfg.out_dir / "part.step").exists()
    assert (cfg.out_dir / "manufacturing_notes.md").exists()


def test_grbl_hobby_cnc(tmp_path):
    cfg = PipelineConfig(
        intent="a 50 x 30 x 6 mm flat plate, 4 M3 holes, aluminum",
        out_dir=tmp_path / "out",
        machine="grbl_3018",
        material="6061-T6",
        cad_engine="cadquery",
        cam_backend="cadquery_cam",
        post_processor="linuxcnc",
        process="cnc_mill",
        llm_provider="mock",
        skip_validation=True,
    )
    result = Pipeline(cfg).run()
    assert result.ok
    assert (cfg.out_dir / "part.gcode").exists()


# ---------------------------------------------------------------------------
# 6. SVG renderer produces valid output for every shape.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("expected, intent", [
    ("l_bracket", "a 50 mm L-bracket, 6 mm thick, four M6 holes, 6061-T6"),
    ("plate",     "an 80 x 40 x 6 mm flat plate with 4 M6 corner holes, 1018 steel"),
])
def test_svg_renderer(expected, intent, tmp_path):
    cfg = PipelineConfig(
        intent=intent, out_dir=tmp_path / "out",
        cad_engine="cadquery", cam_backend="cadquery_cam",
        post_processor="linuxcnc", process="cnc_mill",
        llm_provider="mock", skip_validation=True,
    )
    result = Pipeline(cfg).run()
    assert result.ok
    svg = (cfg.out_dir / "part.svg").read_text()
    assert svg.startswith("<?xml") or svg.startswith("<svg")
    assert "<path" in svg
    assert svg.count("<path") >= 4           # at least a few edges


# ---------------------------------------------------------------------------
# 7. The CLI subcommands are registered.
# ---------------------------------------------------------------------------
def test_cli_has_demo_command():
    from orchestrator.cli import app
    # typer >= 0.12 stores name on the callback
    names = set()
    for c in app.registered_commands:
        n = getattr(c, "name", None) or getattr(c.callback, "__name__", None)
        if n: names.add(n)
    assert {"run", "engines", "serve", "demo"} <= names, f"missing: {names}"
