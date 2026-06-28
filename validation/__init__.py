"""JoyCAD validation layer.

Four checks run in parallel after geometry + toolpaths are ready:
    1. FEA        (CalculiX / FElupe)        — does it survive the loads?
    2. Collision  (FCL or AABB fallback)     — does the tool hit anything?
    3. DFM        (rule engine)               — is it actually buildable?
    4. Tolerance  (TolStack)                  — does the assembly hold?

Collision backend is chosen at import time:
    - If `fcl` (python-fcl) is importable → CollisionValidator (FCL).
    - Otherwise → AABBCollisionValidator (pure Python, checks toolpath
      moves against the stock bounding box).
On Render's Python 3.14 sandbox, FCL has no prebuilt wheel and the
build from source is impractical, so the AABB fallback runs by default.
"""
from .base import (ValidationReport, register_validator, get_validator,
                   list_validators)
from .fea_calculix import FEAValidator
from .dfm import DFMValidator, DFMRules
from .tolerance_stack import ToleranceValidator

# Pick the best collision backend available in this runtime.
import importlib.util as _iu
if _iu.find_spec("fcl") is not None:
    from .collision_fcl import CollisionValidator  # noqa: F401
    _COLLISION_BACKEND = "fcl"
else:
    from .collision_aabb import AABBCollisionValidator as CollisionValidator  # noqa: F401
    _COLLISION_BACKEND = "aabb"


def collision_backend() -> str:
    """Return the active collision backend name ('fcl' or 'aabb')."""
    return _COLLISION_BACKEND


__all__ = [
    "ValidationReport", "register_validator", "get_validator", "list_validators",
    "FEAValidator", "CollisionValidator",
    "DFMValidator", "DFMRules", "ToleranceValidator",
    "collision_backend",
]
