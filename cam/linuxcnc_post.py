"""LinuxCNCPost — emits LinuxCNC-compatible RS-274 G-code.

Works for: LinuxCNC, Machinekit, grbl (most subset), Marlin (subset),
FluidNC. For Fanuc / Haas / Siemens use a custom post.
"""
from __future__ import annotations

from pathlib import Path

from .base import RawToolpaths
from .post_processor import PostProcessor, register_post


@register_post
class LinuxCNCPost(PostProcessor):
    name = "linuxcnc"
    file_extension = ".ngc"

    def post(self, toolpaths: RawToolpaths, out_path: Path,
             machine_config: dict | None = None) -> Path:
        cfg = machine_config or {}
        lines: list[str] = []
        lines.append(self.header_comment(toolpaths.metadata))
        lines.append("G21 G90 G94 G17")           # mm, abs, feed/min, XY plane
        if cfg.get("coolant", "flood") == "flood":
            lines.append("M8")
        elif cfg.get("coolant") == "mist":
            lines.append("M7")
        if cfg.get("spindle_rpm"):
            lines.append(f"S{cfg['spindle_rpm']} M3")

        cur_tool = None
        for mv in toolpaths.moves:
            if mv.tool and mv.tool != cur_tool:
                # tolerate tool id like "T1" or just "1"
                tnum = mv.tool.lstrip("Tt")
                lines.append(f"T{tnum} M6")
                cur_tool = mv.tool
                if mv.rpm:
                    lines.append(f"S{mv.rpm} M3")

            word = {"rapid": "G0", "feed": "G1",
                    "arc_cw": "G2", "arc_ccw": "G3",
                    "plunge": "G1"}[mv.move]
            x = self.fmt(mv.x); y = self.fmt(mv.y); z = self.fmt(mv.z)
            line = f"{word} X{x} Y{y} Z{z}"
            if mv.move in ("arc_cw", "arc_ccw"):
                line += f" I{self.fmt(mv.i)} J{self.fmt(mv.j)}"
            if mv.feed_mm_min:
                line += f" F{self.fmt(mv.feed_mm_min)}"
            lines.append(line)

        lines.append("M5")
        if cfg.get("coolant", "flood") in ("flood", "mist"):
            lines.append("M9")
        lines.append("M2")
        lines.append("%")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines))
        return out_path
