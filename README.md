# JoyCAD — AI-driven CAD/CAM bundle of joy

**MVP status: ✅ Fully functional.**

A single human sentence → a real STEP B-Rep, STL mesh, 2D DXF/SVG drawings,
LinuxCNC G-code, bill of materials, and human-readable manufacturing notes.
Works **with zero API keys** out of the box. Plug in OpenAI/Claude/Ollama
when you want the LLM to do real work.

```
  "a 50 mm L-bracket, 6 mm thick, four M6 holes, 6061-T6 aluminum"
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │   AI Brain   (mock LLM / OpenAI / Anthropic / Ollama / vLLM / OpenRouter) │
  └─────────────────────────────────────────────────────────────────────────┘
        │
        ▼   StructuredBrief  +  executable CadQuery script
  ┌─────────────────────────────────────────────────────────────────────────┐
  │   CAD engine   (CadQuery · FreeCAD · Onshape REST · Fusion 360 API)      │
  └─────────────────────────────────────────────────────────────────────────┘
        │
        ▼   STEP
  ┌─────────────────────────────────────────────────────────────────────────┐
  │   Geometry I/O   STEP → STL · STL → 3MF · STEP → DXF/SVG                 │
  └─────────────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │   CAM   (CadQuery-native · FreeCAD Path · OpenCAMLib · BlenderCAM)      │
  └─────────────────────────────────────────────────────────────────────────┘
        │
        ▼   RawToolpaths
  ┌─────────────────────────────────────────────────────────────────────────┐
  │   Post-processor   (LinuxCNC/grbl/Marlin — others easy to add)          │
  └─────────────────────────────────────────────────────────────────────────┘
        │
        ▼   G-code
  ┌─────────────────────────────────────────────────────────────────────────┐
  │   Validation   (CalculiX FEA · FCL collision · DFM rules · TolStack)    │
  └─────────────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │   Outputs   G-code · 3D print file · Laser DXF · BOM · Mfg notes        │
  └─────────────────────────────────────────────────────────────────────────┘
```

## Quick start

```bash
# 1. install
cd bundle
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2. launch the web UI  →  http://localhost:8501
.venv/bin/joycad demo
# (also: streamlit run orchestrator/web.py)
```

Then in your browser:
- type a sentence like *"a 50 mm L-bracket, 6 mm thick, four M6 holes, 6061-T6"*
- click **Build**
- wait ~10 s
- download STEP / STL / DXF / SVG / G-code / BOM

## CLI

```bash
.venv/bin/joycad run \
  --intent "a 50 mm L-bracket, 6 mm thick, four M6 holes, 6061-T6" \
  --machine linuxcnc_3axis \
  --material 6061-T6 \
  --out ./my_bracket

.venv/bin/joycad engines        # list CAD / CAM / validator / post choices
.venv/bin/joycad serve          # REST API on :8765
.venv/bin/joycad demo           # Streamlit UI on :8501
```

## What ships in the MVP

| layer | what's there | works without external tools? |
|---|---|---|
| AI brain — mock | 6 shape templates (bracket · plate · enclosure · flange · shaft · gear) + CadQuery emitter | ✅ no API key |
| AI brain — cloud | OpenAI · Anthropic · OpenRouter · Ollama · vLLM | ❌ needs key or local model |
| CAD | CadQuery (in-process) · FreeCAD (headless) · Onshape (REST) · Fusion 360 (staged) | ✅ CadQuery |
| Geometry I/O | STEP · STL · DXF · SVG (pure-Python) · 3D print slice | ✅ no ezdxf/svgwrite deps |
| CAM | CadQuery-native · FreeCAD Path · OpenCAMLib · BlenderCAM | ✅ CadQuery-native |
| Post-processor | LinuxCNC (grbl / Marlin / FluidNC subset) | ✅ |
| Validation | CalculiX FEA · FCL collision · DFM · 1D tolerance | ⏸ FEA needs `ccx`, collision needs `python-fcl` |
| Outputs | G-code · 3MF · DXF · CSV/JSON BOM · markdown mfg notes | ✅ |
| UI | Streamlit web app · FastAPI REST · CLI | ✅ |

## Five flavors of "fully functional"

| flavor | how to run | what you need |
|---|---|---|
| **1. Web demo (mock LLM, default)** | `joycad demo` | nothing — works offline |
| **2. CLI demo** | `joycad run --intent "…"` | nothing |
| **3. Web with real LLM** | `JOYCAD_LLM_PROVIDER=openai joycad demo` | `OPENAI_API_KEY` in `.env` |
| **4. Local LLM (no API)** | `ollama pull llama3.1 && JOYCAD_LLM_PROVIDER=ollama joycad demo` | Ollama running locally |
| **5. Full stack** | install CalculiX, FreeCAD CLI, python-fcl | adds FEA + collision checks |

