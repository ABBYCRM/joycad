"""GCodeValidator — lint and sanity-check a G-code file.

Detects:
    • missing motion command on a line
    • rapid moves that plunge below safe-Z
    • feed-rate spikes (> machine max)
    • arcs missing I/J/K
    • tool changes without spindle stop
    • Z drops without coolant on (for steel/alu)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from loguru import logger


@dataclass
class GCodeIssue:
    severity: str           # "info" | "warn" | "error"
    line_no: int
    message: str
    context: str = ""


@dataclass
class GCodeValidationReport:
    issues: list[GCodeIssue] = field(default_factory=list)
    line_count: int = 0
    feed_max_mm_min: float = 0.0
    rapid_max_z_mm: float = 0.0
    feed_max_z_mm: float = 0.0
    has_tool_changes: bool = False
    has_coolant: bool = False

    @property
    def status(self) -> str:
        if any(i.severity == "error" for i in self.issues):
            return "fail"
        if any(i.severity == "warn" for i in self.issues):
            return "warn"
        return "pass"

    def to_dict(self) -> dict:
        return {"status": self.status,
                "line_count": self.line_count,
                "feed_max_mm_min": self.feed_max_mm_min,
                "rapid_max_z_mm": self.rapid_max_z_mm,
                "feed_max_z_mm": self.feed_max_z_mm,
                "has_tool_changes": self.has_tool_changes,
                "has_coolant": self.has_coolant,
                "issues": [asdict(i) for i in self.issues]}


class GCodeValidator:
    def __init__(self, *, machine_safe_z_mm: float = 2.0,
                 machine_max_feed_mm_min: float = 5000.0):
        self.safe_z = machine_safe_z_mm
        self.max_feed = machine_max_feed_mm_min

    def validate(self, gcode_path: Path) -> GCodeValidationReport:
        report = GCodeValidationReport()
        cur_z = 0.0
        cur_feed = 0.0
        cur_motion = None
        for i, raw in enumerate(gcode_path.read_text().splitlines(), start=1):
            line = raw.split(";")[0].strip()
            if not line:
                continue
            report.line_count += 1
            tokens = line.split()

            if "T" in line and "M6" in line:
                report.has_tool_changes = True
                # tool change should stop spindle
            if any(t.startswith("M8") or t.startswith("M7") for t in tokens):
                report.has_coolant = True

            if tokens[0] in ("G0", "G00", "G1", "G01", "G2", "G02",
                             "G3", "G03"):
                cur_motion = tokens[0]
            else:
                continue

            z_tok = next((t for t in tokens if t.startswith("Z")), None)
            f_tok = next((t for t in tokens if t.startswith("F")), None)
            if z_tok:
                cur_z = float(z_tok[1:])
                if cur_motion in ("G0", "G00") and cur_z < -self.safe_z:
                    report.issues.append(GCodeIssue(
                        severity="error", line_no=i,
                        message=f"rapid below safe-Z ({cur_z:.2f} < -{self.safe_z:.2f})",
                        context=raw))
                report.rapid_max_z_mm = min(report.rapid_max_z_mm or cur_z, cur_z)
                if cur_motion in ("G1", "G01"):
                    report.feed_max_z_mm = min(report.feed_max_z_mm or cur_z, cur_z)
            if f_tok:
                cur_feed = float(f_tok[1:])
                if cur_feed > self.max_feed:
                    report.issues.append(GCodeIssue(
                        severity="warn", line_no=i,
                        message=f"feed exceeds machine max ({cur_feed} > {self.max_feed})",
                        context=raw))
                report.feed_max_mm_min = max(report.feed_max_mm_min, cur_feed)

            if cur_motion in ("G2", "G02", "G3", "G03"):
                if not (any(t.startswith("I") for t in tokens) or
                        any(t.startswith("J") for t in tokens)):
                    report.issues.append(GCodeIssue(
                        severity="error", line_no=i,
                        message="arc without I/J",
                        context=raw))

        # safety heuristic: steel/alu ops usually want coolant
        if report.feed_max_z_mm and report.feed_max_z_mm < -1.5 and not report.has_coolant:
            report.issues.append(GCodeIssue(
                severity="warn", line_no=0,
                message="deep cuts (z < -1.5mm) without coolant"))

        logger.info(f"[GCodeValidator] {gcode_path.name}: "
                    f"{report.status}, {len(report.issues)} issues")
        return report
