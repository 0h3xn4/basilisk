"""Tests for missionstudio.schema -- no Basilisk import, runs anywhere."""

import json

import pytest

from missionstudio.schema import (
    ActuatorConfig,
    ConstantThrustConfig,
    DispersionConfig,
    GravityConfig,
    GroundStationConfig,
    MonteCarloConfig,
    OrbitIC,
    PhasingKeepingConfig,
    PowerConfig,
    RFLinkConfig,
    Scenario,
    ScenarioValidationError,
    SensorConfig,
    SpacecraftConfig,
    StationKeepingConfig,
    load_scenario,
)


def _minimal_scenario(**overrides) -> Scenario:
    defaults = dict(
        name="test scenario",
        epoch_utc="2030-01-01T00:00:00",
        spacecraft=[
            SpacecraftConfig(
                name="sat-1",
                orbit=OrbitIC(
                    type="classical_elements", semi_major_axis_km=7000.0, eccentricity=0.001,
                    inclination_deg=51.6, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0,
                ),
            )
        ],
    )
    defaults.update(overrides)
    return Scenario(**defaults)


def test_minimal_scenario_validates():
    _minimal_scenario().validate()


def test_round_trip_save_load(tmp_path):
    scenario = _minimal_scenario(description="round-trip check")
    path = tmp_path / "scenario.json"
    scenario.save(path)

    loaded = load_scenario(path)
    assert loaded.name == scenario.name
    assert loaded.epoch_utc == scenario.epoch_utc
    assert loaded.description == "round-trip check"
    assert len(loaded.spacecraft) == 1
    assert loaded.spacecraft[0].orbit.semi_major_axis_km == 7000.0
    assert loaded.schema_version == scenario.schema_version


def test_round_trip_preserves_every_field_category(tmp_path):
    scenario = _minimal_scenario()
    scenario.gravity = GravityConfig(central_body="earth", central_body_degree=10,
                                      third_body_perturbers=["sun", "moon"])
    scenario.ground_stations = [GroundStationConfig(name="gs-1", latitude_deg=40.0, longitude_deg=-105.0)]
    scenario.spacecraft[0].sensors = [SensorConfig(kind="star_tracker", name="st-1", params={"noise_arcsec": 5.0})]

    path = tmp_path / "scenario.json"
    scenario.save(path)
    loaded = load_scenario(path)

    assert loaded.gravity.central_body_degree == 10
    assert loaded.gravity.third_body_perturbers == ["sun", "moon"]
    assert loaded.ground_stations[0].name == "gs-1"
    assert loaded.spacecraft[0].sensors[0].kind == "star_tracker"
    assert loaded.spacecraft[0].sensors[0].params["noise_arcsec"] == 5.0


def test_saved_file_is_plain_readable_json(tmp_path):
    path = tmp_path / "scenario.json"
    _minimal_scenario().save(path)
    # round-trips through plain json.loads with no custom decoder -- this
    # is a "human-readable JSON", not a pickle, per the project requirement.
    data = json.loads(path.read_text())
    assert data["name"] == "test scenario"
    assert data["schema_version"] == 1


@pytest.mark.parametrize("bad_field,bad_value,match", [
    ("name", "", "name must not be empty"),
    ("epoch_utc", "not-a-date", "not a valid ISO 8601"),
])
def test_scenario_level_validation_errors(bad_field, bad_value, match):
    scenario = _minimal_scenario(**{bad_field: bad_value})
    with pytest.raises(ScenarioValidationError, match=match):
        scenario.validate()


def test_zero_spacecraft_rejected():
    scenario = _minimal_scenario(spacecraft=[])
    with pytest.raises(ScenarioValidationError, match="at least one spacecraft"):
        scenario.validate()


def test_duplicate_spacecraft_names_rejected():
    sc = _minimal_scenario()
    sc.spacecraft.append(SpacecraftConfig(name="sat-1", orbit=sc.spacecraft[0].orbit))
    with pytest.raises(ScenarioValidationError, match="unique"):
        sc.validate()


def test_unsupported_central_body_rejected():
    sc = _minimal_scenario()
    sc.gravity = GravityConfig(central_body="pluto")
    with pytest.raises(ScenarioValidationError, match="must be one of"):
        sc.validate()


def test_invalid_eccentricity_rejected():
    sc = _minimal_scenario()
    sc.spacecraft[0].orbit.eccentricity = 1.2  # hyperbolic, out of this schema's supported range
    with pytest.raises(ScenarioValidationError, match="0 <= eccentricity < 1"):
        sc.validate()


