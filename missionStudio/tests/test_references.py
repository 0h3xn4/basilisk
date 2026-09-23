"""Tests for missionstudio.schema.references -- no Basilisk import, runs
anywhere.
"""

import pytest

from missionstudio.schema.command import Command
from missionstudio.schema.references import (
    ReferenceError,
    find_ground_station_references,
    find_spacecraft_references,
    rename_ground_station,
    rename_spacecraft,
)
from missionstudio.schema.scenario import (
    DispersionConfig,
    GroundStationConfig,
    MonteCarloConfig,
    OrbitIC,
    PhasingKeepingConfig,
    Scenario,
    SpacecraftConfig,
)


def _orbit():
    return OrbitIC(type="cartesian", position_km=[7000.0, 0.0, 0.0], velocity_km_s=[0.0, 7.5, 0.0])


def _scenario(**overrides):
    defaults = dict(
        name="ref test", epoch_utc="2030-01-01T00:00:00",
        spacecraft=[SpacecraftConfig(name="sat-1", orbit=_orbit())],
    )
    defaults.update(overrides)
    return Scenario(**defaults)


# -- find_spacecraft_references ---------------------------------------------

def test_no_references_when_unreferenced():
    assert find_spacecraft_references(_scenario(), "sat-1") == []


def test_phasing_keeping_chief_is_found():
    chief = SpacecraftConfig(name="chief", orbit=_orbit())
    follower = SpacecraftConfig(name="follower", orbit=_orbit(), phasing_keeping=PhasingKeepingConfig(
        chief_spacecraft="chief", target_separation_km=[100.0], tolerance_fraction=0.1, restore_tolerance_fraction=0.5,
        correction_window_days=1.0, max_drift_days=5.0, max_delta_semi_major_axis_km=1.0,
    ))
    scenario = _scenario(spacecraft=[chief, follower])

    refs = find_spacecraft_references(scenario, "chief")

    assert len(refs) == 1
    assert refs[0].resource_kind == "spacecraft"
    assert "phasing_keeping.chief_spacecraft" in refs[0].path
    assert "follower" in refs[0].path


def test_monte_carlo_dispersion_is_found():
    scenario = _scenario(monte_carlo=MonteCarloConfig(
        enabled=True, num_runs=2,
        dispersions=[DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="uniform", bounds=[90, 110])],
    ))

    refs = find_spacecraft_references(scenario, "sat-1")

    assert len(refs) == 1
    assert "monte_carlo.dispersions[0]" in refs[0].path


def test_maneuver_command_reference_is_found():
    scenario = _scenario(mission_sequence=[
        Command(kind="maneuver", label="Trim", params={"spacecraft": "sat-1", "delta_v_m_s": [1.0, 0.0, 0.0]}),
    ])

    refs = find_spacecraft_references(scenario, "sat-1")

    assert len(refs) == 1
    assert "mission_sequence[0]" in refs[0].path
    assert "'Trim'" in refs[0].path


def test_propagate_event_command_reference_is_found():
    scenario = _scenario(mission_sequence=[
        Command(kind="propagate", params={"stop_condition": "event", "event_kind": "periapsis",
                                            "spacecraft": "sat-1"}),
    ])
    refs = find_spacecraft_references(scenario, "sat-1")
    assert len(refs) == 1


def test_assignment_target_reference_is_found():
    scenario = _scenario(mission_sequence=[
        Command(kind="assignment", params={"target": "sat-1.station_keeping.thrust_n", "value": 0.5}),
    ])

    refs = find_spacecraft_references(scenario, "sat-1")

    assert len(refs) == 1
    assert "params['target']" in refs[0].path


def test_reference_nested_inside_if_is_found():
    scenario = _scenario(mission_sequence=[
        Command(kind="if", params={"condition": "True"}, children=[
            Command(kind="maneuver", params={"spacecraft": "sat-1", "delta_v_m_s": [1.0, 0.0, 0.0]}),
        ]),
    ])

    refs = find_spacecraft_references(scenario, "sat-1")

    assert len(refs) == 1
    assert "children[0]" in refs[0].path


def test_reference_to_a_different_spacecraft_is_not_found():
    scenario = _scenario(spacecraft=[SpacecraftConfig(name="sat-1", orbit=_orbit()),
                                       SpacecraftConfig(name="sat-2", orbit=_orbit())],
                          mission_sequence=[
        Command(kind="maneuver", params={"spacecraft": "sat-2", "delta_v_m_s": [1.0, 0.0, 0.0]}),
    ])
    assert find_spacecraft_references(scenario, "sat-1") == []


# -- find_ground_station_references ------------------------------------------

