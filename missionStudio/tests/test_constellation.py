"""Tests for missionstudio.engine.constellation -- no Basilisk import, runs
anywhere. Checks the Walker-pattern math directly (RAAN/mean-anomaly
spacing, semi-major axis) rather than just "it doesn't crash".
"""

import pytest

from missionstudio.engine.constellation import (
    CENTRAL_BODY_EQUATORIAL_RADIUS_KM,
    SeparationSchedule,
    WalkerConstellationRequest,
    generate_walker_constellation,
)
from missionstudio.schema.scenario import OrbitIC, PowerConfig, ScenarioValidationError, SpacecraftConfig


def _template(**overrides):
    defaults = dict(
        name="template", dry_mass_kg=50.0,
        orbit=OrbitIC(type="cartesian", position_km=[7000.0, 0.0, 0.0], velocity_km_s=[0.0, 7.5, 0.0]),
    )
    defaults.update(overrides)
    return SpacecraftConfig(**defaults)


def _request(**overrides):
    defaults = dict(total_satellites=12, num_planes=3, phasing_factor=1, altitude_km=780.0, inclination_deg=86.4)
    defaults.update(overrides)
    return WalkerConstellationRequest(**defaults)


def test_generates_total_satellites_count():
    sats = generate_walker_constellation(_request(), _template())
    assert len(sats) == 12
    assert len({s.name for s in sats}) == 12  # every name unique


def test_semi_major_axis_matches_altitude_plus_earth_radius():
    sats = generate_walker_constellation(_request(altitude_km=500.0), _template())
    expected_sma = CENTRAL_BODY_EQUATORIAL_RADIUS_KM["earth"] + 500.0
    for s in sats:
        assert s.orbit.semi_major_axis_km == pytest.approx(expected_sma)


def test_raan_spacing_is_360_over_planes_for_delta_pattern():
    sats = generate_walker_constellation(_request(total_satellites=6, num_planes=3, phasing_factor=0), _template())
    raans = sorted({s.orbit.raan_deg for s in sats})
    assert raans == pytest.approx([0.0, 120.0, 240.0])


def test_raan_spacing_is_180_over_planes_for_star_pattern():
    sats = generate_walker_constellation(
        _request(total_satellites=6, num_planes=3, phasing_factor=0, pattern="star"), _template()
    )
    raans = sorted({s.orbit.raan_deg for s in sats})
    assert raans == pytest.approx([0.0, 60.0, 120.0])


def test_mean_anomaly_spacing_within_one_plane():
    sats = generate_walker_constellation(_request(total_satellites=8, num_planes=2, phasing_factor=0), _template())
    plane1_anomalies = sorted(s.orbit.mean_anomaly_deg for s in sats if s.orbit.raan_deg == 0.0)
    assert plane1_anomalies == pytest.approx([0.0, 90.0, 180.0, 270.0])


def test_phasing_factor_offsets_adjacent_planes():
    # T=8, P=2, F=1 -> phase offset between planes = F * 360/T = 45 deg
    sats = generate_walker_constellation(_request(total_satellites=8, num_planes=2, phasing_factor=1), _template())
    plane0 = sorted(s.orbit.mean_anomaly_deg for s in sats if s.orbit.raan_deg == 0.0)
    plane1 = sorted(s.orbit.mean_anomaly_deg for s in sats if s.orbit.raan_deg == 180.0)
    assert plane0 == pytest.approx([0.0, 90.0, 180.0, 270.0])
    assert plane1 == pytest.approx([45.0, 135.0, 225.0, 315.0])


def test_raan_offset_rotates_whole_constellation():
    sats = generate_walker_constellation(
        _request(total_satellites=6, num_planes=3, phasing_factor=0, raan_offset_deg=30.0), _template()
    )
    raans = sorted({s.orbit.raan_deg for s in sats})
    assert raans == pytest.approx([30.0, 150.0, 270.0])


def test_orbit_uses_mean_anomaly_not_true_anomaly():
    sats = generate_walker_constellation(_request(), _template())
    for s in sats:
        assert s.orbit.anomaly_type == "mean"
        assert s.orbit.true_anomaly_deg is None
        assert s.orbit.mean_anomaly_deg is not None


def test_template_fields_other_than_name_and_orbit_are_preserved():
    template = _template(dry_mass_kg=123.0, power=PowerConfig(panel_area_m2=1.5, panel_efficiency=0.3))
    sats = generate_walker_constellation(_request(total_satellites=4, num_planes=2, phasing_factor=0), template)
    for s in sats:
        assert s.dry_mass_kg == 123.0
        assert s.power == template.power
        assert s.power is not template.power  # deep-copied, not shared