def test_cartesian_orbit_requires_full_vectors():
    orbit = OrbitIC(type="cartesian", position_km=[7000.0, 0.0])  # only 2 elements, missing velocity
    with pytest.raises(ScenarioValidationError, match="3-element"):
        orbit.validate()


def test_tle_orbit_requires_both_lines():
    orbit = OrbitIC(type="tle", tle_line1="1 25544U ...")
    with pytest.raises(ScenarioValidationError, match="both tle_line1 and tle_line2"):
        orbit.validate()


def test_classical_elements_orbit_defaults_to_true_anomaly():
    orbit = OrbitIC(type="classical_elements", semi_major_axis_km=7000.0, eccentricity=0.001,
                     inclination_deg=51.6, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=30.0)
    assert orbit.anomaly_type == "true"
    orbit.validate()  # must not raise


def test_classical_elements_orbit_accepts_mean_anomaly():
    orbit = OrbitIC(type="classical_elements", semi_major_axis_km=7000.0, eccentricity=0.001,
                     inclination_deg=51.6, raan_deg=0.0, arg_periapsis_deg=0.0,
                     anomaly_type="mean", mean_anomaly_deg=30.0)
    orbit.validate()  # must not raise


def test_classical_elements_orbit_requires_the_anomaly_matching_anomaly_type():
    orbit = OrbitIC(type="classical_elements", semi_major_axis_km=7000.0, eccentricity=0.001,
                     inclination_deg=51.6, raan_deg=0.0, arg_periapsis_deg=0.0,
                     anomaly_type="mean", true_anomaly_deg=30.0)  # wrong field for anomaly_type="mean"
    with pytest.raises(ScenarioValidationError, match="needs mean_anomaly_deg"):
        orbit.validate()


def test_classical_elements_orbit_rejects_unknown_anomaly_type():
    orbit = OrbitIC(type="classical_elements", semi_major_axis_km=7000.0, eccentricity=0.001,
                     inclination_deg=51.6, raan_deg=0.0, arg_periapsis_deg=0.0,
                     anomaly_type="eccentric", true_anomaly_deg=30.0)
    with pytest.raises(ScenarioValidationError, match="anomaly_type"):
        orbit.validate()


def test_space_weather_local_file_requires_path():
    sc = _minimal_scenario()
    sc.space_weather.source = "local_file"
    sc.space_weather.local_file_path = None
    with pytest.raises(ScenarioValidationError, match="local_file_path was not set"):
        sc.validate()


def test_load_scenario_missing_file_gives_clear_error(tmp_path):
    with pytest.raises(ScenarioValidationError, match="could not read file"):
        load_scenario(tmp_path / "does_not_exist.json")


def test_load_scenario_malformed_json_gives_clear_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    with pytest.raises(ScenarioValidationError, match="not valid JSON"):
        load_scenario(path)


def test_load_scenario_missing_schema_version_gives_clear_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"name": "no version"}))
    with pytest.raises(ScenarioValidationError, match="missing required top-level 'schema_version'"):
        load_scenario(path)


