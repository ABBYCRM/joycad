"""JoyCAD Streamlit web UI — the user-facing front door of the MVP.

Run with:
    joycad demo
or:
    streamlit run orchestrator/web.py
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
from orchestrator.settings import Settings, get_preset, list_presets


st.set_page_config(
    page_title="JoyCAD — AI-driven CAD/CAM",
    page_icon="🛠️",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Session-state init
# ---------------------------------------------------------------------------
def _init_state():
    defaults = {
        "preset_name": "mvp-mock",
        "advanced_open": False,
        "last_run": None,                    # last PipelineResult.to_dict()
        "last_outputs_dir": "",
        "last_settings": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=300)
def _cached_run(settings_dict: dict, intent: str, api_keys: dict):
    """Run the pipeline with the given settings. Cached so re-renders are free.

    `api_keys` is a dict like {"openai": "sk-...", "anthropic": "sk-ant-..."}.
    Keys are injected into os.environ for this run only (not persisted).
    """
    s = Settings.from_request(settings_dict)
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td) / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        os.environ["JOYCAD_LLM_PROVIDER"] = s.llm_provider or "mock"
        # Inject per-session API keys into env for the duration of this run.
        # Empty strings are skipped; existing server-side env vars win only
        # when no session key was pasted for that provider.
        _PROVIDER_ENV_KEYS = {
            "openai":      "OPENAI_API_KEY",
            "anthropic":   "ANTHROPIC_API_KEY",
            "openrouter":  "OPENROUTER_API_KEY",
            "ollama_host": "OLLAMA_HOST",
            "vllm_base":   "VLLM_BASE_URL",
        }
        for k, env_key in _PROVIDER_ENV_KEYS.items():
            val = (api_keys or {}).get(k, "").strip()
            if val:
                os.environ[env_key] = val
        cfg = PipelineConfig(
            intent=intent,
            out_dir=out_dir,
            machine=s.machine,
            material=s.material,
            cad_engine=s.cad_engine,
            cam_backend=s.cam_backend,
            post_processor=s.post_processor,
            process=s.process,
            skip_validation=s.skip_validation,
            llm_provider=s.llm_provider,
            safe_z_mm=s.safe_z_mm,
            spindle_rpm=s.spindle_rpm,
            context=s.extra_context,
        )
        try:
            t0 = time.time()
            result = Pipeline(cfg).run()
            elapsed = time.time() - t0
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


@st.cache_data(show_spinner=False, ttl=600)
def _get_capabilities():
    """Live status of every dep JoyCAD might use, plus how to fix what's missing."""
    import platform, shutil
    import importlib.util as iu

    def has(name: str) -> bool:
        try: return iu.find_spec(name) is not None
        except Exception: return False

    try:
        from validation import collision_backend as _cb
        bknd = _cb()
    except Exception:
        bknd = "aabb"

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executables": {
            "freecadcmd":  shutil.which("freecadcmd"),
            "ccx":         shutil.which("ccx"),
            "prusa-slicer":shutil.which("prusa-slicer"),
            "ollama":      shutil.which("ollama"),
        },
        "modules": {
            "cadquery":      has("cadquery"),
            "sentence_transformers": has("sentence_transformers"),
            "fcl":           has("fcl"),
            "openai":        has("openai"),
            "anthropic":     has("anthropic"),
        },
        "collision_backend": bknd,
        "tool_status": {
            "freecadcmd": {
                "installed": bool(shutil.which("freecadcmd")),
                "install_cmd": "apt-get install -y freecad",
                "used_for": "FreeCAD CAM backend + FreeCAD CAD engine",
                "fallback": "CadQuery (default)",
            },
            "ccx": {
                "installed": bool(shutil.which("ccx")),
                "install_cmd": "apt-get install -y calculix-ccx",
                "used_for": "FEA stress simulation",
                "fallback": "FEA validator skipped",
            },
            "prusa-slicer": {
                "installed": bool(shutil.which("prusa-slicer")),
                "install_cmd": "download from prusa3d.com",
                "used_for": "advanced FDM slicer profiles",
                "fallback": "CadQuery CAM writes standard Marlin G-code",
            },
            "ollama": {
                "installed": bool(shutil.which("ollama")),
                "install_cmd": "curl -fsSL https://ollama.com/install.sh | sh && ollama pull llama3.1",
                "used_for": "local LLM, no API key",
                "fallback": "mock LLM or cloud providers",
            },
            "fcl": {
                "installed": has("fcl"),
                "install_cmd": "pip install python-fcl   # needs libfcl-dev; no wheel for Python 3.14",
                "used_for": "mesh-vs-mesh collision detection",
                "fallback": f"pure-Python AABB (active: {bknd})",
            },
        },
    }