def test_ground_station_target_is_found():
    sc = SpacecraftConfig(name="sat-1", orbit=_orbit(), fsw_mode="locationPointing",
                            fsw_params={"target_ground_station": "dsn-goldstone", "pHat_B": [0, 0, 1]})
    scenario = _scenario(spacecraft=[sc],
                          ground_stations=[GroundStationConfig(name="dsn-goldstone", latitude_deg=35.0,
                                                                  longitude_deg=-116.0)])

    refs = find_ground_station_references(scenario, "dsn-goldstone")

    assert len(refs) == 1
    assert "target_ground_station" in refs[0].path


def test_ground_station_unreferenced_is_empty():
    scenario = _scenario(ground_stations=[GroundStationConfig(name="gs-1", latitude_deg=0.0, longitude_deg=0.0)])
    assert find_ground_station_references(scenario, "gs-1") == []


# -- rename_spacecraft ------------------------------------------------------

def test_rename_spacecraft_updates_self_and_every_reference():
    chief = SpacecraftConfig(name="chief", orbit=_orbit())
    follower = SpacecraftConfig(name="follower", orbit=_orbit(), phasing_keeping=PhasingKeepingConfig(
        chief_spacecraft="chief", target_separation_km=[100.0], tolerance_fraction=0.1, restore_tolerance_fraction=0.5,
        correction_window_days=1.0, max_drift_days=5.0, max_delta_semi_major_axis_km=1.0,
    ))
    scenario = _scenario(spacecraft=[chief, follower], mission_sequence=[
        Command(kind="maneuver", params={"spacecraft": "chief", "delta_v_m_s": [1.0, 0.0, 0.0]}),
        Command(kind="assignment", params={"target": "chief.station_keeping.thrust_n", "value": 1.0}),
    ], monte_carlo=MonteCarloConfig(
        enabled=True, num_runs=1,
        dispersions=[DispersionConfig(spacecraft="chief", quantity="dry_mass_kg", kind="uniform", bounds=[90, 110])],
    ))

    updated = rename_spacecraft(scenario, "chief", "chief-2")

    assert updated == 4  # phasing_keeping + dispersion + maneuver + assignment
    assert chief.name == "chief-2"
    assert follower.phasing_keeping.chief_spacecraft == "chief-2"
    assert scenario.monte_carlo.dispersions[0].spacecraft == "chief-2"
    assert scenario.mission_sequence[0].params["spacecraft"] == "chief-2"
    assert scenario.mission_sequence[1].params["target"] == "chief-2.station_keeping.thrust_n"
    assert find_spacecraft_references(scenario, "chief") == []


def test_rename_spacecraft_in_nested_if_children():
    scenario = _scenario(mission_sequence=[
        Command(kind="while", params={"condition": "True"}, children=[
            Command(kind="maneuver", params={"spacecraft": "sat-1", "delta_v_m_s": [1.0, 0.0, 0.0]}),
        ]),
    ])
    rename_spacecraft(scenario, "sat-1", "sat-1-renamed")
    assert scenario.mission_sequence[0].children[0].params["spacecraft"] == "sat-1-renamed"


def test_rename_spacecraft_raises_if_old_name_not_found():
    with pytest.raises(ReferenceError, match="no spacecraft named"):
        rename_spacecraft(_scenario(), "does-not-exist", "new-name")


def test_rename_spacecraft_raises_on_collision():
    scenario = _scenario(spacecraft=[SpacecraftConfig(name="sat-1", orbit=_orbit()),
                                       SpacecraftConfig(name="sat-2", orbit=_orbit())])
    with pytest.raises(ReferenceError, match="already exists"):
        rename_spacecraft(scenario, "sat-1", "sat-2")


def test_rename_spacecraft_raises_on_empty_new_name():
    with pytest.raises(ReferenceError, match="must not be empty"):
        rename_spacecraft(_scenario(), "sat-1", "")


def test_rename_spacecraft_to_same_name_is_a_harmless_no_op():
    scenario = _scenario()
    updated = rename_spacecraft(scenario, "sat-1", "sat-1")
    assert updated == 0
    assert scenario.spacecraft[0].name == "sat-1"


# -- rename_ground_station ----------------------------------------------------

def test_rename_ground_station_updates_self_and_references():
    sc = SpacecraftConfig(name="sat-1", orbit=_orbit(), fsw_mode="locationPointing",
                            fsw_params={"target_ground_station": "gs-1", "pHat_B": [0, 0, 1]})
    scenario = _scenario(spacecraft=[sc],
                          ground_stations=[GroundStationConfig(name="gs-1", latitude_deg=0.0, longitude_deg=0.0)])

    updated = rename_ground_station(scenario, "gs-1", "gs-1-renamed")

    assert updated == 1
    assert scenario.ground_stations[0].name == "gs-1-renamed"
    assert sc.fsw_params["target_ground_station"] == "gs-1-renamed"


def test_rename_ground_station_raises_if_not_found():
    with pytest.raises(ReferenceError, match="no ground station named"):
        rename_ground_station(_scenario(), "does-not-exist", "new-name")