def test_load_scenario_future_schema_version_gives_clear_error(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema_version": 999, "name": "from the future", "epoch_utc": "2030-01-01T00:00:00"}))
    with pytest.raises(ScenarioValidationError, match="upgrade missionStudio"):
        load_scenario(path)


# -- Phase 2: sensors/actuators/FSW mode validation ---------------------------

def test_unsupported_sensor_kind_rejected():
    sc = _minimal_scenario()
    sc.spacecraft[0].sensors = [SensorConfig(kind="lidar", name="l-1")]
    with pytest.raises(ScenarioValidationError, match="must be one of"):
        sc.validate()


def test_unsupported_actuator_kind_rejected():
    sc = _minimal_scenario()
    sc.spacecraft[0].actuators = [ActuatorConfig(kind="ion_engine", name="ie-1")]
    with pytest.raises(ScenarioValidationError, match="must be one of"):
        sc.validate()


def test_duplicate_sensor_names_rejected():
    sc = _minimal_scenario()
    sc.spacecraft[0].sensors = [SensorConfig(kind="imu", name="dup"), SensorConfig(kind="star_tracker", name="dup")]
    with pytest.raises(ScenarioValidationError, match="sensor names must be unique"):
        sc.validate()


def test_duplicate_actuator_names_rejected():
    sc = _minimal_scenario()
    sc.spacecraft[0].actuators = [
        ActuatorConfig(kind="reaction_wheel", name="dup", params={"gsHat_B": [1, 0, 0]}),
        ActuatorConfig(kind="thruster", name="dup"),
    ]
    with pytest.raises(ScenarioValidationError, match="actuator names must be unique"):
        sc.validate()


def test_coarse_sun_sensor_requires_nHat_B():
    sc = _minimal_scenario()
    sc.spacecraft[0].sensors = [SensorConfig(kind="coarse_sun_sensor", name="css-1")]
    with pytest.raises(ScenarioValidationError, match="nHat_B"):
        sc.validate()


def test_reaction_wheel_requires_gsHat_B():
    sc = _minimal_scenario()
    sc.spacecraft[0].actuators = [ActuatorConfig(kind="reaction_wheel", name="rw-1")]
    with pytest.raises(ScenarioValidationError, match="gsHat_B"):
        sc.validate()


def test_unsupported_fsw_mode_rejected():
    sc = _minimal_scenario()
    sc.spacecraft[0].fsw_mode = "sunTrackingRasterScan"
    with pytest.raises(ScenarioValidationError, match="fsw_mode"):
        sc.validate()


def test_none_fsw_mode_is_valid():
    _minimal_scenario().validate()  # fsw_mode defaults to None -- must not raise


def test_none_vizard_model_path_is_valid():
    _minimal_scenario().validate()  # vizard_model_path defaults to None -- must not raise


def test_blank_vizard_model_path_rejected():
    sc = _minimal_scenario()
    sc.spacecraft[0].vizard_model_path = "   "
    with pytest.raises(ScenarioValidationError, match="vizard_model_path must not be blank"):
        sc.validate()


@pytest.mark.parametrize("field", ["vizard_model_offset_m", "vizard_model_rotation_deg", "vizard_model_scale"])
def test_vizard_model_vectors_require_3_elements(field):
    sc = _minimal_scenario()
    setattr(sc.spacecraft[0], field, [1.0, 2.0])
    with pytest.raises(ScenarioValidationError, match=f"{field} must have 3 elements"):
        sc.validate()


def test_vizard_model_path_round_trips_through_json(tmp_path):
    sc = _minimal_scenario()
    sc.spacecraft[0].vizard_model_path = "CUBE"
    sc.spacecraft[0].vizard_model_offset_m = [0.1, 0.2, 0.3]
    sc.spacecraft[0].vizard_model_rotation_deg = [10.0, 20.0, 30.0]
    sc.spacecraft[0].vizard_model_scale = [2.0, 2.0, 2.0]
    sc.validate()

    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(sc.to_dict(), indent=2))
    loaded = load_scenario(path)
    assert loaded.spacecraft[0].vizard_model_path == "CUBE"
    assert loaded.spacecraft[0].vizard_model_offset_m == [0.1, 0.2, 0.3]
    assert loaded.spacecraft[0].vizard_model_rotation_deg == [10.0, 20.0, 30.0]
    assert loaded.spacecraft[0].vizard_model_scale == [2.0, 2.0, 2.0]


@pytest.mark.parametrize("mode", ["inertial3D", "hillPoint", "velocityPoint", "sunSafePoint"])
def test_every_supported_fsw_mode_validates(mode):
    sc = _minimal_scenario()
    sc.spacecraft[0].fsw_mode = mode
    sc.validate()  # must not raise


def test_location_pointing_requires_exactly_one_target():
    sc = _minimal_scenario()
    sc.spacecraft[0].fsw_mode = "locationPointing"
    sc.spacecraft[0].fsw_params = {}  # neither target given
    with pytest.raises(ScenarioValidationError, match="exactly one of"):
        sc.validate()

    sc.spacecraft[0].fsw_params = {"target_ground_station": "gs-1", "target_body": "sun"}  # both given
    with pytest.raises(ScenarioValidationError, match="exactly one of"):
        sc.validate()


def test_location_pointing_target_ground_station_must_exist():
    sc = _minimal_scenario()
    sc.ground_stations = [GroundStationConfig(name="gs-1", latitude_deg=40.0, longitude_deg=-105.0)]
    sc.spacecraft[0].fsw_mode = "locationPointing"
    sc.spacecraft[0].fsw_params = {"target_ground_station": "gs-does-not-exist"}
    with pytest.raises(ScenarioValidationError, match="not one of this scenario's ground_stations"):
        sc.validate()


def test_location_pointing_with_existing_ground_station_validates():
    sc = _minimal_scenario()
    sc.ground_stations = [GroundStationConfig(name="gs-1", latitude_deg=40.0, longitude_deg=-105.0)]
    sc.spacecraft[0].fsw_mode = "locationPointing"
    sc.spacecraft[0].fsw_params = {"target_ground_station": "gs-1"}
    sc.validate()  # must not raise


