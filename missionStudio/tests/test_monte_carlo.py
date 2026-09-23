"""Tests for missionstudio.engine.monte_carlo.run_monte_carlo(). Needs a
Basilisk build to import (Basilisk.utilities.MonteCarlo.* at module level);
see tests/conftest.py for the auto-skip behavior in this development
sandbox, which does not have one.
"""

import pytest

from missionstudio.schema import GravityConfig, MonteCarloConfig, OrbitIC, Scenario, SpacecraftConfig
from missionstudio.schema.scenario import ConstantThrustConfig, DispersionConfig, StationKeepingConfig

pytestmark = pytest.mark.requires_basilisk


def _scenario(**spacecraft_overrides):
    return Scenario(
        name="mc test scenario",
        epoch_utc="2030-01-01T00:00:00",
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        spacecraft=[SpacecraftConfig(
            name="sat-1", dry_mass_kg=100.0,
            orbit=OrbitIC(type="cartesian", position_km=[7000.0, 0.0, 0.0], velocity_km_s=[0.0, 7.5, 0.0]),
            **spacecraft_overrides,
        )],
        monte_carlo=MonteCarloConfig(enabled=True, num_runs=1),
    )


def test_run_monte_carlo_reports_a_clean_error_when_archive_dir_is_a_file(tmp_path):
    """Regression test for an audit finding: archive_dir.mkdir(...) used to
    sit outside run_monte_carlo()'s own try/except (which only wrapped
    controller.executeSimulations()), so pointing --archive-dir at a path
    that already exists as a plain file raised a bare FileExistsError
    instead of this module's usual MonteCarloError.
    """
    from missionstudio.engine.monte_carlo import MonteCarloError, run_monte_carlo

    archive_dir = tmp_path / "already_a_file"
    archive_dir.write_text("not a directory")

    with pytest.raises(MonteCarloError, match="could not create Monte Carlo archive directory"):
        run_monte_carlo(_scenario(), MonteCarloConfig(enabled=True, num_runs=1), archive_dir)


def test_propellant_offset_kg_sums_station_keeping_and_constant_thrust():
    from missionstudio.engine.monte_carlo import _propellant_offset_kg

    sc = SpacecraftConfig(
        name="s", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]),
        station_keeping=StationKeepingConfig(
            target_altitude_km=500, deadband_km=1, thrust_n=0.1, isp_s=200, propellant_kg=10.0),
        constant_thrust=ConstantThrustConfig(propellant_kg=2.0),
    )
    assert _propellant_offset_kg(sc) == 12.0


def test_propellant_offset_kg_is_zero_with_neither_configured():
    from missionstudio.engine.monte_carlo import _propellant_offset_kg

    sc = SpacecraftConfig(name="s", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0],
                                                    velocity_km_s=[0, 7.5, 0]))
    assert _propellant_offset_kg(sc) == 0.0


def test_dry_mass_dispersion_adds_propellant_offset_on_top():
    """Regression test for an audit finding: Basilisk's dispersion classes
    write their generated value ABSOLUTELY to hub.mHub, with no way to add
    anything on top -- but hub.mHub is dry_mass_kg + propellant for a
    spacecraft with station_keeping/constant_thrust configured (see
    service.py's own initial_mass_kg computation), not just dry_mass_kg.
    A plain dispersion on "dry_mass_kg" would therefore silently disperse
    the TOTAL mass under that name instead of just the dry mass.
    """
    from missionstudio.engine.monte_carlo import _build_dispersion

    scenario = _scenario(station_keeping=StationKeepingConfig(
        target_altitude_km=500, deadband_km=1, thrust_n=0.1, isp_s=200, propellant_kg=10.0))
    dispersion = DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="uniform", bounds=[90.0, 110.0])

    disp = _build_dispersion(dispersion, scenario)
    for _ in range(50):
        value = disp.generate(sim=None)
        assert 100.0 <= value <= 120.0  # [90, 110] dry-mass bounds + 10 kg propellant offset


def test_dry_mass_dispersion_with_no_propellant_is_unshifted():
    from missionstudio.engine.monte_carlo import _build_dispersion

    scenario = _scenario()  # no station_keeping/constant_thrust
    dispersion = DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="uniform", bounds=[90.0, 110.0])

    disp = _build_dispersion(dispersion, scenario)
    for _ in range(50):
        value = disp.generate(sim=None)
        assert 90.0 <= value <= 110.0


def test_dry_mass_normal_dispersion_adds_propellant_offset_on_top():
    from missionstudio.engine.monte_carlo import _build_dispersion

    scenario = _scenario(constant_thrust=ConstantThrustConfig(propellant_kg=5.0))
    dispersion = DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="normal",
                                   mean=100.0, std_deviation=0.001)

    disp = _build_dispersion(dispersion, scenario)
    value = disp.generate(sim=None)
    assert value == pytest.approx(105.0, abs=0.1)  # mean 100 + 5 kg propellant offset


def test_build_dispersion_unknown_spacecraft_raises_clear_error():
    from missionstudio.engine.monte_carlo import MonteCarloError, _build_dispersion

    scenario = _scenario()
    dispersion = DispersionConfig(spacecraft="does-not-exist", quantity="dry_mass_kg", kind="uniform",
                                   bounds=[90.0, 110.0])

    with pytest.raises(MonteCarloError, match="does-not-exist"):
        _build_dispersion(dispersion, scenario)
