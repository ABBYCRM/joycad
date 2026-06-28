"""Post-processors — convert neutral RawToolpaths into machine G-code.

Each machine gets a Python class that emits its dialect of G-code.
We start with LinuxCNC (covers grbl, Marlin, FluidNC variants too).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from loguru import logger

from .base import RawToolpaths


class PostProcessor(ABC):
    name: ClassVar[str] = "abstract"
    file_extension: ClassVar[str] = ".ngc"

    @abstractmethod
    def post(self, toolpaths: RawToolpaths, out_path: Path,
             machine_config: dict | None = None) -> Path: ...

    # common helpers -----------------------------------------------------
    @staticmethod
    def header_comment(meta: dict) -> str:
        import datetime
        lines = [
            "%",
            f"; JoyCAD post-processor output",
            f"; date: {datetime.datetime.utcnow().isoformat()}Z",
            f"; engine: {meta.get('engine','?')}",
            f"; est time: {meta.get('estimated_time_min', 0):.1f} min",
            "%",
        ]
        return "\n".join(lines)

    @staticmethod
    def fmt(x: float) -> str:
        # 3 decimal places is plenty for mm; CAD/CAM convention.
        return f"{x:.3f}"


_REGISTRY: dict[str, type[PostProcessor]] = {}


def get_post_processor(name: str) -> PostProcessor:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown post-processor: {name!r}. "
                       f"Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def register_post(cls: type[PostProcessor]) -> type[PostProcessor]:
    _REGISTRY[cls.name] = cls
    return cls