# ---------------------------------------------------------------------------
# Sidebar — presets, basic settings, advanced settings, info
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ JoyCAD config")

    # --- presets ---
    st.subheader("Preset")
    preset_map = {p["name"]: p["label"] for p in list_presets()}
    chosen = st.selectbox(
        "Quick start",
        options=list(preset_map.keys()),
        format_func=lambda k: preset_map[k],
        index=list(preset_map.keys()).index(st.session_state.preset_name)
              if st.session_state.preset_name in preset_map else 0,
        help="Loading a preset fills the basic settings below.",
    )
    if chosen != st.session_state.preset_name:
        st.session_state.preset_name = chosen
        # when preset changes, re-seed the basic settings
        st.rerun()

    chosen_preset = get_preset(chosen) or Settings.default()
    for p in list_presets():
        if p["name"] == chosen:
            st.caption(p["description"])
            break

    st.divider()

    # --- basic settings (always visible) ---
    st.subheader("Basic")

    machine = st.selectbox(
        "Machine",
        options=["linuxcnc_3axis", "grbl_3018", "marlin_fdm"],
        index=["linuxcnc_3axis", "grbl_3018", "marlin_fdm"].index(chosen_preset.machine),
    )
    material = st.selectbox(
        "Material",
        options=["6061-T6", "1018", "316", "ABS", "PETG", "PLA"],
        index=["6061-T6", "1018", "316", "ABS", "PETG", "PLA"].index(chosen_preset.material),
    )
    process = st.selectbox(
        "Process",
        options=["cnc_mill", "cnc_lathe", "3d_print_fdm", "laser_cut",
                 "plasma_cut", "sheet_metal"],
        index=["cnc_mill", "cnc_lathe", "3d_print_fdm", "laser_cut",
               "plasma_cut", "sheet_metal"].index(chosen_preset.process),
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
        help="cadquery_cam needs no external CLI; freecad_path needs freecadcmd.",
    )
    llm_provider = st.selectbox(
        "LLM provider",
        options=["mock", "ollama", "openai", "anthropic", "openrouter", "vllm"],
        index=["mock", "ollama", "openai", "anthropic", "openrouter", "vllm"].index(chosen_preset.llm_provider),
        help="mock = deterministic, zero API key. ollama = local LLM. cloud = needs key.",
    )

    # --- advanced settings (collapsible) ---
    with st.expander("Advanced settings", expanded=st.session_state.advanced_open):
        safe_z_mm = st.slider("Safe Z (mm)", 1.0, 20.0, chosen_preset.safe_z_mm, 0.5)
        spindle_rpm = st.slider("Spindle RPM", 1000, 30000, chosen_preset.spindle_rpm, 500)
        coolant = st.selectbox("Coolant", options=["flood", "mist", "off"],
                               index=["flood", "mist", "off"].index(chosen_preset.coolant))
        stock_padding_mm = st.slider("Stock padding (mm)", 0.0, 10.0,
                                     chosen_preset.stock_padding_mm, 0.5)
        work_offset = st.text_input("Work offset", value=chosen_preset.work_offset)
        validators_enabled = st.multiselect(
            "Validators",
            options=["fea", "dfm", "collision", "tolerance"],
            default=chosen_preset.validators_enabled,
        )
        skip_validation = st.checkbox("Skip validation",
                                       value=chosen_preset.skip_validation)
        export_formats = st.multiselect(
            "Export formats",
            options=["step", "stl", "dxf", "svg", "gcode", "bom", "notes"],
            default=chosen_preset.export_formats,
        )
        log_level = st.selectbox("Log level",
                                 options=["DEBUG", "INFO", "WARNING", "ERROR"],
                                 index=1)
        extra_context = st.text_area(
            "Extra context (passed to LLM)",
            value="",
            placeholder="e.g. 'this is a prototype for an aerospace fixture, light load only'",
            height=80,
        )

    st.divider()

    # --- capabilities (live, per-host) ---
    with st.expander("Runtime capabilities", expanded=False):
        caps = _get_capabilities()
        st.write(f"**Python**: `{caps['python']}`")
        st.write(f"**Platform**: `{caps['platform'][:60]}`")
        st.write("**Executables on PATH:**")
        for k, v in caps["executables"].items():
            icon = "✅" if v else "❌"
            st.write(f"  {icon} `{k}`: `{v or 'not installed'}`")
        st.write("**Python modules:**")
        for k, v in caps["modules"].items():
            icon = "✅" if v else "❌"
            st.write(f"  {icon} `{k}`")

        # Tell the user what's missing AND how to fix it
        missing = [(k, t) for k, t in caps.get("tool_status", {}).items()
                   if not t.get("installed")]
        if missing:
            st.write("**🔧 How to install the missing tools:**")
            for k, t in missing:
                with st.container(border=True):
                    st.markdown(f"**{k}** — _{t['used_for']}_")
                    st.code(t["install_cmd"], language="bash")
                    st.caption(f"↩ fallback: {t['fallback']}")
        st.write(f"**Collision backend:** `{caps.get('collision_backend', '?')}`")

        if st.button("🔄 Refresh", key="refresh_caps"):
            _get_capabilities.clear()
            st.rerun()

    st.divider()

    # --- API keys (per-browser-session only; not persisted) ---
    with st.expander("🔑 API Keys", expanded=False):
        st.caption(
            "Pasted keys are kept in **this browser session only** (in-memory). "
            "They are sent to the server for the duration of a pipeline run "
            "and discarded after. They never touch the database or Render env vars."
        )
        st.session_state.openai_key = st.text_input(
            "OpenAI API Key", type="password",
            value=st.session_state.get("openai_key", ""),
            placeholder="sk-...",
            help="Used when llm_provider = openai or openai-cloud preset.")
        st.session_state.anthropic_key = st.text_input(
            "Anthropic API Key", type="password",
            value=st.session_state.get("anthropic_key", ""),
            placeholder="sk-ant-...",
            help="Used when llm_provider = anthropic.")
        st.session_state.openrouter_key = st.text_input(
            "OpenRouter API Key", type="password",
            value=st.session_state.get("openrouter_key", ""),
            placeholder="sk-or-...",
            help="Used when llm_provider = openrouter.")
        st.session_state.ollama_host = st.text_input(
            "Ollama host (advanced)",
            value=st.session_state.get("ollama_host", "http://localhost:11434"),
            help="Where Ollama is running. The default assumes local; on Render, "
                 "this would point to an external Ollama instance.")
        st.session_state.vllm_base = st.text_input(
            "vLLM base URL (advanced)",
            value=st.session_state.get("vllm_base", "http://localhost:8000/v1"),
            help="OpenAI-compatible endpoint of your vLLM server.")
        cols = st.columns(2)
        with cols[0]:
            if st.button("🗑️ Clear keys", use_container_width=True):
                for k in ("openai_key", "anthropic_key", "openrouter_key"):
                    st.session_state[k] = ""
                st.success("Cleared.")
                st.rerun()
        with cols[1]:
            st.caption(f"🔒 {sum(1 for k in ('openai_key','anthropic_key','openrouter_key') if st.session_state.get(k))} key(s) set")

    st.divider()
    st.caption("API endpoints: `/v1/info`, `/v1/settings`, `/v1/pipeline`, `/v1/presets`.")


