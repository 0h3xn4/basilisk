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


def test_generate_constellation_writes_new_scenario(tmp_path, capsys):
    path = tmp_path / "template.json"
    _write_scenario(path)
    out_path = tmp_path / "constellation.json"

    rc = cli.main([
        "generate-constellation", str(path), "--out", str(out_path),
        "--total-satellites", "6", "--planes", "2", "--phasing-factor", "1",
        "--altitude-km", "700", "--inclination-deg", "98.0",
    ])
    assert rc == 0
    assert "Generated 6 spacecraft" in capsys.readouterr().out

    from missionstudio.schema import load_scenario

    generated = load_scenario(out_path)
    assert len(generated.spacecraft) == 6
    assert len({sc.name for sc in generated.spacecraft}) == 6
    assert all(sc.orbit.type == "classical_elements" for sc in generated.spacecraft)


def test_generate_constellation_append_keeps_existing_spacecraft(tmp_path, capsys):
    path = tmp_path / "template.json"
    _write_scenario(path)  # one spacecraft named "sat-1"
    out_path = tmp_path / "constellation.json"

    rc = cli.main([
        "generate-constellation", str(path), "--out", str(out_path), "--append",
        "--total-satellites", "2", "--planes", "1", "--phasing-factor", "0",
        "--altitude-km", "700", "--inclination-deg", "0.0",
    ])
    assert rc == 0

    from missionstudio.schema import load_scenario

    generated = load_scenario(out_path)
    assert len(generated.spacecraft) == 3  # original sat-1 + 2 generated
    assert "sat-1" in {sc.name for sc in generated.spacecraft}


def _write_scenario_with_spacecraft(path, spacecraft):
    from missionstudio.schema import GravityConfig, Scenario

    scenario = Scenario(name="cli test scenario", epoch_utc="2030-01-01T00:00:00",
                         gravity=GravityConfig(central_body="earth", central_body_degree=0), spacecraft=spacecraft)
    scenario.save(path)
    return scenario


def test_generate_constellation_requires_template_spacecraft_flag_when_ambiguous(tmp_path, capsys):
    from missionstudio.schema import OrbitIC, SpacecraftConfig

    path = tmp_path / "template.json"
    _write_scenario_with_spacecraft(path, [
        SpacecraftConfig(name="a", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0],
                                                  velocity_km_s=[0, 7.5, 0])),
        SpacecraftConfig(name="b", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0],
                                                  velocity_km_s=[0, 7.5, 0])),
    ])
    rc = cli.main([
        "generate-constellation", str(path), "--out", str(tmp_path / "out.json"),
        "--total-satellites", "2", "--planes", "1", "--phasing-factor", "0",
        "--altitude-km", "700", "--inclination-deg", "0.0",
    ])
    assert rc == 1
    assert "--template-spacecraft" in capsys.readouterr().err


def test_generate_constellation_uses_named_template_spacecraft(tmp_path, capsys):
    from missionstudio.schema import OrbitIC, SpacecraftConfig

    path = tmp_path / "template.json"
    _write_scenario_with_spacecraft(path, [
        SpacecraftConfig(name="a", dry_mass_kg=10.0,
                          orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0])),
        SpacecraftConfig(name="b", dry_mass_kg=99.0,
                          orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0])),
    ])
    out_path = tmp_path / "out.json"
    rc = cli.main([
        "generate-constellation", str(path), "--out", str(out_path), "--template-spacecraft", "b",
        "--total-satellites", "2", "--planes", "1", "--phasing-factor", "0",
        "--altitude-km", "700", "--inclination-deg", "0.0",
    ])
    assert rc == 0

    from missionstudio.schema import load_scenario

    generated = load_scenario(out_path)
    assert all(sc.dry_mass_kg == 99.0 for sc in generated.spacecraft)


def test_generate_constellation_rejects_unknown_template_spacecraft_name(tmp_path, capsys):
    path = tmp_path / "template.json"
    _write_scenario(path)
    rc = cli.main([
        "generate-constellation", str(path), "--out", str(tmp_path / "out.json"),
        "--template-spacecraft", "does-not-exist",
        "--total-satellites", "2", "--planes", "1", "--phasing-factor", "0",
        "--altitude-km", "700", "--inclination-deg", "0.0",
    ])
    assert rc == 1
    assert "does-not-exist" in capsys.readouterr().err


def test_generate_constellation_rejects_invalid_walker_parameters(tmp_path, capsys):
    path = tmp_path / "template.json"
    _write_scenario(path)
    rc = cli.main([
        "generate-constellation", str(path), "--out", str(tmp_path / "out.json"),
        "--total-satellites", "10", "--planes", "3", "--phasing-factor", "0",  # 10 not divisible by 3
        "--altitude-km", "700", "--inclination-deg", "0.0",
    ])
    assert rc == 1
    assert "INVALID" in capsys.readouterr().err


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


