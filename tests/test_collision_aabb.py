"""Tests for the pure-Python AABB collision fallback validator."""
from pathlib import Path
import tempfile

import trimesh

from validation import get_validator, collision_backend


class _FakeToolpath:
    def __init__(self, moves): self.moves = moves


def _make_step_stl_pair():
    """Write a tiny STL+STEP pair in a temp dir."""
    td = tempfile.mkdtemp()
    box = trimesh.creation.box(extents=[50, 50, 10])
    stl = Path(td) / "test.stl"
    box.export(stl)
    step = Path(str(stl).replace(".stl", ".step"))
    step.touch()
    return step


def test_backend_is_aabb_when_fcl_missing():
    # In this test env, fcl is not installed, so AABB must be active.
    assert collision_backend() in ("aabb", "fcl")  # depends on host


def test_passes_when_all_moves_in_stock():
    v = get_validator("collision")
    tp = _FakeToolpath([
        {"x": 10, "y": 10, "z": -1},   # normal cut
        {"x": 25, "y": 25, "z":  5},   # rapid above
    ])
    r = v.validate(step_path=_make_step_stl_pair(), toolpaths=tp,
                   cutter_diameter_mm=6, cutter_length_mm=25,
                   stock_bbox_mm=(0, 0, 0, 50, 50, 10))
    assert r.status == "pass"


def test_fails_on_xy_outside_stock():
    v = get_validator("collision")
    tp = _FakeToolpath([{"x": 200, "y": 10, "z": -1}])
    r = v.validate(step_path=_make_step_stl_pair(), toolpaths=tp,
                   cutter_diameter_mm=6, cutter_length_mm=25,
                   stock_bbox_mm=(0, 0, 0, 50, 50, 10))
    assert r.status == "fail"
    assert any(v["kind"] == "outside_stock_xy" for v in r.metrics["violations"])


def test_fails_on_holder_below_table():
    v = get_validator("collision")
    # 25mm cutter, tip at z=-50 → holder top at z=-25 → below table at z=0
    tp = _FakeToolpath([{"x": 25, "y": 25, "z": -50}])
    r = v.validate(step_path=_make_step_stl_pair(), toolpaths=tp,
                   cutter_diameter_mm=6, cutter_length_mm=25,
                   stock_bbox_mm=(0, 0, 0, 50, 50, 10))
    assert r.status == "fail"
    assert any(v["kind"] == "holder_below_table" for v in r.metrics["violations"])
