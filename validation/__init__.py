"""JoyCAD validation layer.

Four checks run in parallel after geometry + toolpaths are ready:
    1. FEA        (CalculiX / FElupe)        — does it survive the loads?
    2. Collision  (FCL)                       — does the tool hit anything?
    3. DFM        (rule engine)               — is it actually buildable?
    4. Tolerance  (TolStack)                  — does the assembly hold?
"""
from .base import (ValidationReport, register_validator, get_validator,
                   list_validators)
from .fea_calculix import FEAValidator
from .collision_fcl import CollisionValidator
from .dfm import DFMValidator, DFMRules
from .tolerance_stack import ToleranceValidator

__all__ = [
    "ValidationReport", "register_validator", "get_validator", "list_validators",
    "FEAValidator", "CollisionValidator", "DFMValidator", "DFMRules",
    "ToleranceValidator",
]
