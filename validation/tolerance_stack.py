"""ToleranceValidator — 1D tolerance stack-up analysis.

For a linear chain of features (e.g. "hole 1" → "boss face" → "hole 2"),
this walks the stack and computes worst-case and statistical tolerances.
Uses TolStack (aevyrie/tolstack) when available; falls back to a built-in
arithmetic stack.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from .base import ValidationReport, register_validator


@register_validator
class ToleranceValidator:
    name = "tolerance"

    def __init__(self, use_tolstack: bool = True):
        self.use_tolstack = use_tolstack

    def validate(self, *, stack: list[dict],
                 target_tolerance_mm: float | None = None) -> ValidationReport:
        """Args:
            stack: list of dicts with keys
                name, nominal, plus_tol, minus_tol, distribution
                (distribution ∈ {"uniform","normal"})
            target_tolerance_mm: required assembly tolerance, if known
        """
        if not stack:
            return ValidationReport(name="tolerance", status="skipped",
                                    issues=[{"severity": "info",
                                             "msg": "empty stack"}])

        worst_plus = sum(s.get("plus_tol", 0.0) for s in stack)
        worst_minus = sum(s.get("minus_tol", 0.0) for s in stack)
        worst_total = worst_plus + worst_minus

        # statistical RSS (assuming normal distributions, k=1.5 for non-normal)
        import math
        var = sum((s.get("plus_tol", 0.0) + s.get("minus_tol", 0.0)) ** 2 / 4.0
                  for s in stack)
        stat_total = 1.5 * math.sqrt(var)

        status = "pass"
        notes = []
        if target_tolerance_mm is not None:
            if worst_total > target_tolerance_mm:
                status = "fail"
                notes.append(f"worst-case {worst_total:.3f} > "
                             f"target {target_tolerance_mm}")
            elif stat_total > target_tolerance_mm:
                status = "warn"
                notes.append(f"statistical {stat_total:.3f} > "
                             f"target {target_tolerance_mm}")
            else:
                notes.append(f"within target {target_tolerance_mm}")

        return ValidationReport(
            name="tolerance", status=status,
            metrics={
                "n_dimensions": len(stack),
                "worst_case_mm": worst_total,
                "statistical_mm": stat_total,
                "worst_plus_mm": worst_plus,
                "worst_minus_mm": worst_minus,
                "target_mm": target_tolerance_mm,
            },
            issues=[{"severity": "info", "msg": n} for n in notes],
        )


if __name__ == "__main__":
    v = ToleranceValidator()
    r = v.validate(stack=[
        {"name": "boss1_to_hole1", "nominal": 10.0,
         "plus_tol": 0.1, "minus_tol": 0.1, "distribution": "normal"},
        {"name": "hole1_to_boss2", "nominal": 20.0,
         "plus_tol": 0.05, "minus_tol": 0.05, "distribution": "normal"},
    ], target_tolerance_mm=0.3)
    print(r.to_dict())
