#
#  ISC License
#
#  Copyright (c) 2026, Autonomous Vehicle Systems Lab, University of Colorado at Boulder
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
#  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
#  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
#  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
#  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
#  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
#  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#

r"""
The scenario file format: a versioned, human-readable JSON schema for
everything needed to define and run a mission-analysis case (spacecraft
config, orbit initial conditions, epoch, central body, sensors/actuators,
FSW mode, ground stations).

Deliberately dependency-light: standard-library ``dataclasses`` + hand
-written validation, not a pickled Python object and not a third-party
schema library (pydantic, etc.) -- consistent with keeping the backend
service layer's own dependency footprint small (Basilisk itself, plus
whatever the GUI needs, is already enough surface area). This module has
NO Basilisk import and is fully unit-testable without a Basilisk build --
see ``tests/test_scenario_schema.py``.

Versioning
----------
Every scenario file carries a top-level ``schema_version`` integer.
``load_scenario()`` runs the file through ``migrations.MIGRATIONS`` before
constructing a :class:`Scenario`, so old scenario files keep loading as the
schema grows -- see ``migrations.py``. Bump ``CURRENT_SCHEMA_VERSION`` and
add a migration function whenever a field is added, renamed, or removed in
a way that would break an older file.

Phase 0 scope note
-------------------
This schema is intentionally more complete than what Phase 0's
``engine.service.SimulationService`` actually consumes (see that module's
docstring for exactly what Phase 0 wires up: central-body point-mass/
spherical-harmonics gravity, one or more spacecraft with classical
-elements/Cartesian/TLE initial conditions, propagation only). Fields for
sensors, actuators, FSW modes, and ground stations are validated here and
carried through save/load round-trips starting now, precisely so the
schema does not need a disruptive reshape once Phase 2/3 start consuming
them -- retrofitting schema versioning after the fact is much more
painful than reserving the shape up front.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

CURRENT_SCHEMA_VERSION = 1

# SPICE-recognized central body name strings this schema accepts, matching
# Basilisk's simIncludeGravBody.gravBodyFactory named helpers
# (createSun/createEarth/createMoon/createMars/createMarsBarycenter/
# createVenus/createJupiter) -- see engine/service.py for where this list
# is actually consumed.
SUPPORTED_CENTRAL_BODIES = (
    "sun", "mercury", "venus", "earth", "moon", "mars", "mars barycenter", "jupiter",
)

ORBIT_IC_TYPES = ("classical_elements", "cartesian", "tle")


class ScenarioValidationError(ValueError):
    """Raised by :meth:`Scenario.validate` (and the dataclass ``__post_init__``
    hooks it calls) with a specific, actionable message -- never a silent
    NaN or a bare ``KeyError``/``TypeError`` from malformed input, per the
    "clear error messages" requirement this project is built around.
    """


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioValidationError(message)


@dataclass
class OrbitIC:
    """One spacecraft's orbit initial condition, in exactly one of three
    forms. Only the fields for ``type`` need to be set; the others are
    left ``None`` and ignored -- this keeps the JSON readable (no
    all-fields-always-present clutter) while still being one dataclass, so
    ``engine.service.SimulationService`` has a single type to switch on.
    """

    type: str  # one of ORBIT_IC_TYPES

    # type == "classical_elements" (angles in degrees, matching the rest of
    # this codebase's convention -- see mission_config.py in ../missionAnalysis)
    semi_major_axis_km: Optional[float] = None
    eccentricity: Optional[float] = None
    inclination_deg: Optional[float] = None
    raan_deg: Optional[float] = None
    arg_periapsis_deg: Optional[float] = None
    true_anomaly_deg: Optional[float] = None

    # type == "cartesian" (inertial frame of the scenario's central body)
    position_km: Optional[list] = None  # [x, y, z]
    velocity_km_s: Optional[list] = None  # [vx, vy, vz]

    # type == "tle"
    tle_line1: Optional[str] = None
    tle_line2: Optional[str] = None

    def validate(self) -> None:
        _require(self.type in ORBIT_IC_TYPES,
                  f"orbit.type {self.type!r} must be one of {ORBIT_IC_TYPES}")
        if self.type == "classical_elements":
            _require(self.semi_major_axis_km is not None and self.semi_major_axis_km > 0,
                      "classical_elements orbit needs semi_major_axis_km > 0")
            _require(self.eccentricity is not None and 0.0 <= self.eccentricity < 1.0,
                      "classical_elements orbit needs 0 <= eccentricity < 1 (elliptical only)")
            for name in ("inclination_deg", "raan_deg", "arg_periapsis_deg", "true_anomaly_deg"):
                _require(getattr(self, name) is not None, f"classical_elements orbit needs {name}")
        elif self.type == "cartesian":
            for name in ("position_km", "velocity_km_s"):
                value = getattr(self, name)
                _require(value is not None and len(value) == 3,
                          f"cartesian orbit needs {name} as a 3-element [x, y, z] list")
        elif self.type == "tle":
            _require(bool(self.tle_line1) and bool(self.tle_line2),
                      "tle orbit needs both tle_line1 and tle_line2")


@dataclass
class SensorConfig:
    """One sensor instance. ``kind`` selects the Basilisk module (see the
    capability matrix): ``"star_tracker"``, ``"imu"``, ``"coarse_sun_sensor"``,
    ``"magnetometer"``, ``"simple_nav"``. ``params`` is an open dict of
    module-specific settings (noise std devs, mounting DCM, ...) -- kept
    generic here rather than one dataclass per sensor type so new sensor
    kinds can be added (Phase 2+) without another schema migration.
    """

    kind: str
    name: str
    params: dict = field(default_factory=dict)


@dataclass
class ActuatorConfig:
    """One actuator instance. ``kind``: ``"reaction_wheel"``, ``"thruster"``,
    ``"magnetic_torque_rod"``. See :class:`SensorConfig` for why ``params``
    is an open dict.
    """

    kind: str
    name: str
    params: dict = field(default_factory=dict)


@dataclass
class SpacecraftConfig:
    name: str
    orbit: OrbitIC
    dry_mass_kg: float = 100.0
    inertia_kg_m2: list = field(default_factory=lambda: [10.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0])
    sigma_bn_init: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    omega_bn_b_init_rad_s: list = field(default_factory=lambda: [0.0, 0.0, 0.0])

    # Perturbations -- Phase 0's service only ever consumes central-body
    # gravity; these flags are validated/round-tripped now and read starting
    # Phase 1, matching the "reserve the shape, don't wire it all up yet" note.
    enable_drag: bool = False
    drag_coeff: float = 2.2
    drag_area_m2: float = 1.0
    enable_srp: bool = False
    srp_coeff: float = 1.3
    srp_area_m2: float = 1.0

    sensors: list = field(default_factory=list)  # list[SensorConfig]
    actuators: list = field(default_factory=list)  # list[ActuatorConfig]
    fsw_mode: Optional[str] = None  # e.g. "hillPoint", "sunSafePoint", ... (Phase 2)
    fsw_params: dict = field(default_factory=dict)

    def validate(self) -> None:
        _require(bool(self.name), "spacecraft.name must not be empty")
        _require(self.dry_mass_kg > 0, f"{self.name}: dry_mass_kg must be > 0")
        _require(len(self.inertia_kg_m2) == 9, f"{self.name}: inertia_kg_m2 must have 9 elements (3x3, row-major)")
        _require(len(self.sigma_bn_init) == 3, f"{self.name}: sigma_bn_init must have 3 elements")
        _require(len(self.omega_bn_b_init_rad_s) == 3, f"{self.name}: omega_bn_b_init_rad_s must have 3 elements")
        self.orbit.validate()
        for sensor in self.sensors:
            _require(bool(sensor.kind) and bool(sensor.name), f"{self.name}: every sensor needs kind and name")
        for actuator in self.actuators:
            _require(bool(actuator.kind) and bool(actuator.name), f"{self.name}: every actuator needs kind and name")


@dataclass
class GravityConfig:
    central_body: str = "earth"
    central_body_degree: int = 0  # 0 == point-mass only
    third_body_perturbers: list = field(default_factory=list)  # e.g. ["sun", "moon"]

    def validate(self) -> None:
        _require(self.central_body in SUPPORTED_CENTRAL_BODIES,
                  f"gravity.central_body {self.central_body!r} must be one of {SUPPORTED_CENTRAL_BODIES}")
        _require(self.central_body_degree >= 0, "gravity.central_body_degree must be >= 0")
        for name in self.third_body_perturbers:
            _require(name in SUPPORTED_CENTRAL_BODIES,
                      f"gravity.third_body_perturbers entry {name!r} must be one of {SUPPORTED_CENTRAL_BODIES}")


@dataclass
class GroundStationConfig:
    name: str
    latitude_deg: float
    longitude_deg: float
    altitude_m: float = 0.0
    min_elevation_deg: float = 10.0

    def validate(self) -> None:
        _require(bool(self.name), "ground_station.name must not be empty")
        _require(-90.0 <= self.latitude_deg <= 90.0, f"{self.name}: latitude_deg must be in [-90, 90]")
        _require(-180.0 <= self.longitude_deg <= 180.0, f"{self.name}: longitude_deg must be in [-180, 180]")
        _require(0.0 <= self.min_elevation_deg < 90.0, f"{self.name}: min_elevation_deg must be in [0, 90)")


@dataclass
class SpaceWeatherConfig:
    """See engine/spaceweather.py. ``source`` selects the resolution
    strategy; ``local_file_path`` is used (and required) only for
    ``"local_file"``, matching the user's own fallback plan ("if fetching
    isn't possible I'll provide the file myself").
    """

    source: str = "celestrak"  # "celestrak" | "local_file" | "synthetic"
    local_file_path: Optional[str] = None
    cache_dir: Optional[str] = None  # defaults to engine.spaceweather's own cache dir when None

    def validate(self) -> None:
        _require(self.source in ("celestrak", "local_file", "synthetic"),
                  f"space_weather.source {self.source!r} must be 'celestrak', 'local_file', or 'synthetic'")
        if self.source == "local_file":
            _require(bool(self.local_file_path),
                      "space_weather.source is 'local_file' but local_file_path was not set")


# Matches the svIntegrator* classes this Basilisk checkout actually ships
# (src/simulation/dynamics/Integrators/) -- verified by directly listing
# that directory, not assumed. There is deliberately no "rk4" option: this
# checkout has no svIntegratorRK4 (only Euler/RK2 fixed-step and the
# RKF45/RKF78 adaptive pair), and fabricating one here would violate the
# "map every feature to a module Basilisk actually provides" requirement
# this whole project is built around.
SUPPORTED_INTEGRATORS = ("euler", "rk2", "rkf45", "rkf78")


@dataclass
class SimSettings:
    duration_days: float = 1.0
    dynamics_task_rate_s: float = 10.0
    integrator: str = "rkf78"  # see SUPPORTED_INTEGRATORS

    # NOTE: gravity-field degree/order lives on GravityConfig.central_body_degree,
    # not here -- an earlier draft of this schema had a second,
    # SimSettings.earth_grav_degree field that duplicated it, which meant
    # the two could disagree (one saying "point-mass", the other holding a
    # stale nonzero degree) with no validation catching it. Fixed before
    # anything (the GUI, saved scenario files) came to depend on the
    # redundant field -- there is deliberately only one place to set this now.

    def validate(self) -> None:
        _require(self.duration_days > 0, "sim_settings.duration_days must be > 0")
        _require(self.dynamics_task_rate_s > 0, "sim_settings.dynamics_task_rate_s must be > 0")
        _require(self.integrator in SUPPORTED_INTEGRATORS,
                  f"sim_settings.integrator {self.integrator!r} must be one of {SUPPORTED_INTEGRATORS}")


@dataclass
class Scenario:
    name: str
    epoch_utc: str  # ISO 8601, e.g. "2030-01-01T00:00:00" -- single source of
    # truth for time; TAI/TT/ET are DERIVED (see engine/time_system.py), never
    # separately stored, so they cannot drift out of sync with epoch_utc.
    gravity: GravityConfig = field(default_factory=GravityConfig)
    spacecraft: list = field(default_factory=list)  # list[SpacecraftConfig], >= 1 required
    ground_stations: list = field(default_factory=list)  # list[GroundStationConfig]
    space_weather: SpaceWeatherConfig = field(default_factory=SpaceWeatherConfig)
    sim_settings: SimSettings = field(default_factory=SimSettings)
    description: str = ""
    schema_version: int = CURRENT_SCHEMA_VERSION

    def validate(self) -> None:
        _require(bool(self.name), "scenario.name must not be empty")
        try:
            datetime.fromisoformat(self.epoch_utc)
        except ValueError as exc:
            raise ScenarioValidationError(
                f"scenario.epoch_utc {self.epoch_utc!r} is not a valid ISO 8601 datetime "
                f"(e.g. '2030-01-01T00:00:00'): {exc}"
            ) from exc
        self.gravity.validate()
        _require(len(self.spacecraft) >= 1, "scenario needs at least one spacecraft")
        names = [sc.name for sc in self.spacecraft]
        _require(len(names) == len(set(names)), f"spacecraft names must be unique, got {names}")
        for sc in self.spacecraft:
            sc.validate()
        gs_names = [gs.name for gs in self.ground_stations]
        _require(len(gs_names) == len(set(gs_names)), f"ground_station names must be unique, got {gs_names}")
        for gs in self.ground_stations:
            gs.validate()
        self.space_weather.validate()
        self.sim_settings.validate()

    # -- (de)serialization -------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Scenario":
        data = dict(data)  # shallow copy, don't mutate the caller's dict
        gravity = GravityConfig(**data.pop("gravity", {}))
        sim_settings = SimSettings(**data.pop("sim_settings", {}))
        space_weather = SpaceWeatherConfig(**data.pop("space_weather", {}))
        ground_stations = [GroundStationConfig(**gs) for gs in data.pop("ground_stations", [])]

        spacecraft = []
        for sc in data.pop("spacecraft", []):
            sc = dict(sc)
            orbit = OrbitIC(**sc.pop("orbit"))
            sensors = [SensorConfig(**s) for s in sc.pop("sensors", [])]
            actuators = [ActuatorConfig(**a) for a in sc.pop("actuators", [])]
            spacecraft.append(SpacecraftConfig(orbit=orbit, sensors=sensors, actuators=actuators, **sc))

        return Scenario(
            gravity=gravity, sim_settings=sim_settings, space_weather=space_weather,
            ground_stations=ground_stations, spacecraft=spacecraft, **data,
        )

    def save(self, path: "str | Path") -> None:
        self.validate()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")


def load_scenario(path: "str | Path") -> Scenario:
    """Load, migrate (if needed), and validate a scenario file. Raises
    :class:`ScenarioValidationError` with a specific message on anything
    malformed -- never returns a partially-populated or silently-defaulted
    :class:`Scenario`.
    """
    from . import migrations  # local import: avoids a cycle at module load time

    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        # Covers a missing file, a directory given by mistake, a
        # permissions error, etc. -- all "can't read this path" failures,
        # not just the literal FileNotFoundError case.
        raise ScenarioValidationError(f"{path}: could not read file ({exc.strerror or exc})") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScenarioValidationError(f"{path}: not valid JSON ({exc})") from exc

    if not isinstance(raw, dict) or "schema_version" not in raw:
        raise ScenarioValidationError(f"{path}: missing required top-level 'schema_version' field")

    raw = migrations.migrate(raw)

    try:
        scenario = Scenario.from_dict(raw)
    except (TypeError, KeyError) as exc:
        raise ScenarioValidationError(f"{path}: malformed scenario structure ({exc})") from exc

    scenario.validate()
    return scenario
