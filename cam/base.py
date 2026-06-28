"""CAM abstractions and registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import ClassVar, Literal


OperationKind = Literal["face", "pocket", "drill", "contour",
                        "adaptive", "engrave", "lathe_rough", "lathe_finish"]


@dataclass
class CAMOperation:
    kind: OperationKind
    tool: str                                 # tool id from ToolDB
    params: dict = field(default_factory=dict)
    # params examples:
    #   pocket  : {depth_mm, stepdown_mm, stepover_mm, stock_mm}
    #   drill   : {x, y, depth_mm, peck_mm}
    #   contour : {depth_mm, offset_mm, finish_pass: bool}


@dataclass
class CAMJob:
    machine: str                              # ref into config/machines/*.yaml
    stock_mm: dict[str, float]                # {x,y,z} of raw stock
    work_offset: str = "G54"
    operations: list[CAMOperation] = field(default_factory=list)
    safe_z_mm: float = 5.0
    spindle_rpm: int | None = None
    coolant: Literal["flood", "mist", "off"] = "flood"


@dataclass
class Toolpath:
    """A single linear / arc move.

    All values in millimetres unless otherwise stated.
    """
    op_kind: OperationKind
    tool: str
    move: Literal["rapid", "feed", "plunge", "arc_cw", "arc_ccw"]
    x: float; y: float; z: float
    i: float = 0.0; j: float = 0.0; k: float = 0.0
    feed_mm_min: float | None = None
    rpm: int | None = None


@dataclass
class RawToolpaths:
    moves: list[Toolpath] = field(default_factory=list)
    estimated_time_min: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"estimated_time_min": self.estimated_time_min,
                "moves": [asdict(m) for m in self.moves],
                "metadata": self.metadata}

    def save_json(self, path: Path) -> None:
        import json
        path.write_text(json.dumps(self.to_dict(), indent=2))


class CAMBackend(ABC):
    name: ClassVar[str] = "abstract"

    @abstractmethod
    def generate(self, step_path: Path, job: CAMJob, out_dir: Path) -> RawToolpaths: ...


_REGISTRY: dict[str, type[CAMBackend]] = {}


def register_cam(cls: type[CAMBackend]) -> type[CAMBackend]:
    _REGISTRY[cls.name] = cls
    return cls


def get_cam(name: str) -> CAMBackend:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown CAM backend: {name!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def list_cams() -> list[str]:
    return sorted(_REGISTRY)
