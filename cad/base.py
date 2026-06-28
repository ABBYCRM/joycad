"""CAD engine protocol and registry.

Every CAD engine (FreeCAD, CadQuery, Onshape, Fusion) returns a
``CADGeometry`` so downstream layers (CAM, validation, output) can be
engine-agnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import ClassVar


@dataclass
class CADGeometry:
    step_path: Path
    native_path: Path | None = None
    units: str = "mm"
    bbox_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    volume_mm3: float = 0.0
    surface_area_mm2: float = 0.0
    metadata: dict = None  # type: ignore

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["step_path"] = str(d["step_path"])
        d["native_path"] = str(d["native_path"]) if d["native_path"] else None
        return d


class CADEngine(ABC):
    """Base class every CAD engine inherits from."""

    name: ClassVar[str] = "abstract"

    @abstractmethod
    def execute(self, script_path: Path, out_dir: Path) -> CADGeometry: ...


_REGISTRY: dict[str, type[CADEngine]] = {}


def register_engine(cls: type[CADEngine]) -> type[CADEngine]:
    """Class decorator to auto-register an engine."""
    _REGISTRY[cls.name] = cls
    return cls


def get_engine(name: str) -> CADEngine:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown CAD engine: {name!r}. "
                       f"Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def list_engines() -> list[str]:
    return sorted(_REGISTRY)