def test_generated_names_are_deterministic_and_prefixed():
    sats = generate_walker_constellation(_request(total_satellites=4, num_planes=2, name_prefix="iridium"),
                                          _template())
    assert {s.name for s in sats} == {"iridium-01-01", "iridium-01-02", "iridium-02-01", "iridium-02-02"}


def test_generated_scenario_validates(tmp_path):
    from missionstudio.schema.scenario import GravityConfig, Scenario

    sats = generate_walker_constellation(_request(total_satellites=4, num_planes=2), _template())
    scenario = Scenario(name="walker test", epoch_utc="2030-01-01T00:00:00",
                         gravity=GravityConfig(central_body="earth"), spacecraft=sats)
    scenario.validate()  # must not raise
    scenario.save(tmp_path / "walker.json")  # round-trips through JSON cleanly


@pytest.mark.parametrize("overrides,match", [
    (dict(total_satellites=0), "total_satellites"),
    (dict(num_planes=0), "num_planes"),
    (dict(total_satellites=10, num_planes=3), "evenly divisible"),
    (dict(phasing_factor=3), "phasing_factor"),
    (dict(altitude_km=0.0), "altitude_km"),
    (dict(inclination_deg=200.0), "inclination_deg"),
    (dict(eccentricity=1.0), "eccentricity"),
    (dict(pattern="triangle"), "pattern"),
    (dict(central_body="pluto"), "central_body"),
    (dict(name_prefix="  "), "name_prefix"),
])
def test_request_validation_rejects_bad_input(overrides, match):
    with pytest.raises(ScenarioValidationError, match=match):
        _request(**overrides).validate()


# -- SeparationSchedule -----------------------------------------------------

def test_separation_schedule_rejects_empty_distances():
    with pytest.raises(ValueError, match="at least one distance"):
        SeparationSchedule(distances_km=[], interval_days=90.0, semi_major_axis_m=7.0e6)


def test_separation_schedule_single_entry_holds_for_whole_mission():
    schedule = SeparationSchedule(distances_km=[100.0], interval_days=90.0, semi_major_axis_m=7.0e6)
    expected = 100.0 * 1000.0 / 7.0e6
    assert schedule.value_at(0.0) == pytest.approx(expected)
    assert schedule.value_at(1.0e9) == pytest.approx(expected)  # far beyond any interval -- still holds


def test_separation_schedule_steps_through_distances_on_schedule():
    a_m = 7.0e6
    schedule = SeparationSchedule(distances_km=[1000.0, 500.0, 100.0], interval_days=90.0, semi_major_axis_m=a_m)
    day_s = 86400.0

    assert schedule.value_at(0.0) == pytest.approx(1000.0 * 1000.0 / a_m)
    assert schedule.value_at(89.0 * day_s) == pytest.approx(1000.0 * 1000.0 / a_m)
    assert schedule.value_at(90.0 * day_s) == pytest.approx(500.0 * 1000.0 / a_m)
    assert schedule.value_at(179.0 * day_s) == pytest.approx(500.0 * 1000.0 / a_m)
    assert schedule.value_at(180.0 * day_s) == pytest.approx(100.0 * 1000.0 / a_m)


def test_separation_schedule_holds_at_last_entry_when_not_looping():
    a_m = 7.0e6
    schedule = SeparationSchedule(distances_km=[1000.0, 500.0, 100.0], interval_days=90.0, semi_major_axis_m=a_m,
                                   loop=False)
    day_s = 86400.0
    far_future = 1000.0 * day_s
    assert schedule.value_at(far_future) == pytest.approx(100.0 * 1000.0 / a_m)


def test_separation_schedule_loops_when_requested():
    a_m = 7.0e6
    schedule = SeparationSchedule(distances_km=[1000.0, 500.0, 100.0], interval_days=90.0, semi_major_axis_m=a_m,
                                   loop=True)
    day_s = 86400.0
    # index 3 (0-based) wraps back to index 0
    assert schedule.value_at(3 * 90.0 * day_s) == pytest.approx(1000.0 * 1000.0 / a_m)
    assert schedule.value_at(4 * 90.0 * day_s) == pytest.approx(500.0 * 1000.0 / a_m)


def test_separation_schedule_zero_interval_holds_first_entry():
    schedule = SeparationSchedule(distances_km=[1000.0, 500.0], interval_days=0.0, semi_major_axis_m=7.0e6)
    assert schedule.value_at(0.0) == pytest.approx(1000.0 * 1000.0 / 7.0e6)
    assert schedule.value_at(1.0e9) == pytest.approx(1000.0 * 1000.0 / 7.0e6)
