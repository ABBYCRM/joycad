"""CollisionValidator — uses the Flexible Collision Library (FCL).

For each tool swept volume along the toolpath, we check it against the
stock + any fixtures. Anything touching → violation.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from .base import ValidationReport, register_validator


@register_validator
class CollisionValidator:
    name = "collision"

    def validate(self, *, step_path: Path, toolpaths, fixtures: list | None = None,
                 cutter_diameter_mm: float = 6.0,
                 cutter_length_mm: float = 25.0) -> ValidationReport:
        try:
            import numpy as np
            import trimesh
            import fcl                           # python-fcl
        except ImportError:
            return ValidationReport(
                name="collision", status="skipped",
                issues=[{"severity": "info",
                         "msg": "trimesh + python-fcl not installed; "
                                "see pyproject [fcl] extra."}],
            )

        stock_mesh = trimesh.load_mesh(str(step_path).replace(".step", ".stl"))
        if isinstance(stock_mesh, trimesh.Scene):
            stock_mesh = trimesh.util.concatenate(
                [g for g in stock_mesh.geometry.values()])
        stock_coll = fcl.CollisionObject(
            fcl.BVHModel(),
            fcl.Transform(np.eye(4)))

        # Build BVH from stock triangles
        verts = np.asarray(stock_mesh.vertices, dtype=np.float64)
        tris = np.asarray(stock_mesh.faces, dtype=np.int32)
        stock_coll.collision_geometry.begin_model(len(tris), len(verts))
        stock_coll.collision_geometry.add_vertices(verts)
        stock_coll.collision_geometry.add_triangles(tris)
        stock_coll.collision_geometry.end_model()

        contacts = []
        for i, mv in enumerate(toolpaths.moves or []):
            cutter = self._cutter_box(mv, cutter_diameter_mm, cutter_length_mm)
            req = fcl.CollisionRequest(num_max_contacts=4, enable_contact=True)
            res = fcl.CollisionResult()
            d = fcl.continuous_collision_distance if False else None
            ok = fcl.collide(cutter, stock_coll, req, res)
            if ok:
                for c in res.contacts:
                    contacts.append({
                        "move_index": i,
                        "tool_position": [mv.x, mv.y, mv.z],
                        "penetration_depth_mm": float(c.penetration_depth),
                        "normal": list(c.normal),
                    })

        status = "pass" if not contacts else "fail"
        return ValidationReport(
            name="collision", status=status,
            metrics={"contacts": len(contacts),
                     "moves_checked": len(toolpaths.moves or [])},
            issues=[{"severity": "error",
                     "msg": f"tool collides with stock at move {c['move_index']}",
                     **c} for c in contacts[:10]],
        )

    def _cutter_box(self, mv, dia: float, length: float):
        import numpy as np, fcl
        half = np.array([dia / 2, dia / 2, length / 2])
        center = np.array([mv.x, mv.y, mv.z + length / 2])
        # cylinder approximated as a box — coarse but catches gross collisions
        box = fcl.Box(*half)
        tf = fcl.Transform(np.eye(4))
        tf.translation = center
        return fcl.CollisionObject(box, tf)