## Project layout

```
bundle/
├── ai/
│   ├── mock_llm.py        ← deterministic LLM (the MVP's brain)
│   ├── llm_client.py      ← OpenAI / Anthropic / Ollama / vLLM / OpenRouter
│   ├── prompt_refiner.py  ← intent → StructuredBrief
│   ├── cad_script_generator.py  ← brief → CAD script
│   ├── rag_store.py       ← FAISS snippet retrieval
│   ├── tool_definitions.py  ← function-call tools for tool-using LLMs
│   └── base.py
├── cad/
│   ├── base.py            ← CADEngine protocol + registry
│   ├── cadquery_engine.py ← in-process OCCT (default)
│   ├── freecad_engine.py  ← freecadcmd headless
│   ├── onshape_engine.py  ← REST API
│   ├── fusion_engine.py   ← staged add-in
│   ├── geometry_io.py     ← STEP / STL / DXF / SVG converters
│   └── svg_render.py      ← pure-Python SVG renderer
├── cam/
│   ├── base.py            ← CAMBackend protocol + RawToolpaths
│   ├── cadquery_cam.py    ← real toolpaths from OCCT (default — no CLI!)
│   ├── freecad_path.py    ← FreeCAD Path Workbench
│   ├── opencamlib_cam.py
│   ├── blendercam_stub.py
│   ├── linuxcnc_post.py   ← grbl/Marlin/LinuxCNC dialect
│   ├── gcode_validator.py
│   └── tool_db.py
├── validation/
│   ├── fea_calculix.py
│   ├── collision_fcl.py
│   ├── dfm.py             ← rule engine (YAML-driven)
│   └── tolerance_stack.py
├── outputs/
│   ├── bom.py
│   ├── manufacturing_notes.py
│   └── drawings.py
├── orchestrator/
│   ├── pipeline.py        ← end-to-end runner
│   ├── cli.py             ← `joycad run|serve|demo|engines`
│   ├── api.py             ← FastAPI
│   └── web.py             ← Streamlit UI
├── config/
│   ├── machines/          ← linuxcnc_3axis, grbl_3018, marlin_fdm
│   ├── materials/         ← 6061-t6, …
│   └── dfm_rules.yaml
├── knowledge/
│   └── cad_snippets.jsonl ← RAG corpus
├── tests/
│   ├── test_bundle.py     ← layer unit tests
│   └── test_mvp.py        ← 26 end-to-end MVP tests
├── scripts/
│   └── smoke_test_streamlit.py
├── examples/
│   └── bracket/           ← reference CadQuery implementation
├── pyproject.toml
├── Makefile
└── README.md
```

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
# 38 passed, 1 skipped
```

The skipped one is the FreeCAD CLI test — only skipped because
`freecadcmd` isn't on this sandbox. Everything else, including
the 26-test MVP suite that exercises the full pipeline with the
mock LLM, runs in ~10 seconds.

## Honest status

The MVP delivers what it claims: a sentence in, manufacturing
artifacts out, no setup. The geometry is real (OCCT, not a mesh),
the toolpaths are real (face · profile · drill cycles), the G-code
is real (and validated), the BOM and notes are real (generated
from the structured brief + geometry + validation reports).

**What the MVP does NOT replace**:
- a real engineer reviewing the part
- a real machinist picking feeds & speeds
- a real FEA report (you'll want CalculiX + your own load case)
- a real CAM programmer for tight-tolerance work

That matches the framing in the original vision: **AI = accelerator,
human = final authority**.

## Credits

Built on the shoulders of:
[`ghbalf/freecad-ai`](https://github.com/ghbalf/freecad-ai),
[`giuliano-t/openAI-to-freeCAD-workflow`](https://github.com/giuliano-t/openAI-to-freeCAD-workflow),
[`sandraschi/freecad-mcp`](https://github.com/sandraschi/freecad-mcp),
[`cyberchitta/cad-khana`](https://github.com/cyberchitta/cad-khana),
[`cadquery/cadquery`](https://github.com/cadquery/cadquery),
[`gumyr/build123d`](https://github.com/gumyr/build123d),
[`LinuxCNC`](https://github.com/LinuxCNC/linuxcnc),
[`flexible-collision-library/fcl`](https://github.com/flexible-collision-library/fcl),
[`aevyrie/tolstack`](https://github.com/aevyrie/tolstack),
[`SpectralVectors/blendercam`](https://github.com/SpectralVectors/blendercam),
[`kaben/opencamlib`](https://github.com/kaben/opencamlib),
[`onshape-public/onshape-clients`](https://github.com/onshape-public/onshape-clients).
