"""Validation abstractions and registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar


@dataclass
class ValidationReport:
    name: str
    status: str                     # "pass" | "warn" | "fail" | "skipped"
    metrics: dict[str, Any] = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)   # file paths

    def to_dict(self) -> dict:
        return asdict(self)


class Validator(ABC):
    name: ClassVar[str] = "abstract"

    @abstractmethod
    def validate(self, **kwargs) -> ValidationReport: ...


_REGISTRY: dict[str, type[Validator]] = {}


def register_validator(cls: type[Validator]) -> type[Validator]:
    _REGISTRY[cls.name] = cls
    return cls


def get_validator(name: str) -> Validator:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown validator: {name!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def list_validators() -> list[str]:
    return sorted(_REGISTRY)