def test_location_pointing_with_target_body_validates_structurally():
    # Schema-valid (exactly one target given); engine.fsw is what rejects
    # target_body as not-yet-wired-up at run time, not schema validation.
    sc = _minimal_scenario()
    sc.spacecraft[0].fsw_mode = "locationPointing"
    sc.spacecraft[0].fsw_params = {"target_body": "sun"}
    sc.validate()  # must not raise


# -- Phase 3: Monte Carlo validation ------------------------------------------

def test_monte_carlo_defaults_to_disabled_and_validates():
    _minimal_scenario().validate()  # monte_carlo defaults to enabled=False, no dispersions


def test_monte_carlo_num_runs_must_be_positive():
    sc = _minimal_scenario()
    sc.monte_carlo = MonteCarloConfig(enabled=True, num_runs=0)
    with pytest.raises(ScenarioValidationError, match="num_runs must be >= 1"):
        sc.validate()


def test_monte_carlo_thread_count_must_be_positive():
    sc = _minimal_scenario()
    sc.monte_carlo = MonteCarloConfig(enabled=True, thread_count=0)
    with pytest.raises(ScenarioValidationError, match="thread_count must be >= 1"):
        sc.validate()


def test_dispersion_unsupported_quantity_rejected():
    sc = _minimal_scenario()
    sc.monte_carlo = MonteCarloConfig(
        enabled=True,
        dispersions=[DispersionConfig(spacecraft="sat-1", quantity="orbit_position", kind="uniform", bounds=[0, 1])],
    )
    with pytest.raises(ScenarioValidationError, match="quantity"):
        sc.validate()


def test_dispersion_kind_not_valid_for_quantity_rejected():
    sc = _minimal_scenario()
    sc.monte_carlo = MonteCarloConfig(
        enabled=True,
        dispersions=[DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="uniform_euler_mrp",
                                       bounds=[0, 1])],
    )
    with pytest.raises(ScenarioValidationError, match="must be one of"):
        sc.validate()


def test_dispersion_uniform_requires_bounds():
    sc = _minimal_scenario()
    sc.monte_carlo = MonteCarloConfig(
        enabled=True,
        dispersions=[DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="uniform")],
    )
    with pytest.raises(ScenarioValidationError, match="needs bounds"):
        sc.validate()


def test_dispersion_normal_requires_mean_and_std():
    sc = _minimal_scenario()
    sc.monte_carlo = MonteCarloConfig(
        enabled=True,
        dispersions=[DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="normal")],
    )
    with pytest.raises(ScenarioValidationError, match="needs mean and std_deviation"):
        sc.validate()


def test_dispersion_unknown_spacecraft_rejected():
    sc = _minimal_scenario()
    sc.monte_carlo = MonteCarloConfig(
        enabled=True,
        dispersions=[DispersionConfig(spacecraft="does-not-exist", quantity="dry_mass_kg", kind="normal",
                                       mean=100.0, std_deviation=5.0)],
    )
    with pytest.raises(ScenarioValidationError, match="not one of this scenario's spacecraft"):
        sc.validate()


def test_valid_dispersions_validate():
    sc = _minimal_scenario()
    sc.monte_carlo = MonteCarloConfig(
        enabled=True, num_runs=25,
        dispersions=[
            DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="normal", mean=100.0, std_deviation=5.0),
            DispersionConfig(spacecraft="sat-1", quantity="attitude_sigma_bn", kind="uniform_euler_mrp",
                              bounds=[0.0, 6.283185307]),
        ],
    )
    sc.validate()  # must not raise


def test_monte_carlo_round_trips_through_save_load(tmp_path):
    sc = _minimal_scenario()
    sc.monte_carlo = MonteCarloConfig(
        enabled=True, num_runs=25, thread_count=2,
        dispersions=[DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="uniform", bounds=[95.0, 105.0])],
    )
    path = tmp_path / "scenario.json"
    sc.save(path)
    loaded = load_scenario(path)

    assert loaded.monte_carlo.enabled is True
    assert loaded.monte_carlo.num_runs == 25
    assert loaded.monte_carlo.thread_count == 2
    assert loaded.monte_carlo.dispersions[0].quantity == "dry_mass_kg"
    assert loaded.monte_carlo.dispersions[0].bounds == [95.0, 105.0]


