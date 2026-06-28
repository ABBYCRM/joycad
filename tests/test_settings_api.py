"""Settings & API tests.

Tests the Settings dataclass, presets, and the 11 new /v1/* endpoints.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("JOYCAD_LLM_PROVIDER", "mock")

from orchestrator.settings import PRESETS, Settings, get_preset, list_presets
from orchestrator.api import create_app


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------
def test_settings_defaults():
    s = Settings.default()
    assert s.machine == "linuxcnc_3axis"
    assert s.llm_provider == "mock"
    assert s.process == "cnc_mill"
    assert s.cad_engine == "cadquery"
    assert s.cam_backend == "cadquery_cam"
    assert s.coolant == "flood"
    assert s.safe_z_mm == 5.0
    assert s.spindle_rpm == 12000
    assert "fea" in s.validators_enabled
    assert "step" in s.export_formats


def test_settings_round_trip_yaml(tmp_path):
    s = Settings.default()
    s.machine = "marlin_fdm"
    s.process = "3d_print_fdm"
    s.coolant = "off"
    p = tmp_path / "settings.yaml"
    s.save(p)
    loaded = Settings.default()
    assert loaded.machine == "linuxcnc_3axis"   # default still
    # but our saved file has the new values
    import yaml
    data = yaml.safe_load(p.read_text())
    assert data["machine"] == "marlin_fdm"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("JOYCAD_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("JOYCAD_DEFAULT_MACHINE", "grbl_3018")
    s = Settings.default()
    assert s.llm_provider == "ollama"
    assert s.machine == "grbl_3018"


def test_settings_from_request_preserves_extras():
    req = {"machine": "marlin_fdm", "unknown_field": "preserved",
           "future_knob": 42}
    s = Settings.from_request(req)
    assert s.machine == "marlin_fdm"
    assert "unknown_field" in s.extra_context
    assert "future_knob" in s.extra_context


def test_presets_listed():
    presets = list_presets()
    assert len(presets) >= 3
    names = {p["name"] for p in presets}
    assert "mvp-mock" in names
    assert "fdm-print" in names


def test_preset_mvp_mock():
    s = get_preset("mvp-mock")
    assert s is not None
    assert s.llm_provider == "mock"
    assert s.cad_engine == "cadquery"


def test_preset_unknown_returns_none():
    assert get_preset("nonexistent") is None


def test_preset_fdm_print():
    s = get_preset("fdm-print")
    assert s is not None
    assert s.machine == "marlin_fdm"
    assert s.process == "3d_print_fdm"
    assert s.write_3d_print_gcode is True


def test_settings_to_dict_is_json_safe():
    s = Settings.default()
    json.dumps(s.to_dict())    # must not raise


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_root_lists_endpoints(client):
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert "endpoints" in data
    assert "/v1/pipeline" in data["endpoints"]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_v1_info(client):
    r = client.get("/v1/info")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "JoyCAD"
    assert "cad_engines" in data
    assert "cam_backends" in data
    assert "presets" in data
    assert isinstance(data["processes"], list)
    assert isinstance(data["machine_configs"], list)


def test_v1_capabilities_reports_runtime(client):
    r = client.get("/v1/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert "python" in data
    assert "executables_on_path" in data
    assert "python_modules" in data
    assert "llm_providers_available" in data


def test_v1_settings_default(client):
    r = client.get("/v1/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["machine"] == "linuxcnc_3axis"
    assert data["llm_provider"] == "mock"


def test_v1_settings_validate_accepts_known(client):
    r = client.post("/v1/settings/validate",
                    json={"machine": "marlin_fdm", "coolant": "off",
                          "safe_z_mm": 3.0})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["settings"]["machine"] == "marlin_fdm"
    assert "machine" in data["diff_from_defaults"]


def test_v1_settings_validate_preserves_extras(client):
    r = client.post("/v1/settings/validate",
                    json={"machine": "grbl_3018",
                          "totally_unknown_field": "kept-as-context"})
    assert r.status_code == 200
    data = r.json()
    assert "totally_unknown_field" in data["settings"]["extra_context"]


def test_v1_engines_legacy(client):
    r = client.get("/v1/engines")
    assert r.status_code == 200
    data = r.json()
    assert "cad_engines" in data
    assert "cam_backends" in data


def test_v1_machines(client):
    r = client.get("/v1/machines")
    assert r.status_code == 200
    data = r.json()
    assert any(m["id"] == "linuxcnc_3axis" for m in data["machines"])
    assert "default_tool_db" in data


def test_v1_materials(client):
    r = client.get("/v1/materials")
    assert r.status_code == 200
    data = r.json()
    assert any(m["id"] == "6061-t6" for m in data["materials"])


def test_v1_processes(client):
    r = client.get("/v1/processes")
    assert r.status_code == 200
    data = r.json()
    assert any(p["id"] == "cnc_mill" for p in data["processes"])


def test_v1_presets_list(client):
    r = client.get("/v1/presets")
    assert r.status_code == 200
    data = r.json()
    assert len(data["presets"]) >= 3


def test_v1_preset_detail(client):
    r = client.get("/v1/presets/fdm-print")
    assert r.status_code == 200
    data = r.json()
    assert data["machine"] == "marlin_fdm"


def test_v1_preset_detail_unknown_404(client):
    r = client.get("/v1/presets/nonexistent")
    assert r.status_code == 404


def test_v1_examples(client):
    r = client.get("/v1/examples")
    assert r.status_code == 200
    data = r.json()
    assert len(data["examples"]) >= 4
    for ex in data["examples"]:
        assert "intent" in ex
        assert "preset" in ex


def test_v1_run_legacy(client):
    """Legacy /v1/run still works (backward compat)."""
    r = client.post("/v1/run", json={
        "intent": "a 50 mm L-bracket, 6 mm thick, four M6 holes, 6061-T6",
        "skip_validation": True,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True


def test_v1_pipeline_requires_intent(client):
    r = client.post("/v1/pipeline", json={"machine": "linuxcnc_3axis"})
    assert r.status_code == 400


def test_v1_pipeline_preset_applies(client):
    """When preset is specified, preset values are honored."""
    r = client.post("/v1/pipeline", json={
        "preset": "fdm-print",
        "intent": "a 60 x 40 x 20 mm enclosure, ABS",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["settings_used"]["machine"] == "marlin_fdm"
    assert data["settings_used"]["process"] == "3d_print_fdm"
    assert data["settings_used"]["write_3d_print_gcode"] is True


def test_v1_pipeline_overrides_preset(client):
    """Explicit fields override the preset."""
    r = client.post("/v1/pipeline", json={
        "preset": "fdm-print",
        "intent": "enclosure",
        "machine": "linuxcnc_3axis",     # override
        "process": "cnc_mill",           # override
    })
    assert r.status_code == 200
    data = r.json()
    assert data["settings_used"]["machine"] == "linuxcnc_3axis"
    assert data["settings_used"]["process"] == "cnc_mill"


def test_v1_pipeline_unknown_preset_400(client):
    r = client.post("/v1/pipeline", json={
        "preset": "does-not-exist",
        "intent": "x",
    })
    assert r.status_code == 400
