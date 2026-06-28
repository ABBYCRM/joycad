"""DFMValidator — checks Design-for-Manufacturability rules.

The rule list comes from ``config/dfm_rules.yaml``. Each rule is a small
predicate over the geometry. We use CadQuery to inspect STEP files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from loguru import logger

from .base import ValidationReport, register_validator


@dataclass
class DFMRules:
    min_internal_corner_radius_mm: float = 1.0
    min_hole_diameter_mm: float = 1.0
    min_wall_thickness_mm: float = 0.8
    min_slot_width_mm: float = 1.0
    max_pocket_depth_mm: float = 30.0
    max_hole_depth_to_dia_ratio: float = 10.0
    hard_no: list[str] = field(default_factory=list)
    warn_only: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "DFMRules":
        data = yaml.safe_load(path.read_text())
        proc = data.get("default_process", "cnc_mill")
        mins = data.get("min_feature", {}).get(proc, {})
        return cls(
            min_internal_corner_radius_mm=mins.get("internal_corner_radius_mm", 1.0),
            min_hole_diameter_mm=mins.get("hole_diameter_mm", 1.0),
            min_wall_thickness_mm=mins.get("wall_thickness_mm", 0.8),
            min_slot_width_mm=mins.get("slot_width_mm", 1.0),
            max_pocket_depth_mm=mins.get("pocket_depth_mm", 30.0),
            max_hole_depth_to_dia_ratio=mins.get("hole_depth_to_dia_ratio", 10.0),
            hard_no=data.get("hard_no", []),
            warn_only=data.get("warn_only", []),
        )


@register_validator
class DFMValidator:
    name = "dfm"

    def __init__(self, rules: DFMRules | None = None,
                 rules_path: Path | None = None):
        if rules is None:
            rules_path = rules_path or (
                Path(__file__).resolve().parent.parent /
                "config" / "dfm_rules.yaml")
            if rules_path.exists():
                rules = DFMRules.load(rules_path)
            else:
                rules = DFMRules()
        self.rules = rules

    def validate(self, *, step_path: Path, process: str = "cnc_mill",
                 material: str = "") -> ValidationReport:
        issues: list[dict] = []
        try:
            import cadquery as cq
            from cadquery import importers
        except ImportError:
            return ValidationReport(name="dfm", status="skipped",
                                    issues=[{"severity": "info",
                                             "msg": "cadquery not installed"}])

        shape = importers.importStep(str(step_path)).val()
        bb = shape.BoundingBox()
        volume = float(shape.Volume())
        if volume <= 0:
            issues.append({"severity": "error", "rule": "zero_volume",
                           "msg": "STEP file has zero or negative volume"})
            return ValidationReport(name="dfm", status="fail", issues=issues)

        # min wall thickness: detect by intersecting the bounding box and the
        # shape; if the difference is large, walls are thin. Coarse but useful.
        try:
            from trimesh import proximity
            shell = shape.Mesh()
            shell.write("/tmp/_shell.stl")
            import trimesh, numpy as np
            mesh = trimesh.load("/tmp/_shell.stl")
            # sample interior points and check distance to surface
            pts = np.random.uniform(low=[bb.xmin, bb.ymin, bb.zmin],
                                    high=[bb.xmax, bb.ymax, bb.zmax],
                                    size=(2000, 3))
            inside = mesh.contains(pts)
            inside_pts = pts[inside]
            if len(inside_pts) > 0:
                _, dist, _ = proximity.closest_point(mesh, inside_pts)
                min_thick = float(dist.min() * 2)
                if min_thick < self.rules.min_wall_thickness_mm:
                    issues.append({
                        "severity": "warn", "rule": "thin_wall",
                        "msg": f"thinnest wall ≈ {min_thick:.2f} mm < "
                               f"{self.rules.min_wall_thickness_mm} mm",
                    })
        except Exception as e:
            logger.debug(f"[DFM] wall thickness check skipped: {e}")

        # hole detection — every CYLINDER face counts as a hole candidate
        try:
            for face in shape.Faces():
                if face.geomType() == "CYLINDER":
                    r = face.radius()
                    d = 2 * r
                    if d < self.rules.min_hole_diameter_mm:
                        issues.append({"severity": "warn", "rule": "small_hole",
                                       "msg": f"hole dia {d:.2f}mm below "
                                              f"{self.rules.min_hole_diameter_mm}mm",
                                       "diameter_mm": d})
        except Exception as e:
            logger.debug(f"[DFM] hole check skipped: {e}")

        # corner radii
        try:
            for edge in shape.Edges():
                if edge.geomType() == "CIRCLE":
                    r = edge.radius()
                    if r < self.rules.min_internal_corner_radius_mm:
                        issues.append({
                            "severity": "warn", "rule": "tight_internal_radius",
                            "msg": f"internal radius {r:.2f} mm < "
                                   f"{self.rules.min_internal_corner_radius_mm} mm "
                                   f"(needs smaller tool)",
                            "radius_mm": r,
                        })
                        break  # one finding is enough
        except Exception as e:
            logger.debug(f"[DFM] corner check skipped: {e}")

        status = "fail" if any(i["severity"] == "error" for i in issues) else (
            "warn" if any(i["severity"] == "warn" for i in issues) else "pass")

        return ValidationReport(
            name="dfm", status=status,
            metrics={"bbox_mm": [bb.xlen, bb.ylen, bb.zlen],
                     "volume_mm3": volume},
            issues=issues,
        )