def test_old_scenario_file_without_monte_carlo_key_still_loads(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({
        "schema_version": 1, "name": "old scenario", "epoch_utc": "2030-01-01T00:00:00",
        "spacecraft": [{
            "name": "sat-1",
            "orbit": {"type": "cartesian", "position_km": [7000, 0, 0], "velocity_km_s": [0, 7.5, 0]},
        }],
    }))
    loaded = load_scenario(path)
    assert loaded.monte_carlo.enabled is False
    assert loaded.monte_carlo.dispersions == []


def test_phase2_fields_round_trip_through_save_load(tmp_path):
    sc = _minimal_scenario()
    sc.spacecraft[0].sensors = [SensorConfig(kind="coarse_sun_sensor", name="css-1", params={"nHat_B": [1, 0, 0]})]
    sc.spacecraft[0].actuators = [ActuatorConfig(kind="reaction_wheel", name="rw-1", params={"gsHat_B": [0, 1, 0]})]
    sc.spacecraft[0].fsw_mode = "hillPoint"
    sc.spacecraft[0].control_params = {"K": 4.0, "P": 25.0}

    path = tmp_path / "scenario.json"
    sc.save(path)
    loaded = load_scenario(path)

    assert loaded.spacecraft[0].sensors[0].params["nHat_B"] == [1, 0, 0]
    assert loaded.spacecraft[0].actuators[0].params["gsHat_B"] == [0, 1, 0]
    assert loaded.spacecraft[0].fsw_mode == "hillPoint"
    assert loaded.spacecraft[0].control_params == {"K": 4.0, "P": 25.0}


def test_power_and_rf_link_default_to_none():
    sc = _minimal_scenario()
    assert sc.spacecraft[0].power is None
    assert sc.spacecraft[0].rf_link is None
    sc.validate()  # must not raise -- neither field is required


def test_power_config_round_trips_through_save_load(tmp_path):
    sc = _minimal_scenario()
    sc.spacecraft[0].power = PowerConfig(panel_area_m2=1.2, panel_efficiency=0.29,
                                          bus_idle_power_w=25.0, battery_capacity_wh=120.0,
                                          battery_initial_soc=0.9)
    sc.spacecraft[0].rf_link = RFLinkConfig(tx_power_w=15.0, frequency_hz=8.2e9, data_rate_bps=1.0e6)

    path = tmp_path / "scenario.json"
    sc.save(path)
    loaded = load_scenario(path)

    assert isinstance(loaded.spacecraft[0].power, PowerConfig)
    assert loaded.spacecraft[0].power.panel_area_m2 == 1.2
    assert loaded.spacecraft[0].power.battery_initial_soc == 0.9
    assert isinstance(loaded.spacecraft[0].rf_link, RFLinkConfig)
    assert loaded.spacecraft[0].rf_link.tx_power_w == 15.0
    assert loaded.spacecraft[0].rf_link.frequency_hz == 8.2e9


def test_power_config_rejects_invalid_panel_efficiency():
    sc = _minimal_scenario()
    sc.spacecraft[0].power = PowerConfig(panel_area_m2=1.0, panel_efficiency=1.5)
    with pytest.raises(ScenarioValidationError, match="panel_efficiency"):
        sc.validate()


def test_power_config_rejects_invalid_initial_soc():
    sc = _minimal_scenario()
    sc.spacecraft[0].power = PowerConfig(panel_area_m2=1.0, panel_efficiency=0.3, battery_initial_soc=1.5)
    with pytest.raises(ScenarioValidationError, match="battery_initial_soc"):
        sc.validate()


def test_rf_link_config_rejects_non_positive_data_rate():
    sc = _minimal_scenario()
    sc.spacecraft[0].rf_link = RFLinkConfig(tx_power_w=10.0, frequency_hz=8.0e9, data_rate_bps=0.0)
    with pytest.raises(ScenarioValidationError, match="data_rate_bps"):
        sc.validate()


def test_ground_station_rejects_non_positive_system_noise_temp():
    gs = GroundStationConfig(name="gs1", latitude_deg=0.0, longitude_deg=0.0, system_noise_temp_k=0.0)
    with pytest.raises(ScenarioValidationError, match="system_noise_temp_k"):
        gs.validate()


def test_old_scenario_file_without_power_or_rf_link_keys_still_loads(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({
        "schema_version": 1, "name": "old scenario", "epoch_utc": "2030-01-01T00:00:00",
        "spacecraft": [{
            "name": "sat-1",
            "orbit": {"type": "cartesian", "position_km": [7000, 0, 0], "velocity_km_s": [0, 7.5, 0]},
        }],
    }))
    loaded = load_scenario(path)
    assert loaded.spacecraft[0].power is None
    assert loaded.spacecraft[0].rf_link is None
    assert loaded.spacecraft[0].station_keeping is None