def test_run_rejects_both_vizard_flags_at_once(tmp_path, capsys):
    path = tmp_path / "scenario.json"
    _write_scenario(path)
    rc = cli.main([
        "run", str(path), "--out-dir", str(tmp_path / "out"),
        "--vizard-save-file", str(tmp_path / "viz.bin"), "--vizard-live-stream",
    ])
    assert rc == 1
    assert "at most one of" in capsys.readouterr().err


def test_run_parses_vizard_camera_and_orbit_line_flags():
    parser = cli.build_parser()
    args = parser.parse_args([
        "run", "scenario.json",
        "--vizard-live-stream", "--vizard-camera-target", "sat-1", "--vizard-no-orbit-lines",
    ])
    assert args.vizard_camera_target == "sat-1"
    assert args.vizard_no_orbit_lines is True


def test_run_vizard_camera_target_defaults_to_none():
    parser = cli.build_parser()
    args = parser.parse_args(["run", "scenario.json"])
    assert args.vizard_camera_target is None
    assert args.vizard_no_orbit_lines is False


def test_station_keeping_summary_reports_delta_v_and_propellant_used(capsys):
    import numpy as np

    from missionstudio.engine.results import ResultSet, TimeSeries
    from missionstudio.schema import GravityConfig, OrbitIC, Scenario, SpacecraftConfig, StationKeepingConfig

    scenario = Scenario(
        name="sk test", epoch_utc="2030-01-01T00:00:00", gravity=GravityConfig(),
        spacecraft=[SpacecraftConfig(
            name="sat-1",
            orbit=OrbitIC(type="cartesian", position_km=[7000.0, 0.0, 0.0], velocity_km_s=[0.0, 7.5, 0.0]),
            station_keeping=StationKeepingConfig(target_altitude_km=500.0, deadband_km=1.0, thrust_n=0.01,
                                                  isp_s=1500.0, propellant_kg=2.0),
        )],
    )
    result = ResultSet(scenario_name="sk test")
    t = np.array([0.0, 100.0, 200.0])
    result.add(TimeSeries("sat-1.station_keeping.delta_v", t, ("cumulative_delta_v",),
                           np.array([[0.0], [0.5], [1.25]]), units="m/s"))
    result.add(TimeSeries("sat-1.station_keeping.propellant_remaining", t, ("propellant_remaining",),
                           np.array([[2.0], [1.9], [1.75]]), units="kg"))

    cli._print_station_keeping_summary(scenario, result)
    out = capsys.readouterr().out
    assert "sat-1" in out
    assert "1.250 m/s delta-V" in out
    assert "0.250 kg propellant used" in out
    assert "1.750 kg remaining" in out


def test_station_keeping_summary_skips_spacecraft_without_the_config(capsys):
    from missionstudio.engine.results import ResultSet
    from missionstudio.schema import GravityConfig, OrbitIC, Scenario, SpacecraftConfig

    scenario = Scenario(
        name="no sk", epoch_utc="2030-01-01T00:00:00", gravity=GravityConfig(),
        spacecraft=[SpacecraftConfig(
            name="sat-1",
            orbit=OrbitIC(type="cartesian", position_km=[7000.0, 0.0, 0.0], velocity_km_s=[0.0, 7.5, 0.0]),
        )],
    )
    result = ResultSet(scenario_name="no sk")

    cli._print_station_keeping_summary(scenario, result)
    assert capsys.readouterr().out == ""


def test_monte_carlo_rejects_scenario_without_enabled_flag(tmp_path, capsys):
    path = tmp_path / "scenario.json"
    _write_scenario(path)  # monte_carlo.enabled defaults to False
    rc = cli.main(["monte-carlo", str(path), "--archive-dir", str(tmp_path / "mc")])
    assert rc == 1
    assert "monte_carlo.enabled is false" in capsys.readouterr().err


@pytest.mark.skipif(_BASILISK_AVAILABLE, reason="this test's premise is specifically that Basilisk is unavailable")
def test_monte_carlo_without_basilisk_reports_clear_error(tmp_path, capsys):
    from missionstudio.schema import MonteCarloConfig

    path = tmp_path / "scenario.json"
    _write_scenario(path, monte_carlo=MonteCarloConfig(enabled=True, num_runs=2))
    rc = cli.main(["monte-carlo", str(path), "--archive-dir", str(tmp_path / "mc")])
    assert rc == 2
    assert "Basilisk is not installed" in capsys.readouterr().err


def test_no_subcommand_is_an_error():
    with pytest.raises(SystemExit):
        cli.main([])


def test_unknown_scenario_file_is_a_clear_error(tmp_path, capsys):
    rc = cli.main(["validate", str(tmp_path / "does_not_exist.json")])
    assert rc == 1
    assert "INVALID" in capsys.readouterr().err
