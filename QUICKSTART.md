# JoyCAD — Quickstart

Three ways to use the bundle.

## 1. CLI (one-shot)

```bash
cd bundle
pip install -e ".[dev]"          # or use the venv: .venv/bin/python
cp .env.example .env             # add your OPENAI_API_KEY

# full pipeline from intent to G-code
joycad run \
  --intent "a 50 mm L-bracket, 6 mm thick, two M6 holes per face, 6061-T6" \
  --machine linuxcnc_3axis \
  --material 6061-T6 \
  --out ./examples/bracket/out

# or, with no API key, run the reference example
make example
```

The `--out` directory gets:
- `brief.json`               — structured design brief
- `part.cadquery.py`         — generated (or reference) CAD script
- `part.step`                — STEP B-Rep
- `part.stl`                 — STL mesh (for 3D printing)
- `part.dxf`                 — 2D DXF (for laser/plasma)
- `part.svg`                 — 2D SVG preview
- `toolpaths.json`           — neutral toolpath moves
- `part.gcode`               — LinuxCNC G-code
- `gcode_validation.json`    — validator report
- `bom.csv` / `bom.json`     — bill of materials
- `manufacturing_notes.md`   — setup / tools / feeds / risks
- `pipeline_result.json`     — full pipeline trace
- `fea/`                     — FEA artifacts (when ccx is on PATH)
- `part.print.gcode`         — sliced G-code (when process=3d_print_*)

## 2. REST API

```bash
joycad serve --host 127.0.0.1 --port 8765
```

Then in another shell:

```bash
curl -X POST http://127.0.0.1:8765/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "intent": "a 100x60x20 mm enclosure, 4 corner M3 bosses, 1mm walls, 3D print in PETG",
    "machine": "marlin_fdm",
    "process": "3d_print_fdm"
  }'
```

## 3. Programmatic

```python
from orchestrator.pipeline import Pipeline, PipelineConfig

result = Pipeline(PipelineConfig(
    intent="a 50 mm L-bracket, 6 mm thick, two M6 holes per face",
    out_dir="./out",
    machine="linuxcnc_3axis",
    material="6061-T6",
)).run()

print(result.ok, result.steps[-1].details)
```

## Picking components

| you want to …                       | use                              |
|-------------------------------------|----------------------------------|
| run entirely locally, no API        | `--llm ollama --model qwen2.5-coder` |
| use Claude for tool-calling         | `--llm anthropic`                |
| send to Onshape instead of FreeCAD  | `--engine onshape`               |
| cut on a hobby CNC                  | `--machine grbl_3018`            |
| FDM 3D print                        | `--machine marlin_fdm --process 3d_print_fdm` |
| laser-cut 2D                        | `--machine linuxcnc_3axis --process laser_cut` |
| run FEA                             | install CalculiX (`apt install calculix-ccx`) |
| check collisions                    | `pip install -e ".[fcl]"`        |

## Without an LLM

Every layer works independently. Drop a CadQuery or FreeCAD script into
`out/part.<engine>.py` and run:

```bash
joycad run --engine cadquery --skip-validation
```

## Tests

```bash
make test      # 12 pass, 1 skipped (needs freecadcmd)
```