def test_station_keeping_defaults_to_none():
    sc = _minimal_scenario()
    assert sc.spacecraft[0].station_keeping is None
    sc.validate()  # must not raise -- not required


def test_station_keeping_round_trips_through_save_load(tmp_path):
    sc = _minimal_scenario()
    sc.spacecraft[0].station_keeping = StationKeepingConfig(
        target_altitude_km=500.0, deadband_km=1.0, thrust_n=0.01, isp_s=1500.0, propellant_kg=2.0,
    )

    path = tmp_path / "scenario.json"
    sc.save(path)
    loaded = load_scenario(path)

    assert isinstance(loaded.spacecraft[0].station_keeping, StationKeepingConfig)
    assert loaded.spacecraft[0].station_keeping.target_altitude_km == 500.0
    assert loaded.spacecraft[0].station_keeping.propellant_kg == 2.0
    assert loaded.spacecraft[0].station_keeping.eclipse_sunlit_threshold == 0.99  # default preserved


def test_station_keeping_rejects_deadband_not_less_than_target_altitude():
    sc = _minimal_scenario()
    sc.spacecraft[0].station_keeping = StationKeepingConfig(
        target_altitude_km=500.0, deadband_km=500.0, thrust_n=0.01, isp_s=1500.0, propellant_kg=2.0,
    )
    with pytest.raises(ScenarioValidationError, match="deadband_km"):
        sc.validate()


def test_station_keeping_rejects_zero_deadband():
    sc = _minimal_scenario()
    sc.spacecraft[0].station_keeping = StationKeepingConfig(
        target_altitude_km=500.0, deadband_km=0.0, thrust_n=0.01, isp_s=1500.0, propellant_kg=2.0,
    )
    with pytest.raises(ScenarioValidationError, match="deadband_km"):
        sc.validate()


def test_station_keeping_rejects_non_positive_thrust():
    sc = _minimal_scenario()
    sc.spacecraft[0].station_keeping = StationKeepingConfig(
        target_altitude_km=500.0, deadband_km=1.0, thrust_n=0.0, isp_s=1500.0, propellant_kg=2.0,
    )
    with pytest.raises(ScenarioValidationError, match="thrust_n"):
        sc.validate()


def test_station_keeping_rejects_negative_propellant():
    sc = _minimal_scenario()
    sc.spacecraft[0].station_keeping = StationKeepingConfig(
        target_altitude_km=500.0, deadband_km=1.0, thrust_n=0.01, isp_s=1500.0, propellant_kg=-1.0,
    )
    with pytest.raises(ScenarioValidationError, match="propellant_kg"):
        sc.validate()


def test_station_keeping_rejects_out_of_range_eclipse_threshold():
    sc = _minimal_scenario()
    sc.spacecraft[0].station_keeping = StationKeepingConfig(
        target_altitude_km=500.0, deadband_km=1.0, thrust_n=0.01, isp_s=1500.0, propellant_kg=2.0,
        eclipse_sunlit_threshold=1.5,
    )
    with pytest.raises(ScenarioValidationError, match="eclipse_sunlit_threshold"):
        sc.validate()


def test_constant_thrust_defaults_to_none():
    sc = _minimal_scenario()
    assert sc.spacecraft[0].constant_thrust is None
    sc.validate()  # must not raise -- not required


def test_constant_thrust_round_trips_through_save_load(tmp_path):
    sc = _minimal_scenario()
    sc.spacecraft[0].constant_thrust = ConstantThrustConfig(
        frame="RTN", direction=[0.0, 1.0, 0.0], thrust_n=0.05, isp_s=2000.0, propellant_kg=1.5,
    )

    path = tmp_path / "scenario.json"
    sc.save(path)
    loaded = load_scenario(path)

    assert isinstance(loaded.spacecraft[0].constant_thrust, ConstantThrustConfig)
    assert loaded.spacecraft[0].constant_thrust.frame == "RTN"
    assert loaded.spacecraft[0].constant_thrust.direction == [0.0, 1.0, 0.0]
    assert loaded.spacecraft[0].constant_thrust.thrust_n == 0.05


def test_constant_thrust_defaults_to_vnb_prograde():
    config = ConstantThrustConfig()
    assert config.frame == "VNB"
    assert config.direction == [1.0, 0.0, 0.0]


def test_constant_thrust_rejects_unknown_frame():
    sc = _minimal_scenario()
    sc.spacecraft[0].constant_thrust = ConstantThrustConfig(frame="LVLH")
    with pytest.raises(ScenarioValidationError, match="frame"):
        sc.validate()


