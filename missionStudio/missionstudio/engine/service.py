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
:class:`SimulationService` is the ONE GUI-agnostic backend API both the
future GUI (Phase 1+) and a headless/batch CLI call to go from a
:class:`~missionstudio.schema.Scenario` to a
:class:`~missionstudio.engine.results.ResultSet`. It wraps Basilisk's
``SimulationBaseClass``/task-process architecture directly -- there is no
other layer between this class and Basilisk.

Phase 0 scope
-------------
Deliberately narrow, matching exactly what the two-body analytical
validation scenario (``scenarios/two_body_validation.json``,
``tests/test_two_body_validation.py``) needs and nothing more:

* Central-body gravity, point-mass (``gravity.central_body_degree == 0``)
  or spherical harmonics (> 0, Earth-only for now -- GGM03S, the same
  gravity file already used in ``../missionAnalysis``), PLUS third-body
  point-mass perturbers (``gravity.third_body_perturbers``): both the
  central body and every perturber are created via
  ``gravBodyFactory.createBodies()`` and then ``addBodiesTo(sc_object)``
  attaches ALL of them as gravitational contributors to each spacecraft
  -- this is the exact same mechanism (verified, not assumed: see
  ``../missionAnalysis/run_constellation_mission.py``'s own comment on
  ``addBodiesTo()``) that already gives the Moon and Sun as automatic
  third-body perturbers there, with no extra per-body wiring needed
  beyond creating them. An earlier version of this docstring claimed
  third-body perturbers were schema-only and not actually wired up here;
  that was wrong (this service already adds them) and has been corrected.
* One or more spacecraft, each from a classical-elements, Cartesian, or
  TLE initial condition (:class:`~missionstudio.schema.OrbitIC`).
* Orbital dynamics only -- attitude integrates (Basilisk always integrates
  it), but nothing controls or reads it yet.
* A single dynamics task, propagated for ``sim_settings.duration_days``.

