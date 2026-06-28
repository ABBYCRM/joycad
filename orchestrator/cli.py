"""JoyCAD CLI — `joycad run`, `joycad serve`, etc."""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .pipeline import Pipeline, PipelineConfig

app = typer.Typer(help="JoyCAD — AI-driven CAD/CAM bundle")
console = Console()


@app.command()
def run(
    intent: str = typer.Option(..., "--intent", "-i",
                               help="Natural-language design intent."),
    out_dir: Path = typer.Option("./out", "--out", "-o",
                                  help="Where to drop artifacts."),
    machine: str = typer.Option("linuxcnc_3axis", "--machine", "-m"),
    material: str = typer.Option("6061-T6", "--material"),
    cad_engine: str = typer.Option("cadquery", "--engine", "-e",
                                   help="cadquery | freecad | onshape | fusion"),
    cam: str = typer.Option("freecad_path", "--cam"),
    post: str = typer.Option("linuxcnc", "--post"),
    process: str = typer.Option("cnc_mill", "--process"),
    skip_validation: bool = typer.Option(False, "--skip-validation"),
    llm_provider: str = typer.Option(None, "--llm"),
    context: str = typer.Option("", "--context", "-c"),
):
    """Run the full pipeline from intent to G-code + BOM + notes."""
    cfg = PipelineConfig(
        intent=intent, out_dir=out_dir, machine=machine,
        material=material, cad_engine=cad_engine, cam_backend=cam,
        post_processor=post, process=process,
        skip_validation=skip_validation, llm_provider=llm_provider,
        context=context,
    )
    result = Pipeline(cfg).run()

    table = Table(title="JoyCAD run", show_lines=True)
    table.add_column("step")
    table.add_column("status")
    table.add_column("elapsed")
    table.add_column("details")
    for s in result.steps:
        elapsed = (s.finished_at - s.started_at) if s.finished_at else 0
        det = ", ".join(f"{k}={v}" for k, v in (s.details or {}).items())
        if len(det) > 60: det = det[:57] + "…"
        table.add_row(s.name, s.status, f"{elapsed:5.2f}s", det)
    console.print(table)

    if result.ok:
        console.print(f"\n[bold green]✓ done[/bold green] artifacts in: {out_dir}")
        console.print(f"  • STEP:     {result.geometry.step_path}")
        if result.gcode_path:
            console.print(f"  • G-code:   {result.gcode_path}")
        if result.manufacturing_notes_path:
            console.print(f"  • Mfg notes:{result.manufacturing_notes_path}")
    else:
        console.print(f"[bold red]✗ failed:[/bold red] {result.error}")


@app.command()
def engines():
    """List available CAD engines and CAM backends."""
    from cad import list_engines
    from cam import list_cams
    from validation import list_validators
    from cam.post_processor import _REGISTRY as posts

    t = Table(title="JoyCAD engines")
    t.add_column("kind"); t.add_column("name")
    for e in list_engines(): t.add_row("CAD", e)
    for c in list_cams(): t.add_row("CAM", c)
    for v in list_validators(): t.add_row("validation", v)
    for p in posts: t.add_row("post", p)
    console.print(t)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
):
    """Run the REST API server."""
    import uvicorn
    from .api import create_app
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


@app.command()
def demo(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8501, "--port"),
):
    """Launch the Streamlit web UI — the MVP user front door.

    Runs the same Pipeline you get from `joycad run`, but in your browser.
    Default LLM provider is `mock` so it works without any API key.
    """
    import os
    os.environ.setdefault("JOYCAD_LLM_PROVIDER", "mock")
    import subprocess
    import sys
    web_path = Path(__file__).parent / "web.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(web_path),
           "--server.address", host, "--server.port", str(port),
           "--browser.gatherUsageStats", "false",
           "--theme.base", "dark"]
    console.print(f"[bold green]→[/bold green] launching Streamlit on "
                  f"http://{host}:{port}")
    console.print("      (Ctrl-C to stop)")
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        console.print("\n[yellow]stopped[/yellow]")


if __name__ == "__main__":
    app()
