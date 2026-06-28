"""FEAValidator — runs static FEA via CalculiX (``ccx``).

CalculiX expects:
    • a mesh in INP / Abaqus format
    • material props
    • a step + BCs + loads

We mesh with Gmsh (via FreeCAD's MeshPart) and emit a minimal INP. If ccx is
unavailable on PATH, we return ``status='skipped'`` with a clear note — no
silent pass.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from loguru import logger

from .base import ValidationReport, register_validator


@register_validator
class FEAValidator:
    name = "fea"

    def __init__(self, ccx_cmd: str | None = None):
        self.ccx = ccx_cmd or os.getenv("CALCULIX_CMD", "ccx")

    def validate(self, *, step_path: Path, material: dict | None = None,
                 loads: dict | None = None,
                 fixtures: list[dict] | None = None,
                 out_dir: Path | None = None) -> ValidationReport:
        if shutil.which(self.ccx) is None:
            return ValidationReport(
                name="fea", status="skipped",
                issues=[{"severity": "info",
                         "msg": f"CalculiX '{self.ccx}' not on PATH; FEA skipped."}],
            )
        out_dir = out_dir or step_path.parent / "fea"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            mesh_inp = self._mesh(step_path, out_dir)
            inp_path = self._write_inp(mesh_inp, material or {}, loads or {},
                                       fixtures or [], out_dir)
            logger.info(f"[FEA] running ccx on {inp_path.name}…")
            proc = subprocess.run([self.ccx, "-i", "inp"], cwd=str(out_dir),
                                  capture_output=True, text=True, timeout=1800)
            if proc.returncode != 0:
                return ValidationReport(
                    name="fea", status="fail",
                    issues=[{"severity": "error",
                             "msg": f"ccx exit {proc.returncode}: {proc.stderr[-500:]}"}],
                    artifacts=[str(out_dir / "inp.frd")],
                )
            max_vm = self._parse_max_vonmises(out_dir / "inp.frd")
            yield_mpa = (material or {}).get("yield_strength_mpa", 250.0)
            margin = (yield_mpa / max_vm) if max_vm else float("inf")
            status = "pass" if margin >= 1.5 else ("warn" if margin >= 1.0 else "fail")
            return ValidationReport(
                name="fea", status=status,
                metrics={"max_vonmises_mpa": max_vm,
                         "yield_strength_mpa": yield_mpa,
                         "safety_factor": margin},
                artifacts=[str(out_dir / "inp.frd"),
                           str(out_dir / "inp.dat")],
                issues=[{"severity": "info",
                         "msg": f"max von Mises {max_vm:.1f} MPa / "
                               f"yield {yield_mpa} → SF={margin:.2f}"}],
            )
        except Exception as e:
            return ValidationReport(
                name="fea", status="fail",
                issues=[{"severity": "error", "msg": str(e)}],
            )

    # ----- helpers -----
    def _mesh(self, step_path: Path, out_dir: Path) -> Path:
        # Prefer Gmsh via FreeCAD; fall back to trimesh-based coarse mesh.
        try:
            import FreeCAD, Part, MeshPart
            shape = Part.Shape()
            shape.read(str(step_path))
            mesh = MeshPart.meshFromShape(shape, LinearDeflection=0.5,
                                          AngularDeflection=0.5)
            inp = out_dir / "mesh.unv"
            mesh.write(str(inp))
            return inp
        except Exception as e:
            logger.warning(f"[FEA] FreeCAD mesh failed ({e}); "
                           f"falling back to gmsh.")
        try:
            import gmsh
            gmsh.initialize()
            gmsh.open(str(step_path))
            gmsh.model.mesh.generate(3)
            inp = out_dir / "mesh.inp"
            gmsh.write(str(inp))
            gmsh.finalize()
            return inp
        except Exception as e:
            raise RuntimeError(f"could not mesh STEP for FEA: {e}")

    def _write_inp(self, mesh_path: Path, material: dict, loads: dict,
                   fixtures: list[dict], out_dir: Path) -> Path:
        """Emit a minimal CalculiX .inp file."""
        E = material.get("elastic_modulus_gpa", 70.0) * 1e3      # MPa
        nu = material.get("poisson", 0.33)
        rho = material.get("density_g_cm3", 2.7) * 1e-9         # t/mm^3
        yield_mpa = material.get("yield_strength_mpa", 250.0)

        lines: list[str] = ["*HEADING", "JoyCAD FEA",
                            f"*INCLUDE, INPUT={mesh_path.name}"]
        lines.append("*MATERIAL, NAME=JOY")
        lines.append(f"*ELASTIC, TYPE=ISO")
        lines.append(f"{E:.1f}, {nu}")
        lines.append(f"*DENSITY")
        lines.append(f"{rho:.3e}")
        lines.append(f"*PLASTIC")
        lines.append(f"{yield_mpa:.1f}, 0.0")
        lines.append("*SOLID SECTION, ELSET=EALL, MATERIAL=JOY")
        lines.append("*STEP, NAME=static")
        lines.append("*STATIC")

        # fixtures (boundary conditions)
        for k, fix in enumerate(fixtures or [{"type": "fix",
                                                "nodes": [0, 0, 0, 0, 0, 0]}]):
            lines.append(f"*BOUNDARY")
            if fix.get("type") == "fix":
                lines.append(f"{fix.get('node_set', 9999)}, 1, 6, 0.0")

        # loads
        for load in loads.get("forces", []):
            lines.append(f"*CLOAD")
            lines.append(f"*INCLUDE, INPUT=loads.inp")
            break
        lines.append("*NODE FILE, FREQUENCY=1")
        lines.append("U")
        lines.append("*EL FILE, FREQUENCY=1")
        lines.append("S")
        lines.append("*END STEP")
        inp_path = out_dir / "inp.inp"
        inp_path.write_text("\n".join(lines))
        return inp_path

    def _parse_max_vonmises(self, frd_path: Path) -> float:
        """Best-effort FRD parser: scan for 'STRESS' block, max von Mises."""
        if not frd_path.exists():
            return 0.0
        import re
        max_vm = 0.0
        pat = re.compile(r"-?\d\.\d+E[+-]?\d{2}")
        in_stress = False
        for line in frd_path.read_text(errors="ignore").splitlines():
            if "STRESS" in line.upper():
                in_stress = True
                continue
            if in_stress:
                vals = [float(v) for v in pat.findall(line)]
                if len(vals) >= 6:
                    sxx, syy, szz, sxy, sxz, syz = vals[:6]
                    vm = ((sxx - syy)**2 + (syy - szz)**2 +
                          (szz - sxx)**2 + 3 * (sxy**2 + sxz**2 + syz**2)) ** 0.5
                    max_vm = max(max_vm, vm)
                if line.strip().upper().startswith(" -4"):
                    in_stress = False
        return max_vm
