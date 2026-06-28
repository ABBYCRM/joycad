"""CollisionValidator — pure-Python AABB fallback when FCL isn't installed.

This is the default collision check on cloud sandboxes (Render, Heroku, etc.)
where building python-fcl from source is impractical. It checks toolpath
moves against the stock bounding box (the most common collision risk on a
3-axis mill: cutter plows into the table or wanders off the stock).

For richer mesh-vs-mesh checks (fixtures, clamps, complex stock shapes)
FCL is still preferred — install it via `pip install python-fcl` on a host
where the Cython build completes (Linux x86_64, Python ≤ 3.12).
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from .base import ValidationReport, register_validator


@register_validator
class AABBCollisionValidator:
    name = "collision"

    def validate(self, *, step_path: Path, toolpaths, fixtures: list | None = None,
                 cutter_diameter_mm: float = 6.0,
                 cutter_length_mm: float = 25.0,
                 stock_bbox_mm: tuple | None = None,
                 **_) -> ValidationReport:
        """AABB collision check. No external deps beyond numpy.

        Args:
            step_path:     the STEP file (used to derive stock bbox if not given).
            toolpaths:     Toolpath dataclass with .moves (each is a Move dict).
            fixtures:      ignored in this minimal check.
            cutter_diameter_mm: cutter diameter in mm.
            cutter_length_mm:   cutter flute length (assumed extending downward from tip).
            stock_bbox_mm:      (xmin, ymin, zmin, xmax, ymax, zmax) of the stock.
                                 If None, derived from STL alongside STEP.
        """
        import numpy as np

        # Derive stock bbox from the STL if not provided
        if stock_bbox_mm is None:
            stl_path = Path(str(step_path).replace(".step", ".stl"))
            if not stl_path.exists():
                return ValidationReport(
                    name="collision", status="skipped",
                    issues=[{"severity": "info",
                             "msg": f"AABB collision needs an STL; "
                                    f"{stl_path.name} not found."}],
                )
            try:
                import trimesh
                m = trimesh.load_mesh(str(stl_path))
                if isinstance(m, trimesh.Scene):
                    m = trimesh.util.concatenate(
                        [g for g in m.geometry.values()])
                stock_bbox_mm = tuple(m.bounds.flatten().tolist())   # xmin,ymin,zmin,xmax,ymax,zmax
            except Exception as e:
                return ValidationReport(
                    name="collision", status="skipped",
                    issues=[{"severity": "info",
                             "msg": f"AABB collision needs trimesh to read STL: {e}"}],
                )

        xmin, ymin, zmin, xmax, ymax, zmax = stock_bbox_mm
        # Realistic collision risks on a 3-axis mill:
        #   1. The cutter center is outside the stock XY footprint by more than
        #      the cutter radius + a small margin → tool would crash into the
        #      vise jaws / fixtures / table edges.
        #   2. The cutter holder (tip + cutter_length) reaches BELOW the table
        #      top (z=0) — only a problem if the tool tip is so deep that even
        #      the holder would be submerged. We catch this by checking
        #      tip_z + cutter_length > 0  →  NO, that's the holder top.
        #      Actually we check: tip_z + cutter_length < 0  → the holder has
        #      plunged below the table top.
        #      A normal cut at z = -1 with cutter_length = 25 mm has holder top
        #      at z = 24 mm — well above the table — so this is rarely violated.
        # Tolerance: 1.0 mm on XY, 0.5 mm on Z.
        tol_xy = cutter_diameter_mm / 2 + 1.0
        tol_z  = 0.5
        # We assume the table top sits at z = 0 unless stock_zmin is below.
        # The "stock sits ON the table" assumption is the common 3-axis setup.
        table_z = min(0.0, float(zmin))

        violations = []
        checks = 0
        moves = list(getattr(toolpaths, "moves", []) or [])
        for i, mv in enumerate(moves):
            x, y, z = float(mv.get("x", 0)), float(mv.get("y", 0)), float(mv.get("z", 0))
            checks += 1
            # (1) XY out-of-stock: cutter center is outside the stock XY box
            if (x < xmin - tol_xy or x > xmax + tol_xy or
                y < ymin - tol_xy or y > ymax + tol_xy):
                violations.append({
                    "move_index": i, "kind": "outside_stock_xy",
                    "where": {"x": x, "y": y, "z": z,
                              "stock": [xmin, ymin, zmin, xmax, ymax, zmax],
                              "tol_xy": tol_xy},
                })
                continue
            # (2) Holder plunge: holder top (z + cutter_length) is below the table.
            holder_top_z = z + cutter_length_mm
            if holder_top_z < table_z - tol_z:
                violations.append({
                    "move_index": i, "kind": "holder_below_table",
                    "where": {"x": x, "y": y, "z": z,
                              "holder_top_z": holder_top_z,
                              "table_z": table_z},
                })

        if violations:
            return ValidationReport(
                name="collision", status="fail",
                issues=[{"severity": "error",
                         "msg": f"AABB collision: {len(violations)} "
                                f"violation(s) over {checks} moves"}],
                metrics={"violations": violations[:50],
                         "total_violations": len(violations),
                         "total_moves": checks,
                         "backend": "aabb",
                         "note": "pure-Python AABB check; install python-fcl "
                                 "for mesh-vs-mesh with fixtures/clamps."},
            )

        return ValidationReport(
            name="collision", status="pass",
            metrics={"checks": checks,
                     "violations": 0,
                     "backend": "aabb",
                     "stock_bbox_mm": stock_bbox_mm},
        )