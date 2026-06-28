"""ToolDB — typed catalog of cutting tools.

Used by CAM planners to pick sensible tools / feeds / speeds and by the
post-processor to emit the right T<num> M6 tool changes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml


@dataclass
class Tool:
    id: str                           # "T1", "T2", ...
    type: str                         # endmill | ball | vbit | drill | tap | lathe_tool
    diameter_mm: float
    flutes: int = 2
    material: str = "carbide"         # HSS | carbide | diamond
    coating: str = ""
    max_rpm: int = 24000
    feed_per_tooth_mm: float = 0.04
    description: str = ""


@dataclass
class ToolDB:
    tools: list[Tool] = field(default_factory=list)

    def get(self, tool_id: str) -> Tool | None:
        for t in self.tools:
            if t.id == tool_id:
                return t
        return None

    def add(self, tool: Tool) -> None:
        self.tools.append(tool)

    def save(self, path: Path) -> None:
        path.write_text(yaml.safe_dump([asdict(t) for t in self.tools]))

    @classmethod
    def load(cls, path: Path) -> "ToolDB":
        data = yaml.safe_load(path.read_text())
        return cls(tools=[Tool(**t) for t in data])


def default_tool_db() -> ToolDB:
    return ToolDB(tools=[
        Tool(id="T1", type="endmill", diameter_mm=6.0, flutes=2,
             description="6mm carbide endmill — facing, profiling"),
        Tool(id="T2", type="endmill", diameter_mm=3.0, flutes=2,
             description="3mm carbide endmill — fine pockets"),
        Tool(id="T3", type="drill",   diameter_mm=6.6, flutes=2,
             description="6.6mm drill — M6 clearance"),
        Tool(id="T4", type="endmill", diameter_mm=10.0, flutes=4,
             description="10mm carbide endmill — bulk roughing"),
        Tool(id="T5", type="ball",    diameter_mm=6.0, flutes=2,
             description="6mm ball endmill — 3D surfacing"),
        Tool(id="T6", type="vbit",    diameter_mm=12.0, flutes=2,
             description="60° V-bit — engraving"),
    ])
