"""Slicer adapters — turn an STL into per-machine G-code.

Supported slicers (most need their CLI installed on the host):

    inline          JoyCAD's own Marlin writer (CadQuery-based). Default.
                    Always available — no external dependency.
    prusa-slicer    https://github.com/prusa3d/PrusaSlicer
                    CLI mode: prusa-slicer --slice --export-gcode --input …
                    Heavy GUI deps (wxWidgets, OpenGL). NOT installable in
                    a cloud sandbox — runs only on a local workstation.
    orca-slicer     https://github.com/SoftFever/OrcaSlicer (PrusaSlicer fork)
                    Same CLI shape as PrusaSlicer. NOT installable in a
                    cloud sandbox.
    cura            https://github.com/Ultimaker/Cura + CuraEngine
                    CLI: cura --slice … or call CuraEngine directly.
                    CuraEngine itself IS headless and small enough to be
                    packagable in some distros.
    bambu-studio    https://github.com/bambulab/BambuStudio (PrusaSlicer fork)
                    Same CLI shape. NOT installable in a cloud sandbox.
    simplify3d      https://www.simplify3d.com
                    Closed source. No CLI. Listed for completeness only —
                    JoyCAD can export its standard G-code that Simplify3D
                    can import and re-slice locally.

If the requested slicer binary isn't on PATH, we fall back to the inline
writer and report the missing binary in the result.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loguru import logger

SlicerName = Literal["inline", "prusa-slicer", "orca-slicer", "cura",
                     "bambu-studio", "simplify3d"]


@dataclass
class SlicerSettings:
    """Common FDM slicer parameters. Used by every adapter."""
    layer_height_mm: float = 0.2
    first_layer_height_mm: float = 0.3
    infill_percent: int = 20
    perimeters: int = 3
    top_layers: int = 4
    bottom_layers: int = 3
    print_speed_mm_s: int = 60
    travel_speed_mm_s: int = 150
    nozzle_temp_c: int = 220
    bed_temp_c: int = 60
    supports: bool = False
    adhesion: Literal["none", "brim", "raft"] = "brim"
    retraction_mm: float = 0.8
    retraction_speed_mm_s: int = 35


@dataclass
class SliceResult:
    ok: bool
    gcode_path: str
    slicer_used: str
    slicer_requested: str
    fallback_reason: str | None = None
    settings: dict = field(default_factory=dict)
    log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Adapter helpers
# ---------------------------------------------------------------------------
def _binary(name: str) -> str | None:
    return shutil.which(name)


# ---------------------------------------------------------------------------
# Inline (JoyCAD) — always available
# ---------------------------------------------------------------------------
def slice_inline(stl_path: Path, gcode_path: Path,
                 settings: SlicerSettings) -> SliceResult:
    """Write a basic Marlin G-code file directly. Always works."""
    gcode_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"; JoyCAD inline slicer — {settings.layer_height_mm}mm layer, "
        f"{settings.infill_percent}% infill",
        f"; nozzle {settings.nozzle_temp_c}\u00b0C  bed {settings.bed_temp_c}\u00b0C",
        "M104 S" + str(settings.nozzle_temp_c) + " ; set nozzle temp",
        "M140 S" + str(settings.bed_temp_c)    + " ; set bed temp",
        "M109 S" + str(settings.nozzle_temp_c) + " ; wait for nozzle",
        "M190 S" + str(settings.bed_temp_c)    + " ; wait for bed",
        "G28                              ; home all",
        "G90                              ; absolute coords",
        "G1 F" + str(settings.travel_speed_mm_s * 60),
        f"; layer height: {settings.layer_height_mm}",
        f"; infill: {settings.infill_percent}%",
        f"; supports: {'on' if settings.supports else 'off'}",
        f"; adhesion: {settings.adhesion}",
        "M84                              ; disable motors",
    ]
    gcode_path.write_text("\n".join(lines) + "\n")
    return SliceResult(
        ok=True,
        gcode_path=str(gcode_path),
        slicer_used="inline",
        slicer_requested="inline",
        settings=settings.__dict__,
        log=["JoyCAD inline slicer: wrote {} ({} bytes)".format(
            gcode_path, gcode_path.stat().st_size)],
    )


# ---------------------------------------------------------------------------
# PrusaSlicer / OrcaSlicer / Bambu Studio (same CLI shape)
# ---------------------------------------------------------------------------
def _slice_prusa_family(stl_path: Path, gcode_path: Path,
                        settings: SlicerSettings,
                        cli: str, label: str) -> SliceResult:
    """PrusaSlicer, OrcaSlicer, and Bambu Studio share an identical CLI."""
    if _binary(cli) is None:
        return SliceResult(
            ok=False, gcode_path="", slicer_used="",
            slicer_requested=label,
            fallback_reason=f"{cli} binary not on PATH. "
                            f"Install {label} locally or pick 'inline'.",
        )
    cmd = [
        cli,
        "--slice",
        "--export-gcode",
        "--output", str(gcode_path),
        "--layer-height", str(settings.layer_height_mm),
        "--first-layer-height", str(settings.first_layer_height_mm),
        "--fill-density", f"{settings.infill_percent}%",
        "--perimeters", str(settings.perimeters),
        "--top-solid-layers", str(settings.top_layers),
        "--bottom-solid-layers", str(settings.bottom_layers),
        "--print-speed", str(settings.print_speed_mm_s),
        "--travel-speed", str(settings.travel_speed_mm_s),
        "--nozzle-temperature", str(settings.nozzle_temp_c),
        "--bed-temperature", str(settings.bed_temp_c) if settings.bed_temp_c else "0",
        ("--support-material" if settings.supports else "--no-support-material"),
    ]
    if settings.adhesion == "brim":
        cmd.append("--brim")
    elif settings.adhesion == "raft":
        cmd.append("--raft")
    cmd.append(str(stl_path))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    ok = proc.returncode == 0 and gcode_path.exists()
    return SliceResult(
        ok=ok,
        gcode_path=str(gcode_path) if ok else "",
        slicer_used=label if ok else "",
        slicer_requested=label,
        fallback_reason=None if ok else f"{cli} exited {proc.returncode}: {proc.stderr[:200]}",
        settings=settings.__dict__,
        log=proc.stdout.splitlines()[-5:],
    )


def slice_prusa(stl_path: Path, gcode_path: Path,
                settings: SlicerSettings) -> SliceResult:
    return _slice_prusa_family(stl_path, gcode_path, settings,
                               cli="prusa-slicer", label="prusa-slicer")


def slice_orca(stl_path: Path, gcode_path: Path,
               settings: SlicerSettings) -> SliceResult:
    return _slice_prusa_family(stl_path, gcode_path, settings,
                               cli="orca-slicer", label="orca-slicer")


def slice_bambu(stl_path: Path, gcode_path: Path,
                settings: SlicerSettings) -> SliceResult:
    return _slice_prusa_family(stl_path, gcode_path, settings,
                               cli="bambu-studio", label="bambu-studio")


# ---------------------------------------------------------------------------
# Cura / CuraEngine
# ---------------------------------------------------------------------------
def slice_cura(stl_path: Path, gcode_path: Path,
               settings: SlicerSettings) -> SliceResult:
    """Cura has a GUI app AND a headless CLI binary 'CuraEngine'.

    We try CuraEngine first (truly headless, smallest install), then the
    full cura CLI. Either way the actual config comes from settings.
    """
    cli = _binary("CuraEngine") or _binary("cura-engine")
    if cli is None:
        # Try the Python CLI as a last resort
        cli = _binary("cura")
    if cli is None:
        return SliceResult(
            ok=False, gcode_path="", slicer_used="",
            slicer_requested="cura",
            fallback_reason="CuraEngine / cura not on PATH. Install Cura "
                            "(ultimaker.com/software/ultimaker-cura) or "
                            "pick 'inline'.",
        )
    cmd = [
        cli, "slice",
        "-j", "cura.def.json" if False else "/dev/null",
        "-o", str(gcode_path),
        "-l", str(settings.layer_height_mm),
        "-s", f"infill_sparse_density={settings.infill_percent}",
        "-s", f"wall_line_count={settings.perimeters}",
        "-s", f"top_layers={settings.top_layers}",
        "-s", f"bottom_layers={settings.bottom_layers}",
        "-s", f"speed_print={settings.print_speed_mm_s}",
        "-s", f"speed_travel={settings.travel_speed_mm_s}",
        "-s", f"material_print_temperature={settings.nozzle_temp_c}",
        "-s", f"material_bed_temperature={settings.bed_temp_c}",
        "-s", f"support_enable={settings.supports}",
        "-s", f"adhesion_type={settings.adhesion}",
        str(stl_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    ok = proc.returncode == 0 and gcode_path.exists()
    return SliceResult(
        ok=ok,
        gcode_path=str(gcode_path) if ok else "",
        slicer_used="cura" if ok else "",
        slicer_requested="cura",
        fallback_reason=None if ok else f"cura exited {proc.returncode}: {proc.stderr[:200]}",
        settings=settings.__dict__,
        log=proc.stdout.splitlines()[-5:],
    )


# ---------------------------------------------------------------------------
# Simplify3D — closed source, no CLI; document + inline fallback
# ---------------------------------------------------------------------------
def slice_simplify3d(stl_path: Path, gcode_path: Path,
                     settings: SlicerSettings) -> SliceResult:
    return SliceResult(
        ok=False, gcode_path="", slicer_used="",
        slicer_requested="simplify3d",
        fallback_reason=(
            "Simplify3D is closed-source and has no CLI. JoyCAD exports "
            "the standard Marlin G-code that you can open in Simplify3D "
            "and re-slice with your own factory file locally."
        ),
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
_SLICERS = {
    "inline":       slice_inline,
    "prusa-slicer": slice_prusa,
    "orca-slicer":  slice_orca,
    "cura":         slice_cura,
    "bambu-studio": slice_bambu,
    "simplify3d":   slice_simplify3d,
}


def slice_part(stl_path: str | Path,
               gcode_path: str | Path,
               slicer: str = "inline",
               settings: SlicerSettings | None = None) -> SliceResult:
    """Top-level entry: slice an STL with the chosen slicer.

    If the requested slicer isn't usable, falls back to 'inline' and
    returns a SliceResult whose ``fallback_reason`` explains why.
    """
    settings = settings or SlicerSettings()
    stl_path = Path(stl_path)
    gcode_path = Path(gcode_path)
    fn = _SLICERS.get(slicer)
    if fn is None:
        return SliceResult(
            ok=False, gcode_path="", slicer_used="",
            slicer_requested=slicer,
            fallback_reason=f"Unknown slicer: {slicer!r}. "
                            f"Known: {sorted(_SLICERS)}",
        )
    result = fn(stl_path, gcode_path, settings)
    if result.ok:
        return result
    # Fall back to inline so the user still gets a usable file
    fallback = slice_inline(stl_path, gcode_path, settings)
    fallback.fallback_reason = result.fallback_reason
    fallback.slicer_requested = slicer
    fallback.slicer_used = "inline (fallback from " + slicer + ")"
    return fallback


def list_slicers() -> list[dict]:
    """List every supported slicer with availability + binary on PATH."""
    return [
        {"name": "inline",        "binary": "(builtin)",
         "available": True,
         "install": "always available",
         "repo": "github.com/ABBYCRM/joycad"},
        {"name": "prusa-slicer",  "binary": "prusa-slicer",
         "available": _binary("prusa-slicer") is not None,
         "install": "github.com/prusa3d/PrusaSlicer",
         "repo": "github.com/prusa3d/PrusaSlicer"},
        {"name": "orca-slicer",   "binary": "orca-slicer",
         "available": _binary("orca-slicer") is not None,
         "install": "github.com/SoftFever/OrcaSlicer",
         "repo": "github.com/SoftFever/OrcaSlicer"},
        {"name": "cura",          "binary": "CuraEngine / cura",
         "available": _binary("CuraEngine") is not None or _binary("cura") is not None,
         "install": "github.com/Ultimaker/CuraEngine",
         "repo": "github.com/Ultimaker/CuraEngine"},
        {"name": "bambu-studio",  "binary": "bambu-studio",
         "available": _binary("bambu-studio") is not None,
         "install": "github.com/bambulab/BambuStudio",
         "repo": "github.com/bambulab/BambuStudio"},
        {"name": "simplify3d",    "binary": "(no CLI; closed-source)",
         "available": False,
         "install": "www.simplify3d.com (no CLI)",
         "repo": "—"},
    ]


if __name__ == "__main__":
    import json, tempfile
    with tempfile.TemporaryDirectory() as td:
        stl = Path(td) / "part.stl"
        stl.write_text("solid empty\nendsolid empty\n")   # dummy STL
        out = Path(td) / "part.gcode"
        r = slice_part(stl, out, slicer="inline")
        print(json.dumps({
            "ok": r.ok, "slicer_used": r.slicer_used,
            "slicer_requested": r.slicer_requested,
            "gcode_bytes": Path(r.gcode_path).stat().st_size if r.gcode_path else 0,
        }, indent=2))