def test_constant_thrust_rejects_wrong_length_direction():
    sc = _minimal_scenario()
    sc.spacecraft[0].constant_thrust = ConstantThrustConfig(direction=[1.0, 0.0])
    with pytest.raises(ScenarioValidationError, match="direction"):
        sc.validate()


def test_constant_thrust_rejects_zero_direction_vector():
    sc = _minimal_scenario()
    sc.spacecraft[0].constant_thrust = ConstantThrustConfig(direction=[0.0, 0.0, 0.0])
    with pytest.raises(ScenarioValidationError, match="zero vector"):
        sc.validate()


def test_constant_thrust_rejects_non_positive_thrust():
    sc = _minimal_scenario()
    sc.spacecraft[0].constant_thrust = ConstantThrustConfig(thrust_n=0.0)
    with pytest.raises(ScenarioValidationError, match="thrust_n"):
        sc.validate()


def test_constant_thrust_rejects_non_positive_isp():
    sc = _minimal_scenario()
    sc.spacecraft[0].constant_thrust = ConstantThrustConfig(isp_s=0.0)
    with pytest.raises(ScenarioValidationError, match="isp_s"):
        sc.validate()


def test_constant_thrust_rejects_negative_propellant():
    sc = _minimal_scenario()
    sc.spacecraft[0].constant_thrust = ConstantThrustConfig(propellant_kg=-1.0)
    with pytest.raises(ScenarioValidationError, match="propellant_kg"):
        sc.validate()


def test_constant_thrust_allowed_alongside_station_keeping():
    """Independent propellant budgets -- see ConstantThrustConfig's
    docstring -- so both may be set on the same spacecraft at once.
    """
    sc = _minimal_scenario()
    sc.spacecraft[0].station_keeping = StationKeepingConfig(
        target_altitude_km=500.0, deadband_km=1.0, thrust_n=0.01, isp_s=1500.0, propellant_kg=2.0,
    )
    sc.spacecraft[0].constant_thrust = ConstantThrustConfig()
    sc.validate()  # must not raise


def test_simulation_mode_defaults_to_full_attitude():
    sc = _minimal_scenario()
    assert sc.simulation_mode == "full_attitude"
    sc.validate()  # must not raise


def test_simulation_mode_rejects_unknown_value():
    sc = _minimal_scenario()
    sc.simulation_mode = "cannonball"
    with pytest.raises(ScenarioValidationError, match="simulation_mode"):
        sc.validate()


def test_orbit_only_mode_rejects_fsw_mode():
    sc = _minimal_scenario(simulation_mode="orbit_only")
    sc.spacecraft[0].fsw_mode = "hillPoint"
    with pytest.raises(ScenarioValidationError, match="fsw_mode"):
        sc.validate()


def test_orbit_only_mode_rejects_sensors():
    sc = _minimal_scenario(simulation_mode="orbit_only")
    sc.spacecraft[0].sensors = [SensorConfig(kind="imu", name="imu-1")]
    with pytest.raises(ScenarioValidationError, match="sensors"):
        sc.validate()


def test_orbit_only_mode_rejects_actuators():
    sc = _minimal_scenario(simulation_mode="orbit_only")
    sc.spacecraft[0].actuators = [ActuatorConfig(kind="reaction_wheel", name="rw-1", params={"gsHat_B": [1, 0, 0]})]
    with pytest.raises(ScenarioValidationError, match="actuators"):
        sc.validate()


def test_orbit_only_mode_rejects_power():
    sc = _minimal_scenario(simulation_mode="orbit_only")
    sc.spacecraft[0].power = PowerConfig(panel_area_m2=1.0, panel_efficiency=0.29)
    with pytest.raises(ScenarioValidationError, match="power"):
        sc.validate()


def test_orbit_only_mode_allows_station_keeping_and_constant_thrust():
    """Neither needs an attitude model -- see Scenario.simulation_mode's
    docstring -- so both remain usable in orbit_only mode.
    """
    sc = _minimal_scenario(simulation_mode="orbit_only")
    sc.spacecraft[0].station_keeping = StationKeepingConfig(
        target_altitude_km=500.0, deadband_km=1.0, thrust_n=0.01, isp_s=1500.0, propellant_kg=2.0,
    )
    sc.spacecraft[0].constant_thrust = ConstantThrustConfig()
    sc.spacecraft[0].enable_drag = True
    sc.validate()  # must not raise