# ---------------------------------------------------------------------------
# Main — intent box + run
# ---------------------------------------------------------------------------
st.title("🛠️ JoyCAD")
st.subheader("Natural language → STEP + STL + G-code + BOM + notes")

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

default_intent = intent or EXAMPLE_INTENTS[0]
intent_text = st.text_area(
    "Design intent",
    value=default_intent,
    height=80,
    help="Describe the part in plain English. Mention material, dimensions, holes.",
)

run = st.button("🚀 Build", type="primary", use_container_width=True)

# --- curl helper ---
with st.expander("Equivalent curl (local `joycad serve` only)", expanded=False):
    st.caption(
        "The live Render URL serves **only** the Streamlit UI. "
        "The `/v1/*` programmatic endpoints are exposed when you run "
        "`joycad serve` locally — paste that snippet into a terminal "
        "where joycad is installed."
    )
    settings_payload = {
        "preset": chosen,
        "intent": intent_text,
        "machine": machine, "material": material, "process": process,
        "cad_engine": cad_engine, "cam_backend": cam_backend,
        "llm_provider": llm_provider,
    }
    # only include Advanced fields if the user opened the expander at least once
    if st.session_state.advanced_open:
        settings_payload.update({
            "safe_z_mm": safe_z_mm, "spindle_rpm": spindle_rpm,
            "coolant": coolant, "stock_padding_mm": stock_padding_mm,
            "work_offset": work_offset,
            "validators_enabled": validators_enabled,
            "skip_validation": skip_validation,
            "export_formats": export_formats,
            "log_level": log_level, "extra_context": extra_context,
        })
    # Only include non-empty API keys in the curl payload
    api_keys_payload = {
        k: st.session_state.get(k, "")
        for k in ("openai_key", "anthropic_key", "openrouter_key",
                  "ollama_host", "vllm_base")
        if st.session_state.get(k, "").strip()
    }
    if api_keys_payload:
        settings_payload["api_keys"] = {
            "openai":      api_keys_payload.get("openai_key", ""),
            "anthropic":   api_keys_payload.get("anthropic_key", ""),
            "openrouter":  api_keys_payload.get("openrouter_key", ""),
            "ollama_host": api_keys_payload.get("ollama_host", ""),
            "vllm_base":   api_keys_payload.get("vllm_base", ""),
        }
    curl_cmd = (
        "curl -X POST http://localhost:8000/v1/pipeline \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        f"  -d '{json.dumps(settings_payload)}'"
    )
    st.code(curl_cmd, language="bash")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
