"""Tests for missionstudio.cli. ``validate`` and ``spaceweather-resolve``
need no Basilisk build and run unconditionally; the ``run``/
``kernels-status`` tests here specifically check the graceful
no-Basilisk error path, so they're skipped on a machine that DOES have
Basilisk (where that premise doesn't hold) -- see ``conftest.py`` for the
general ``requires_basilisk``/``requires_gui`` markers this mirrors
inline for the same reason.
"""

import importlib.util
import json

import pytest

from missionstudio import cli

_BASILISK_AVAILABLE = importlib.util.find_spec("Basilisk") is not None


def _write_scenario(path, **overrides):
    from missionstudio.schema import GravityConfig, OrbitIC, Scenario, SpacecraftConfig

    scenario = Scenario(
        name=overrides.pop("name", "cli test scenario"),
        epoch_utc=overrides.pop("epoch_utc", "2030-01-01T00:00:00"),
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        spacecraft=[SpacecraftConfig(
            name="sat-1",
            orbit=OrbitIC(type="cartesian", position_km=[7000.0, 0.0, 0.0], velocity_km_s=[0.0, 7.5, 0.0]),
        )],
        **overrides,
    )
    scenario.save(path)
    return scenario


def test_validate_accepts_a_valid_scenario(tmp_path, capsys):
    path = tmp_path / "scenario.json"
    _write_scenario(path)
    rc = cli.main(["validate", str(path)])
    assert rc == 0
    assert "OK:" in capsys.readouterr().out


def test_validate_rejects_an_invalid_scenario(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": 1, "name": "", "epoch_utc": "2030-01-01T00:00:00"}))
    rc = cli.main(["validate", str(path)])
    assert rc == 1
    assert "INVALID" in capsys.readouterr().err


def test_validate_rejects_malformed_json(tmp_path, capsys):
    path = tmp_path / "malformed.json"
    path.write_text("{not json")
    rc = cli.main(["validate", str(path)])
    assert rc == 1
    assert "INVALID" in capsys.readouterr().err


def test_spaceweather_resolve_reports_resolution(tmp_path, capsys):
    path = tmp_path / "scenario.json"
    _write_scenario(path)
    rc = cli.main(["spaceweather-resolve", str(path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Resolved to:" in out
    assert "Synthetic:" in out


@pytest.mark.skipif(_BASILISK_AVAILABLE, reason="this test's premise is specifically that Basilisk is unavailable")
def test_run_without_basilisk_reports_clear_error(tmp_path, capsys):
    path = tmp_path / "scenario.json"
    _write_scenario(path)
    rc = cli.main(["run", str(path), "--out-dir", str(tmp_path / "out")])
    assert rc == 2
    assert "Basilisk is not installed" in capsys.readouterr().err


@pytest.mark.skipif(_BASILISK_AVAILABLE, reason="this test's premise is specifically that Basilisk is unavailable")
def test_kernels_status_without_basilisk_reports_clear_error(capsys):
    rc = cli.main(["kernels-status"])
    assert rc == 2
    assert "Basilisk is not installed" in capsys.readouterr().err


def test_no_subcommand_is_an_error():
    with pytest.raises(SystemExit):
        cli.main([])


def test_unknown_scenario_file_is_a_clear_error(tmp_path, capsys):
    rc = cli.main(["validate", str(tmp_path / "does_not_exist.json")])
    assert rc == 1
    assert "INVALID" in capsys.readouterr().err