def test_orbit_only_mode_allows_plain_cannonball_spacecraft():
    sc = _minimal_scenario(simulation_mode="orbit_only")
    sc.spacecraft[0].enable_drag = True
    sc.spacecraft[0].drag_area_m2 = 2.5
    sc.spacecraft[0].enable_srp = True
    sc.validate()  # must not raise


def _chief_and_follower_scenario(**follower_overrides):
    chief = SpacecraftConfig(
        name="chief",
        orbit=OrbitIC(type="classical_elements", semi_major_axis_km=7000.0, eccentricity=0.0,
                      inclination_deg=51.6, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0),
    )
    follower_kwargs = dict(
        name="follower",
        orbit=OrbitIC(type="classical_elements", semi_major_axis_km=7000.0, eccentricity=0.0,
                      inclination_deg=51.6, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=10.0),
        station_keeping=StationKeepingConfig(target_altitude_km=500.0, deadband_km=1.0, thrust_n=0.01,
                                              isp_s=1500.0, propellant_kg=2.0),
        phasing_keeping=PhasingKeepingConfig(chief_spacecraft="chief", target_separation_km=[100.0]),
    )
    follower_kwargs.update(follower_overrides)
    follower = SpacecraftConfig(**follower_kwargs)
    return Scenario(name="phasing test", epoch_utc="2030-01-01T00:00:00", spacecraft=[chief, follower])


def test_phasing_keeping_defaults_to_none():
    sc = _minimal_scenario()
    assert sc.spacecraft[0].phasing_keeping is None
    sc.validate()  # must not raise


def test_phasing_keeping_round_trips_through_save_load(tmp_path):
    scenario = _chief_and_follower_scenario()
    path = tmp_path / "phasing.json"
    scenario.save(path)
    loaded = load_scenario(path)

    follower = next(sc for sc in loaded.spacecraft if sc.name == "follower")
    assert isinstance(follower.phasing_keeping, PhasingKeepingConfig)
    assert follower.phasing_keeping.chief_spacecraft == "chief"
    assert follower.phasing_keeping.target_separation_km == [100.0]
    assert follower.phasing_keeping.tolerance_fraction == 0.10  # default preserved


def test_phasing_keeping_requires_station_keeping_on_same_spacecraft():
    scenario = _chief_and_follower_scenario(station_keeping=None)
    with pytest.raises(ScenarioValidationError, match="requires station_keeping"):
        scenario.validate()


def test_phasing_keeping_rejects_chief_being_itself():
    scenario = _chief_and_follower_scenario()
    scenario.spacecraft[1].phasing_keeping.chief_spacecraft = "follower"
    with pytest.raises(ScenarioValidationError, match="cannot be the spacecraft itself"):
        scenario.validate()


def test_phasing_keeping_rejects_unknown_chief_spacecraft():
    scenario = _chief_and_follower_scenario()
    scenario.spacecraft[1].phasing_keeping.chief_spacecraft = "no-such-satellite"
    with pytest.raises(ScenarioValidationError, match="chief_spacecraft"):
        scenario.validate()


def test_phasing_keeping_rejects_empty_target_separation():
    scenario = _chief_and_follower_scenario()
    scenario.spacecraft[1].phasing_keeping.target_separation_km = []
    with pytest.raises(ScenarioValidationError, match="target_separation_km"):
        scenario.validate()


def test_phasing_keeping_rejects_non_positive_target_separation():
    scenario = _chief_and_follower_scenario()
    scenario.spacecraft[1].phasing_keeping.target_separation_km = [100.0, 0.0]
    with pytest.raises(ScenarioValidationError, match="target_separation_km"):
        scenario.validate()


@pytest.mark.parametrize("field,value,match", [
    ("reconfiguration_interval_days", -1.0, "reconfiguration_interval_days"),
    ("tolerance_fraction", 0.0, "tolerance_fraction"),
    ("restore_tolerance_fraction", 0.0, "restore_tolerance_fraction"),
    ("correction_window_days", 0.0, "correction_window_days"),
    ("max_drift_days", 0.0, "max_drift_days"),
    ("max_delta_semi_major_axis_km", 0.0, "max_delta_semi_major_axis_km"),
])
def test_phasing_keeping_rejects_bad_tuning_knobs(field, value, match):
    scenario = _chief_and_follower_scenario()
    setattr(scenario.spacecraft[1].phasing_keeping, field, value)
    with pytest.raises(ScenarioValidationError, match=match):
        scenario.validate()


def test_phasing_keeping_full_scenario_validates():
    scenario = _chief_and_follower_scenario()
    scenario.validate()  # must not raise
