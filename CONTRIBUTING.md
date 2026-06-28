# Contributing to JoyCAD

## Layout

```
ai/                LLM client, prompt refiner, RAG, tool defs
cad/               CAD engines (FreeCAD, CadQuery, Onshape, Fusion)
                    + geometry I/O (STEP/STL/DXF/SVG)
cam/               CAM backends + post-processors + G-code validator
validation/        FEA, collision, DFM, tolerance
outputs/           BOM, manufacturing notes, 2D drawings
orchestrator/      Pipeline + CLI + REST API
config/            machine/material/DFM rule YAML
examples/          end-to-end worked examples
tests/             pytest suite
```

## Adding a new CAD engine

1. Subclass `cad.base.CADEngine` in `cad/<your_engine>.py`.
2. Decorate with `@register_engine`.
3. Set `name = "<your_engine>"` class attribute.
4. Implement `execute(script_path, out_dir) -> CADGeometry`.

The engine returns a STEP file in `out_dir/part.step` and reports its
bounding box, volume, and area.

## Adding a new CAM backend

1. Subclass `cam.base.CAMBackend` in `cam/<your_cam>.py`.
2. Decorate with `@register_cam`.
3. Implement `generate(step_path, job, out_dir) -> RawToolpaths`.

Toolpaths are emitted in a neutral move list. The post-processor turns
them into machine G-code.

## Adding a new post-processor

1. Subclass `cam.post_processor.PostProcessor` in `cam/<post>.py`.
2. Decorate with `@register_post`.
3. Implement `post(toolpaths, out_path, machine_config) -> Path`.
4. Drop a machine YAML into `config/machines/` referencing the post name.

## Adding a new validator

1. Subclass `validation.base.Validator`.
2. Decorate with `@register_validator`.
3. Implement `validate(**kwargs) -> ValidationReport`.

The pipeline calls it with the right kwargs based on the validator name.

## Adding DFM rules

Edit `config/dfm_rules.yaml`. Rules are read by `validation.dfm.DFMRules.load`.

## Adding RAG snippets

Drop `.py` or `.md` files into `knowledge/cad_snippets.jsonl` (one JSON
record per line: `{text, engine, tags}`). The pipeline will embed and
index them on first run.

## Style

- Python 3.10+
- Type hints everywhere
- Pydantic/dataclasses for inter-layer payloads
- `loguru` for logging
- `rich` for CLI output

## Tests

Every layer has at least one smoke test in `tests/test_bundle.py`.
Add tests for new code. Avoid mocking — prefer real execution with
small inputs.