if run and intent_text.strip():
    # Build the settings dict (full payload)
    settings_payload_full = {
        "preset": chosen,
        "intent": intent_text,
        "machine": machine, "material": material, "process": process,
        "cad_engine": cad_engine, "cam_backend": cam_backend,
        "llm_provider": llm_provider,
        "safe_z_mm": safe_z_mm, "spindle_rpm": spindle_rpm,
        "coolant": coolant, "stock_padding_mm": stock_padding_mm,
        "work_offset": work_offset,
        "validators_enabled": validators_enabled,
        "skip_validation": skip_validation,
        "export_formats": export_formats,
        "log_level": log_level, "extra_context": extra_context,
    }
    # Collect any API keys the user pasted in this session. They flow into
    # the pipeline runner only for this single run.
    api_keys = {
        "openai":      st.session_state.get("openai_key", ""),
        "anthropic":   st.session_state.get("anthropic_key", ""),
        "openrouter":  st.session_state.get("openrouter_key", ""),
        "ollama_host": st.session_state.get("ollama_host", ""),
        "vllm_base":   st.session_state.get("vllm_base", ""),
    }
    # Strip empty so we don't clobber server-side env vars unnecessarily.
    api_keys = {k: v for k, v in api_keys.items() if v.strip()}
    with st.spinner(f"Building with preset **{chosen}**…"):
        result = _cached_run(settings_payload_full, intent_text.strip(), api_keys)

    if not result["ok"]:
        st.error(f"Pipeline failed: {result.get('error', 'unknown')}")
        st.stop()

    out_dir = Path(result["outputs_dir"])
    st.session_state.last_run = result
    st.session_state.last_outputs_dir = str(out_dir)
    st.session_state.last_settings = settings_payload_full

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
        "🧊 3D preview", "📄 STEP / STL", "🔩 G-code",
        "📋 BOM", "📝 Mfg notes", "📊 Validation", "⚙ Settings used",
    ])

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
                height=520, scrolling=True)
        st.info("For true 3D: open the STL in **viewstl.com**, "
                "**Fusion 360**, **FreeCAD**, **PrusaSlicer**, or **Blender**.")

    with tabs[1]:
        for name, fname in [("STEP", "part.step"), ("STL", "part.stl"),
                            ("DXF", "part.dxf"), ("SVG", "part.svg")]:
            p = out_dir / fname
            if p.exists():
                st.download_button(
                    f"⬇ Download {name}", p.read_bytes(), file_name=fname,
                    mime={"STEP": "application/step", "STL": "model/stl",
                          "DXF": "image/vnd.dwg",
                          "SVG": "image/svg+xml"}[name])
        if (out_dir / "part.step").exists():
            with st.expander("STEP file header (first 30 lines)"):
                st.code("\n".join((out_dir / "part.step").read_text().splitlines()[:30]))

    with tabs[2]:
        gcode_path = out_dir / "part.gcode"
        if gcode_path.exists():
            st.download_button("⬇ Download G-code", gcode_path.read_bytes(),
                               file_name="part.gcode", mime="text/plain")
            with st.expander("G-code (full)", expanded=True):
                st.code(gcode_path.read_text(), language="gcode")
        else:
            st.warning("No G-code produced.")

    with tabs[3]:
        bom_csv = out_dir / "bom.csv"
        bom_json = out_dir / "bom.json"
        if bom_csv.exists():
            st.download_button("⬇ BOM CSV", bom_csv.read_bytes(),
                               file_name="bom.csv", mime="text/csv")
        if bom_json.exists():
            st.json(json.loads(bom_json.read_text()))

    with tabs[4]:
        notes_path = out_dir / "manufacturing_notes.md"
        if notes_path.exists():
            st.markdown(notes_path.read_text())

    with tabs[5]:
        result_path = out_dir / "pipeline_result.json"
        if result_path.exists():
            data = json.loads(result_path.read_text())
            for rep in data.get("validation_reports", []):
                st.write(f"**{rep['name']}**: `{rep['status']}`")
                if rep.get("metrics"):
                    st.json(rep["metrics"])
                for issue in rep.get("issues", []):
                    st.write(f"- *{issue['severity']}* — {issue['msg']}")

    with tabs[6]:
        st.json(settings_payload_full)
        st.download_button("⬇ Download settings JSON",
                           json.dumps(settings_payload_full, indent=2).encode(),
                           file_name="joycad_settings.json", mime="application/json")