Explicitly NOT wired up yet (validated by the schema and carried through
save/load starting now, so the schema doesn't need to change shape later,
but silently ignored by this service until the phase that implements it):
drag, SRP, space weather (space weather HAS its own resolver in
``engine/spaceweather.py`` -- it just isn't connected to a drag model
here, since drag itself isn't wired up). The Phase 1 GUI (see ``gui/``)
deliberately does not expose editors for these either, for the same
reason: a control that looks like it configures simulated behavior but
silently doesn't is worse than not offering it yet.

Phase 2 scope
-------------
Adds attitude sensors, actuators, FSW pointing/control modes, and Vizard
integration on top of Phase 0's propagation-only baseline. All the actual
guidance/control/actuation chain construction lives in ``engine/fsw.py``
(kept separate so this file stays orchestration-only) -- see that module's
docstring for the exact Basilisk module each ``fsw_mode``/sensor kind/
actuator kind maps to, and for every scoping decision made along the way
(e.g. why ``locationPointing``'s ``target_body`` option and the
``"thruster"``/``"magnetic_torque_rod"`` actuator kinds are schema-valid
but not built here). ``engine/vizard.py`` covers the Vizard integration,
triggered via :class:`SimulationService`'s own ``vizard_request`` constructor
parameter (an ``engine.vizard.VizardRequest``).

Phase 3 scope
-------------
Adds ground-station ACCESS analysis and Monte Carlo batch execution, per
the roadmap's "Phase 3: Monte Carlo + access analysis + packaging".

* Ground-station access: every :class:`schema.scenario.GroundStationConfig`
  now gets a ``groundLocation.GroundLocation`` (used both as a
  ``locationPointing`` target, per Phase 2, and for access analysis), and
  once every spacecraft is built, :func:`engine.fsw.add_access_analysis`
  is called once per station against the FULL spacecraft list -- every
  station sees every spacecraft, which is the standard access-analysis
  question ("when can station X see spacecraft Y"), not just the ones a
  station happens to be a pointing target for. :meth:`run` records
  ``hasAccess``/``slantRange``/``elevation``/``azimuth`` per
  (station, spacecraft) pair.
* Monte Carlo: lives in ``engine/monte_carlo.py``, not here --
  :meth:`build` grew an ``initialize`` parameter (default ``True``)
  specifically so that module can build a sim, apply
  ``Basilisk.utilities.MonteCarlo`` dispersions to it, and only THEN call
  ``InitializeSimulation()``/``ConfigureStopTime()`` itself (calling
  ``InitializeSimulation()`` before dispersions are applied would `Reset()`
  every module against the UN-dispersed nominal values, silently
  defeating the dispersion). See that module's docstring for the full
  design and its own scoping notes (e.g. why Cartesian position/velocity
  dispersion is deliberately not offered).

Packaging is covered in ``packaging/`` (build scripts, installer, desktop
entry) and ``missionStudio/README.md``'s packaging section, not in this
module -- there's no runtime code for it.

Verification status
--------------------
Requires a Basilisk build. A from-source build inside this project's
sandbox was attempted early on and failed (blocked Conan Center network
access); later, ``pip install "bsk[all]"`` (Basilisk's own published PyPI
package) turned out to work in that same sandbox -- see
``missionStudio/README.md``'s "Getting started" section for the working
install path this project actually verified.

Against that real build, ``build()`` was confirmed to run correctly
through gravity/SPICE-interface construction, spacecraft assembly (mass,
inertia, orbit IC, integrator selection), and attitude/sensor/actuator/
ground-station wiring -- it fails only at the SPICE kernel DOWNLOAD step
inside ``engine.kernels``, because that sandbox's network egress to NAIF's
kernel host was blocked (see ``kernels.py``'s own verification note); this
is an environment limitation, not a code path that was skipped. A real
bug was found and fixed this way in ``engine/time_system.py`` (a bare
``import pyswice`` that doesn't match the published package's module
layout) -- see that module's own docstring. Every Basilisk module/class
this file and ``engine/fsw.py``/``vizard.py``/``monte_carlo.py`` import
was individually confirmed to exist under the expected name in that real
build. Full end-to-end execution (a run that gets PAST kernel loading) was
NOT achieved in this sandbox, for the network reason above -- that
remains to be exercised on a machine with ordinary internet access, ideally
starting with ``tests/test_two_body_validation.py``.

The calling conventions in this file also mirror the same verified API
calls already exercised (and long since run against a real Basilisk
build) in ``../missionAnalysis/run_constellation_mission.py`` earlier in
this project (``gravBodyFactory``, ``spacecraft.Spacecraft``,
``svIntegrators``, ``orbitalMotion``). The integrator class lookup (see
``_INTEGRATORS`` below) was confirmed both by directly listing
``src/simulation/dynamics/Integrators/`` in this checkout and, now, by
import against a real (if newer/PyPI-sourced) Basilisk build -- note that
build also exposes ``svIntegratorRK4``, which this checkout's own source
does not; ``_INTEGRATORS`` intentionally still doesn't offer it, since
this schema targets what THIS checkout ships, not whatever a given
installed version happens to add.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from Basilisk.simulation import spacecraft, svIntegrators
from Basilisk.utilities import SimulationBaseClass, macros, orbitalMotion, simHelpers, simIncludeGravBody
from Basilisk.utilities.supportDataTools.dataFetcher import DataFile, get_path

from ..schema.scenario import OrbitIC, Scenario
from . import fsw, kernels, time_system, vizard
from .results import ResultSet, TimeSeries
from .vizard import VizardRequest

# Maps schema.SimSettings.integrator -> the svIntegrator* class it selects.
# Every entry here is a class this Basilisk checkout actually ships (see
# schema.scenario.SUPPORTED_INTEGRATORS for the matching validation list
# and its provenance note) -- deliberately no "rk4" entry.
_INTEGRATORS = {
    "euler": svIntegrators.svIntegratorEuler,
    "rk2": svIntegrators.svIntegratorRK2,
    "rkf45": svIntegrators.svIntegratorRKF45,
    "rkf78": svIntegrators.svIntegratorRKF78,
}


class SimulationServiceError(Exception):
    """Raised on anything that prevents building or running the
    simulation -- an unsupported configuration, a kernel fetch failure
    (see :mod:`engine.kernels`), a malformed orbit IC, etc. Always carries
    a specific, actionable message; this service never silently skips a
    requested feature.
    """


def _orbit_ic_to_rv(mu: float, orbit: OrbitIC):
    """(r_N, v_N) [m], [m/s] from a schema.OrbitIC, for any of its three
    forms. ``orbit.validate()`` is assumed to have already been called
    (Scenario.validate() does this) -- this function trusts the fields for
    ``orbit.type`` are populated.
    """
    if orbit.type == "classical_elements":
        oe = orbitalMotion.ClassicElements()
        oe.a = orbit.semi_major_axis_km * 1000.0
        oe.e = orbit.eccentricity
        oe.i = np.radians(orbit.inclination_deg)
        oe.Omega = np.radians(orbit.raan_deg)
        oe.omega = np.radians(orbit.arg_periapsis_deg)
        oe.f = np.radians(orbit.true_anomaly_deg)
        return orbitalMotion.elem2rv(mu, oe)

    if orbit.type == "cartesian":
        r_N = np.array(orbit.position_km, dtype=float) * 1000.0
        v_N = np.array(orbit.velocity_km_s, dtype=float) * 1000.0
        return r_N, v_N

    if orbit.type == "tle":
        # tleHandling.satTle2elem() reads from a FILE (one or more TLEs),
        # not raw line strings -- the schema stores the two lines directly
        # for JSON readability, so bridge that with a short-lived temp file.
        from Basilisk.utilities import tleHandling

        fd, tmp_path = tempfile.mkstemp(suffix=".tle")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(orbit.tle_line1.rstrip("\n") + "\n")
                f.write(orbit.tle_line2.rstrip("\n") + "\n")
            elements_list, _metadata_list = tleHandling.satTle2elem(tmp_path)
        finally:
            os.unlink(tmp_path)
        if not elements_list:
            raise SimulationServiceError("TLE parsing (tleHandling.satTle2elem) returned no elements")
        return orbitalMotion.elem2rv(mu, elements_list[0])

    raise SimulationServiceError(f"unknown orbit IC type {orbit.type!r}")  # unreachable if orbit.validate() passed


@dataclass
class _SpacecraftHandle:
    name: str
    sc_object: object
    recorder: object
    # Phase 2: all None/empty unless sc_config.fsw_mode/sensors were set.
    nav_recorder: Optional[object] = None
    control_torque_recorder: Optional[object] = None
    rw_speed_recorder: Optional[object] = None
    num_rw: int = 0
    sensor_recorders: Dict[str, object] = field(default_factory=dict)  # sensor.name -> (kind, recorder)


class SimulationService:
    """One instance per run -- create a fresh :class:`SimulationService`
    for each :class:`Scenario` you execute rather than reusing one across
    structurally different scenarios (mirrors Basilisk's own
    ``SimBaseClass``, which is not designed to be reset and rebuilt).
    """

    def __init__(self, scenario: Scenario, vizard_request: Optional[VizardRequest] = None):
        self.scenario = scenario
        self.vizard_request = vizard_request
        self.scSim: Optional[SimulationBaseClass.SimBaseClass] = None
        self.mu: Optional[float] = None
        self._handles: Dict[str, _SpacecraftHandle] = {}
        self._sun_state_out_msg = None
        self._ground_locations: Dict[str, object] = {}
        self._mag_field_model = None
        self._access_recorders: Dict[tuple, object] = {}  # (ground_station_name, spacecraft_name) -> recorder

    @property
    def spacecraft_handles(self) -> Dict[str, "_SpacecraftHandle"]:
        """Read-only view of this run's per-spacecraft handles (``sc_object``,
        recorders, ...), keyed by spacecraft name. Only populated after
        :meth:`build`. ``engine.monte_carlo`` uses this to attach dispersion
        accessor methods to the sim object -- everything else should go
        through :meth:`run`'s :class:`~missionstudio.engine.results.ResultSet`
        instead.
        """
        return dict(self._handles)

    def build(self, initialize: bool = True) -> None:
        """Assemble the Basilisk simulation from ``self.scenario`` without
        running it. Safe to call at most once per instance (see the class
        docstring); :meth:`run` calls this automatically if it hasn't been
        called yet.

        Args:
            initialize: when ``True`` (the default), calls
                ``InitializeSimulation()``/``ConfigureStopTime()`` before
                returning, exactly as Phase 0/1/2 always did. Pass
                ``False`` only when the caller needs to mutate the built
                sim (e.g. apply Monte Carlo dispersions -- see
                ``engine/monte_carlo.py``) BEFORE those are called; the
                caller is then responsible for calling them itself once
                ready.
        """
        if self.scSim is not None:
            raise SimulationServiceError(
                "build() was already called on this SimulationService -- create a new instance per run"
            )

        scenario = self.scenario
        scenario.validate()  # re-validate: the scenario object may have been mutated after load
        gravity = scenario.gravity
        sim_settings = scenario.sim_settings

        integrator_cls = _INTEGRATORS.get(sim_settings.integrator)
        if integrator_cls is None:  # unreachable if sim_settings.validate() passed; kept for a clear error anyway
            raise SimulationServiceError(
                f"integrator {sim_settings.integrator!r} has no engine.service mapping "
                f"(known: {sorted(_INTEGRATORS)})"
            )

        self.scSim = SimulationBaseClass.SimBaseClass()
        dyn_process = self.scSim.CreateNewProcess("dynProcess", priority=100)
        dyn_task_name = "dynTask"
        dyn_process.addTask(
            self.scSim.CreateNewTask(dyn_task_name, macros.sec2nano(sim_settings.dynamics_task_rate_s))
        )

        grav_factory = simIncludeGravBody.gravBodyFactory()
        body_names = [gravity.central_body]
        for name in gravity.third_body_perturbers:
            if name not in body_names:
                body_names.append(name)
        grav_bodies = grav_factory.createBodies(body_names)
        central_body = grav_bodies[gravity.central_body]
        central_body.isCentralBody = True

        if gravity.central_body_degree > 0:
            if gravity.central_body != "earth":
                raise SimulationServiceError(
                    "spherical-harmonics gravity (gravity.central_body_degree > 0) is only wired up "
                    f"for 'earth' in Phase 0 (GGM03S data); {gravity.central_body!r} needs "
                    "gravity.central_body_degree == 0 (point-mass) until engine.service is extended "
                    "with that body's gravity-field file."
                )
            central_body.useSphericalHarmonicsGravityModel(
                str(get_path(DataFile.LocalGravData.GGM03S)), gravity.central_body_degree
            )
        mu = central_body.mu
        self.mu = mu
        self.grav_factory = grav_factory

        spice_time_string = time_system.utc_iso_to_spice_string(scenario.epoch_utc)
        self.spice_object = kernels.build_spice_interface(grav_factory, spice_time_string, epoch_in_msg=True)
        self.scSim.AddModelToTask(dyn_task_name, self.spice_object, 500)

        # -- Phase 2 shared (scenario-level) infrastructure, built once before
        # the per-spacecraft loop below: the "sun" SPICE ephemeris message
        # (for simpleNav's vehSunPntBdy / coarse_sun_sensor -- only present
        # if "sun" is actually SPICE-tracked, see engine.fsw's docstring for
        # why this is a precondition rather than something added silently),
        # locationPointing's ground-station targets, and a shared Earth
        # magnetic-field model for any magnetometer sensors.
        if "sun" in body_names:
            self._sun_state_out_msg = self.spice_object.planetStateOutMsgs[body_names.index("sun")]

        central_body_state_out_msg = self.spice_object.planetStateOutMsgs[body_names.index(gravity.central_body)]

        # Phase 3: every ground station is built (used as both a possible
        # locationPointing target and an access-analysis station), not just
        # ones a spacecraft's fsw_params actually targets -- access analysis
        # is a per-station question independent of pointing.
        for gs_config in scenario.ground_stations:
            ground_location = fsw.build_ground_location(
                self.scSim, dyn_task_name, gs_config, central_body.radEquator,
                central_body_state_out_msg, sc_state_out_msgs=[],
            )
            self._ground_locations[gs_config.name] = ground_location

        needs_magnetometer = any(
            sensor.kind == "magnetometer" for sc in scenario.spacecraft for sensor in sc.sensors
        )
        if needs_magnetometer and gravity.central_body == "earth":
            self._mag_field_model = fsw.build_magnetic_field_wmm(
                self.scSim, dyn_task_name, central_body_state_out_msg, central_body.radEquator
            )

        sc_objects_in_order: List = []
        rw_effectors_in_order: List = []

        for sc_config in scenario.spacecraft:
            sc_object = spacecraft.Spacecraft()
            sc_object.ModelTag = sc_config.name
            sc_object.hub.mHub = sc_config.dry_mass_kg
            sc_object.hub.IHubPntBc_B = simHelpers.np2EigenMatrix3d(sc_config.inertia_kg_m2)
            sc_object.hub.sigma_BNInit = [[v] for v in sc_config.sigma_bn_init]
            sc_object.hub.omega_BN_BInit = [[v] for v in sc_config.omega_bn_b_init_rad_s]

            r_N, v_N = _orbit_ic_to_rv(mu, sc_config.orbit)
            sc_object.hub.r_CN_NInit = r_N
            sc_object.hub.v_CN_NInit = v_N

            sc_object.setIntegrator(integrator_cls(sc_object))
            grav_factory.addBodiesTo(sc_object)
            self.scSim.AddModelToTask(dyn_task_name, sc_object, 10)

            recorder = sc_object.scStateOutMsg.recorder()
            self.scSim.AddModelToTask(dyn_task_name, recorder)

            handle = _SpacecraftHandle(sc_config.name, sc_object, recorder)
            sc_objects_in_order.append(sc_object)

            # -- Phase 2: sensors are independent of fsw_mode (they read
            # truth spacecraft state / SPICE / the magnetic-field model
            # directly, not simpleNav -- see engine.fsw.attach_sensors), so
            # they're attached regardless of whether attitude control is on.
            if sc_config.sensors:
                try:
                    sensor_out_msgs = fsw.attach_sensors(
                        self.scSim, dyn_task_name, sc_config.name, sc_object, sc_config.sensors,
                        sun_state_out_msg=self._sun_state_out_msg, mag_field_model=self._mag_field_model,
                    )
                except fsw.FswError as exc:
                    raise SimulationServiceError(str(exc)) from exc
                for sensor in sc_config.sensors:
                    handle.sensor_recorders[sensor.name] = (sensor.kind, sensor_out_msgs[sensor.name].recorder())
                    self.scSim.AddModelToTask(dyn_task_name, handle.sensor_recorders[sensor.name][1])

            if sc_config.actuators and sc_config.fsw_mode is None:
                raise SimulationServiceError(
                    f"{sc_config.name}: actuators are configured but fsw_mode is None -- an actuator needs a "
                    "guidance+control chain (fsw_mode) commanding it, or it will never receive a torque "
                    "command. Set fsw_mode, or remove the actuator(s)."
                )

            rw_effector_for_viz = None
            if sc_config.fsw_mode is not None:
                unsupported_kinds = sorted({
                    a.kind for a in sc_config.actuators if a.kind in ("thruster", "magnetic_torque_rod")
                })
                if unsupported_kinds:
                    raise SimulationServiceError(
                        f"{sc_config.name}: actuator kind(s) {unsupported_kinds} are schema-valid but not "
                        "wired up by engine.service in Phase 2 (see engine.fsw's module docstring)"
                    )

                nav = fsw.build_simple_nav(
                    self.scSim, dyn_task_name, sc_config.name, sc_object, sun_state_out_msg=self._sun_state_out_msg
                )
                veh_config_msg = fsw.build_vehicle_config_msg(sc_config.inertia_kg_m2)
                try:
                    guid_msg = fsw.build_guidance(
                        self.scSim, dyn_task_name, sc_config.name, sc_config.fsw_mode, sc_config.fsw_params,
                        nav, mu, self._ground_locations,
                    )
                except fsw.FswError as exc:
                    raise SimulationServiceError(str(exc)) from exc

                rw_actuators = [a for a in sc_config.actuators if a.kind == "reaction_wheel"]
                if rw_actuators:
                    _, rw_state_effector, rw_config_msg = fsw.build_reaction_wheels(
                        self.scSim, dyn_task_name, sc_config.name, sc_object, rw_actuators
                    )
                    handle.num_rw = len(rw_actuators)
                    mrp = fsw.build_mrp_feedback(
                        self.scSim, dyn_task_name, sc_config.name, guid_msg, veh_config_msg, sc_config.control_params,
                        rw_config_msg=rw_config_msg, rw_speed_out_msg=rw_state_effector.rwSpeedOutMsg,
                    )
                    fsw.build_rw_motor_torque(self.scSim, dyn_task_name, sc_config.name, mrp, rw_config_msg,
                                               rw_state_effector)
                    handle.rw_speed_recorder = rw_state_effector.rwSpeedOutMsg.recorder()
                    self.scSim.AddModelToTask(dyn_task_name, handle.rw_speed_recorder)
                    rw_effector_for_viz = rw_state_effector
                else:
                    mrp = fsw.build_mrp_feedback(
                        self.scSim, dyn_task_name, sc_config.name, guid_msg, veh_config_msg, sc_config.control_params
                    )
                    fsw.build_idealized_actuation(self.scSim, dyn_task_name, sc_config.name, sc_object, mrp)

                handle.nav_recorder = nav.attOutMsg.recorder()
                handle.control_torque_recorder = mrp.cmdTorqueOutMsg.recorder()
                self.scSim.AddModelToTask(dyn_task_name, handle.nav_recorder)
                self.scSim.AddModelToTask(dyn_task_name, handle.control_torque_recorder)

            rw_effectors_in_order.append(rw_effector_for_viz)
            self._handles[sc_config.name] = handle

        # Phase 3: access analysis -- every ground station sees every
        # spacecraft, now that all spacecraft exist (see fsw.add_access_analysis).
        # accessOutMsgs[i] corresponds to sc_objects_in_order[i]: fsw.add_access_analysis
        # calls addSpacecraftToModel in exactly that order (verified indexing
        # convention, see that function's docstring).
        for gs_name, ground_location in self._ground_locations.items():
            fsw.add_access_analysis(ground_location, sc_objects_in_order)
            for index, sc_object in enumerate(sc_objects_in_order):
                recorder = ground_location.accessOutMsgs[index].recorder()
                self.scSim.AddModelToTask(dyn_task_name, recorder)
                self._access_recorders[(gs_name, sc_object.ModelTag)] = recorder

        if self.vizard_request is not None:
            try:
                vizard.enable_vizard(
                    self.scSim, dyn_task_name, sc_objects_in_order, self.vizard_request,
                    rw_effectors_by_spacecraft=rw_effectors_in_order,
                    ground_stations=self._ground_locations, central_body_name=gravity.central_body,
                )
            except vizard.VizardError as exc:
                raise SimulationServiceError(str(exc)) from exc

        self.dyn_task_name = dyn_task_name
        if initialize:
            self.scSim.InitializeSimulation()
            stop_time_s = sim_settings.duration_days * 86400.0
            self.scSim.ConfigureStopTime(macros.sec2nano(stop_time_s))

    def run(self) -> ResultSet:
        """Build (if not already built) and execute the simulation, then
        extract every spacecraft's logged time histories into a
        :class:`~missionstudio.engine.results.ResultSet`: always
        position/velocity, plus (Phase 2, only for a spacecraft that
        actually has them configured) attitude/body-rate/sun-heading,
        commanded control torque, reaction wheel speeds, and one series per
        attached sensor.
        """
        if self.scSim is None:
            self.build()

        self.scSim.ExecuteSimulation()

        result = ResultSet(scenario_name=self.scenario.name)
        for name, handle in self._handles.items():
            t_s = handle.recorder.times() * macros.NANO2SEC
            result.add(TimeSeries(f"{name}.position_N", t_s, ("x", "y", "z"), handle.recorder.r_BN_N, units="m"))
            result.add(TimeSeries(f"{name}.velocity_N", t_s, ("x", "y", "z"), handle.recorder.v_BN_N, units="m/s"))

            if handle.nav_recorder is not None:
                nav_t_s = handle.nav_recorder.times() * macros.NANO2SEC
                result.add(TimeSeries(f"{name}.attitude_sigma_BN", nav_t_s, ("s1", "s2", "s3"),
                                       handle.nav_recorder.sigma_BN, units="-"))
                result.add(TimeSeries(f"{name}.body_rate_omega_BN_B", nav_t_s, ("x", "y", "z"),
                                       handle.nav_recorder.omega_BN_B, units="rad/s"))
                result.add(TimeSeries(f"{name}.sun_heading_body", nav_t_s, ("x", "y", "z"),
                                       handle.nav_recorder.vehSunPntBdy, units="-"))
            if handle.control_torque_recorder is not None:
                ctrl_t_s = handle.control_torque_recorder.times() * macros.NANO2SEC
                result.add(TimeSeries(f"{name}.control_torque", ctrl_t_s, ("x", "y", "z"),
                                       handle.control_torque_recorder.torqueRequestBody, units="N*m"))
            if handle.rw_speed_recorder is not None:
                rw_t_s = handle.rw_speed_recorder.times() * macros.NANO2SEC
                wheel_speeds = np.asarray(handle.rw_speed_recorder.wheelSpeeds)[:, :handle.num_rw]
                columns = tuple(f"wheel_{i}" for i in range(handle.num_rw))
                result.add(TimeSeries(f"{name}.rw_speeds", rw_t_s, columns, wheel_speeds, units="rad/s"))

            for sensor_name, (kind, recorder) in handle.sensor_recorders.items():
                sensor_t_s = recorder.times() * macros.NANO2SEC
                series_name = f"{name}.sensor.{sensor_name}"
                if kind == "star_tracker":
                    result.add(TimeSeries(series_name, sensor_t_s, ("q0", "q1", "q2", "q3"),
                                           recorder.qInrtl2Case, units="-"))
                elif kind == "imu":
                    result.add(TimeSeries(f"{series_name}.accel", sensor_t_s, ("x", "y", "z"),
                                           recorder.AccelPlatform, units="m/s^2"))
                    result.add(TimeSeries(f"{series_name}.gyro", sensor_t_s, ("x", "y", "z"),
                                           recorder.AngVelPlatform, units="rad/s"))
                elif kind == "coarse_sun_sensor":
                    result.add(TimeSeries(series_name, sensor_t_s, ("output",), recorder.OutputData, units="-"))
                elif kind == "magnetometer":
                    result.add(TimeSeries(series_name, sensor_t_s, ("x", "y", "z"), recorder.tam_S, units="T"))

        for (gs_name, sc_name), recorder in self._access_recorders.items():
            access_t_s = recorder.times() * macros.NANO2SEC
            series_name = f"{gs_name}.access_to_{sc_name}"
            result.add(TimeSeries(f"{series_name}.has_access", access_t_s, ("has_access",),
                                   recorder.hasAccess, units="-"))
            result.add(TimeSeries(f"{series_name}.slant_range", access_t_s, ("slant_range",),
                                   recorder.slantRange, units="m"))
            result.add(TimeSeries(f"{series_name}.elevation", access_t_s, ("elevation",),
                                   recorder.elevation, units="rad"))
            result.add(TimeSeries(f"{series_name}.azimuth", access_t_s, ("azimuth",),
                                   recorder.azimuth, units="rad"))
        return result
