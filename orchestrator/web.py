"""JoyCAD Streamlit web UI — the user-facing front door of the MVP.

Run with:
    joycad demo
or:
    streamlit run orchestrator/web.py

What it does:
    1. Big text box for the design intent.
    2. Sidebar for machine + material + LLM provider.
    3. One button: ``Build``.
    4. After build: tabs for 3D preview, STEP/STL download, G-code, BOM, notes.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st

# Make the bundle importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.pipeline import Pipeline, PipelineConfig


st.set_page_config(
    page_title="JoyCAD — AI-driven CAD/CAM",
    page_icon="🛠️",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Sidebar — config
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ JoyCAD config")

    llm_provider = st.selectbox(
        "LLM provider",
        options=["mock", "ollama", "openai", "anthropic", "openrouter", "vllm"],
        index=0,
        help="mock = no API key, deterministic. ollama = local LLM. "
             "openai/anthropic/openrouter = cloud.",
    )

    cad_engine = st.selectbox(
        "CAD engine",
        options=["cadquery", "freecad", "onshape", "fusion"],
        index=0,
    )

    cam_backend = st.selectbox(
        "CAM backend",
        options=["cadquery_cam", "freecad_path", "opencamlib", "blendercam"],
        index=0,
        help="cadquery_cam = no external CLI needed",
    )

    machine = st.selectbox(
        "Machine",
        options=["linuxcnc_3axis", "grbl_3018", "marlin_fdm"],
        index=0,
    )

    material = st.selectbox(
        "Material",
        options=["6061-T6", "1018", "316", "ABS", "PETG", "PLA"],
        index=0,
    )

    process = st.selectbox(
        "Process",
        options=["cnc_mill", "cnc_lathe", "3d_print_fdm", "laser_cut",
                 "plasma_cut", "sheet_metal"],
        index=0,
    )

    skip_validation = st.checkbox("Skip validation", value=False)
    st.divider()
    st.caption("Tip: leave LLM = mock to demo without any API key.")


# ---------------------------------------------------------------------------
# Main — intent box + run
# ---------------------------------------------------------------------------
st.title("🛠️ JoyCAD")
st.subheader("Natural language → STEP + STL + G-code + BOM")

EXAMPLE_INTENTS = [
    "a 50 mm L-bracket, 6 mm thick, four M6 clearance holes, 6061-T6 aluminum",
    "an 80 x 40 x 6 mm flat plate with four M6 corner holes, 1018 steel",
    "a 100 x 60 x 20 mm enclosure with 3 mm walls and an open pocket, ABS, 3D print",
    "a 80 mm diameter flange, 10 mm thick, central 26 mm bore, six M6 holes on a bolt circle, 6061-T6",
    "a 10 mm diameter shaft, 80 mm long, with a 5 mm keyway, 1018 steel",
    "a 40 mm diameter spur gear, 6 mm thick, 5 mm bore, 6061-T6",
]

st.write("**Examples** (click to load):")
cols = st.columns(len(EXAMPLE_INTENTS))
intent: str = ""
for i, ex in enumerate(EXAMPLE_INTENTS):
    if cols[i].button(ex[:30] + ("…" if len(ex) > 30 else ""), key=f"ex{i}",
                       help=ex):
        intent = ex

default = intent or EXAMPLE_INTENTS[0]
intent_text = st.text_area(
    "Design intent",
    value=default,
    height=80,
    help="Describe the part in plain English. Mention material, dimensions, holes.",
)

run = st.button("🚀 Build", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Pipeline runner (cached so re-renders don't re-run)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _cached_run(intent: str, llm_provider: str, cad_engine: str,
                cam_backend: str, machine: str, material: str,
                process: str, skip_validation: bool):
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td) / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        os.environ["JOYCAD_LLM_PROVIDER"] = llm_provider
        cfg = PipelineConfig(
            intent=intent,
            out_dir=out_dir,
            machine=machine,
            material=material,
            cad_engine=cad_engine,
            cam_backend=cam_backend,
            post_processor="linuxcnc",
            process=process,
            skip_validation=skip_validation,
            llm_provider=llm_provider,
        )
        try:
            t0 = time.time()
            result = Pipeline(cfg).run()
            elapsed = time.time() - t0
            # copy outputs to a stable location so we can serve them via streamlit
            stable = Path(tempfile.gettempdir()) / "joycad_last"
            stable.mkdir(exist_ok=True)
            for f in out_dir.iterdir():
                (stable / f.name).write_bytes(f.read_bytes())
            return {
                "ok": result.ok,
                "error": result.error,
                "steps": [
                    {"name": s.name, "status": s.status,
                     "elapsed": round(s.finished_at - s.started_at, 2),
                     "details": s.details}
                    for s in result.steps if s.finished_at
                ],
                "outputs_dir": str(stable),
                "elapsed_total": round(elapsed, 1),
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "steps": [],
                    "outputs_dir": "", "elapsed_total": 0}


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
if run and intent_text.strip():
    with st.spinner("Building…"):
        result = _cached_run(
            intent_text.strip(),
            llm_provider, cad_engine, cam_backend, machine, material,
            process, skip_validation,
        )

    if not result["ok"]:
        st.error(f"Pipeline failed: {result.get('error', 'unknown')}")
        st.stop()

    out_dir = Path(result["outputs_dir"])

    st.success(
        f"✓ Done in {result['elapsed_total']}s — "
        f"{sum(1 for s in result['steps'] if s['status'] == 'ok')} of "
        f"{len(result['steps'])} steps OK"
    )

    # ---- step timeline ----
    with st.expander("Pipeline trace", expanded=False):
        for s in result["steps"]:
            colour = {"ok": "🟢", "pass": "🟢", "warn": "🟡",
                      "fail": "🔴", "skipped": "⚪",
                      "error": "🔴"}.get(s["status"], "·")
            detail = ", ".join(f"{k}={v}" for k, v in s["details"].items())
            if len(detail) > 80:
                detail = detail[:77] + "…"
            st.write(
                f"{colour} **{s['name']}** `{s['status']}` "
                f"· {s['elapsed']}s  · {detail}"
            )

    # ---- artifact tabs ----
    tabs = st.tabs([
        "🧊 3D preview",
        "📄 STEP / STL",
        "🔩 G-code",
        "📋 BOM",
        "📝 Mfg notes",
        "📊 Validation",
    ])

    # --- 3D preview (STL via stl-mesh-viewer or fall back to download) ---
    with tabs[0]:
        stl_path = out_dir / "part.stl"
        step_path = out_dir / "part.step"
        svg_path = out_dir / "part.svg"
        if stl_path.exists():
            st.download_button("⬇ Download STL", stl_path.read_bytes(),
                               file_name="part.stl", mime="model/stl")
        if svg_path.exists():
            st.markdown("**Top-down SVG projection:**")
            st.components.v1.html(
                f'<div style="background:white;border:1px solid #ddd;'
                f'padding:1rem;border-radius:8px">'
                f'{svg_path.read_text()}</div>',
                height=520,
                scrolling=True,
            )
        st.info(
            "For a true interactive 3D viewer, open the STL in:\n"
            "* **online**: [viewstl.com](https://www.viewstl.com/)\n"
            "* **desktop**: Fusion 360, FreeCAD, BambuStudio, PrusaSlicer, "
            "Blender\n"
            "* **command line**: `openscad part.stl`"
        )

    # --- STEP/STL ---
    with tabs[1]:
        for name, fname in [("STEP", "part.step"), ("STL", "part.stl"),
                            ("DXF", "part.dxf"), ("SVG", "part.svg")]:
            p = out_dir / fname
            if p.exists():
                st.download_button(
                    f"⬇ Download {name}",
                    p.read_bytes(),
                    file_name=fname,
                    mime={"STEP": "application/step",
                          "STL": "model/stl",
                          "DXF": "image/vnd.dwg",
                          "SVG": "image/svg+xml"}[name],
                )
        if step_path.exists():
            with st.expander("STEP file header (first 30 lines)"):
                st.code("\n".join(step_path.read_text().splitlines()[:30]))

    # --- G-code ---
    with tabs[2]:
        gcode_path = out_dir / "part.gcode"
        if gcode_path.exists():
            st.download_button("⬇ Download G-code", gcode_path.read_bytes(),
                               file_name="part.gcode", mime="text/plain")
            with st.expander("G-code (full)", expanded=True):
                st.code(gcode_path.read_text(), language="gcode")
        else:
            st.warning("No G-code produced.")

    # --- BOM ---
    with tabs[3]:
        bom_csv = out_dir / "bom.csv"
        bom_json = out_dir / "bom.json"
        if bom_csv.exists():
            st.download_button("⬇ BOM CSV", bom_csv.read_bytes(),
                               file_name="bom.csv", mime="text/csv")
        if bom_json.exists():
            st.json(json.loads(bom_json.read_text()))

    # --- Mfg notes ---
    with tabs[4]:
        notes_path = out_dir / "manufacturing_notes.md"
        if notes_path.exists():
            st.markdown(notes_path.read_text())

    # --- Validation ---
    with tabs[5]:
        result_path = out_dir / "pipeline_result.json"
        if result_path.exists():
            data = json.loads(result_path.read_text())
            for rep in data.get("validation_reports", []):
                st.write(f"**{rep['name']}**: `{rep['status']}`")
                if rep.get("metrics"):
                    st.json(rep["metrics"])
                for issue in rep.get("issues", []):
                    st.write(
                        f"- *{issue['severity']}* — {issue['msg']}"
                    )
