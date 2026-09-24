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

Explicitly NOT wired up yet in Phase 0 (validated by the schema and
carried through save/load starting now, so the schema doesn't need to
change shape later, but silently ignored by this service until the phase
that implements it): drag, SRP, space weather. The Phase 1 GUI (see
``gui/``) deliberately does not expose editors for these either, for the
same reason: a control that looks like it configures simulated behavior
but silently doesn't is worse than not offering it yet. (Phase 4, below,
is where this gap closes: ``SpacecraftConfig.enable_drag``/``enable_srp``
are wired up there via ``engine/spaceweather.py``'s resolver -> MSIS
atmosphere -> ``dragDynamicEffector``/``radiationPressure``.)

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
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import numpy as np

from Basilisk.simulation import spacecraft, svIntegrators
from Basilisk.utilities import SimulationBaseClass, macros, orbitalMotion, simHelpers, simIncludeGravBody
from Basilisk.utilities.supportDataTools.dataFetcher import DataFile, get_path

from ..schema.scenario import OrbitIC, Scenario
from . import fsw, kernels, link_budget, orbit_maintenance, time_system, vizard
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


# SimulationService.run_live()'s default chunk count when live_step_s isn't
# given -- about this many on_progress callbacks over the whole run,
# regardless of duration_days. A round number, not tuned to any specific
# scenario; see run_live()'s docstring for the dynamics_task_rate_s clamp
# that keeps a very short run from producing a sub-tick step instead.
#
# Deliberately modest, not e.g. 200+: each callback's _extract_results()
# call redoes O(samples-so-far) work (rebuilds every TimeSeries, including
# the per-sample osculating-elements math, from the FULL recorder history,
# not just this chunk's new samples -- see _extract_results()'s
# docstring), so the total extraction work across a live run scales with
# frame count. 60 still reads as smooth/live to a user watching a plot
# update, while keeping that multiplier small relative to a single
# non-live run() call.
_LIVE_DEFAULT_FRAMES = 60


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
        if orbit.anomaly_type == "mean":
            # elem2rv only accepts true anomaly -- solve Kepler's equation
            # (mean -> eccentric, via orbitalMotion's own Newton iteration)
            # then map eccentric -> true, both directly from orbitalMotion
            # rather than reimplementing either conversion here.
            eccentric_anomaly = orbitalMotion.M2E(np.radians(orbit.mean_anomaly_deg), orbit.eccentricity)
            oe.f = orbitalMotion.E2f(eccentric_anomaly, orbit.eccentricity)
        else:
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


def _osculating_elements(mu: float, r_bn_n: np.ndarray, v_bn_n: np.ndarray) -> Dict[str, np.ndarray]:
    """Osculating classical orbital elements (a [m], e [-], i/raan/argp/
    true_anomaly [rad]) at every recorded (r, v) sample, via
    ``orbitalMotion.rv2elem`` -- the exact inverse of ``_orbit_ic_to_rv``'s
    classical-elements branch above, run independently at each sample (not
    a smoothed/mean-element fit), so a result plot can show how the ACTUAL
    simulated orbit's shape/orientation evolves, not just position/velocity.

    Near-circular (e -> 0) and/or near-equatorial (i -> 0) samples are a
    known singularity of the classical elements themselves, not a bug here:
    ``rv2elem`` zeroes ``raan``/``argp`` in those cases and folds their
    angle into ``true_anomaly`` instead (e.g. argument of latitude for a
    circular inclined orbit) -- expect those columns to look degenerate
    (flat at 0, or a discontinuity) for a near-circular/near-equatorial
    scenario. This is inherent to osculating classical elements, not
    something a per-sample computation could avoid.
    """
    n = r_bn_n.shape[0]
    a = np.empty(n)
    e = np.empty(n)
    i = np.empty(n)
    raan = np.empty(n)
    argp = np.empty(n)
    true_anomaly = np.empty(n)
    for k in range(n):
        oe = orbitalMotion.rv2elem(mu, r_bn_n[k], v_bn_n[k])
        a[k] = oe.a
        e[k] = oe.e
        i[k] = oe.i
        raan[k] = oe.Omega
        argp[k] = oe.omega
        true_anomaly[k] = oe.f
    return {"a": a, "e": e, "i": i, "raan": raan, "argp": argp, "true_anomaly": true_anomaly}


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
    battery_recorder: Optional[object] = None  # Phase 4: only set if sc_config.power was configured
    battery_module: Optional[object] = None  # Phase 4: the simpleBattery.SimpleBattery itself, for engine.vizard
    station_keeping_controller: Optional[object] = None  # Phase 4: only set if sc_config.station_keeping was configured
    eclipse_out_msg: Optional[object] = None  # Phase 4: only set if power or station_keeping was configured
    phasing_keeping_controller: Optional[object] = None  # Phase 4: only set if sc_config.phasing_keeping was configured
    constant_thrust_controller: Optional[object] = None  # Phase 5: only set if sc_config.constant_thrust was configured


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
        self._access_out_msgs: Dict[tuple, object] = {}  # (ground_station_name, spacecraft_name) -> accessOutMsg, for engine.vizard
        self._eclipse_object = None  # Phase 4: only built if some spacecraft has power or station_keeping configured
        # Phase 4: retains the vizInterface module enable_vizard() returns,
        # and (separately -- see that function's own docstring for why a
        # SWIG VizInterface proxy can't just carry this as one of its own
        # attributes) every custom bridge SysModel it registered on the
        # task. Previously enable_vizard()'s return value was discarded
        # entirely, which let those bridges be garbage-collected while
        # still C++-task-registered -- undefined behavior that could (and
        # did) surface as an unrelated-looking crash much later.
        self._viz = None
        self._viz_access_indicator_bridges = None

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

        # sim_settings.dynamics_task_rate_s is not just a logging/output
        # cadence -- it also bounds how often the SPICE-derived central-body
        # state (position AND rotation, used directly in the gravity force
        # computation) gets refreshed, since self.spice_object below runs on
        # this SAME task. Basilisk only linearly (Euler-step) extrapolates
        # that state BETWEEN refreshes (see GravBodyData::computeGravityInertial()
        # and getEulerSteppedGravBodyPosition() in gravityEffector.cpp), so a
        # coarse rate here introduces a real force-accuracy error even though
        # the integrator itself (see _INTEGRATORS below) may be far more
        # accurate than that. Confirmed empirically, not guessed: holding
        # everything else fixed and only varying this rate on
        # scenarios/two_body_validation.json made its analytical-comparison
        # position error scale roughly with the SQUARE of this value (~202 m
        # at 30 s, ~22 m at 10 s, ~2 m at 3 s, ~0.22 m at 1 s) -- exactly the
        # signature of a first-order truncation error, and completely
        # insensitive to the RKF78 integrator's own relative tolerance
        # (tested directly at both 1e-4 and 1e-14 with no change whatsoever).
        # That two-body validation scenario uses 1.0 s for exactly this
        # reason; scenarios that need tighter absolute accuracy than a 30 s
        # rate provides should do the same.
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
        # Re-zero every SPICE ephemeris output on the central body (SPICE's
        # own observer/"zeroBase" concept -- see spiceInterface.cpp's
        # spkezr_c call, which queries each body's state relative to
        # `zeroBase`, defaulting to the solar system barycenter "SSB").
        # Without this, GravityEffector::updateInertialPosAndVel() (see
        # gravityEffector.cpp) computes r_BN_N/v_BN_N as the CENTRAL BODY'S
        # OWN (SSB-relative, heliocentric-scale) position/velocity PLUS the
        # true central-body-relative integrated state, because it adds
        # r_CN_N (the central body's own SPICE position) on top of the
        # propagated r_BF_N whenever a central body is set -- every
        # consumer of r_BN_N/v_BN_N in this codebase (osculating-element
        # computation below, engine/orbit_maintenance.py's controllers,
        # engine/fsw.py's hillPoint/velocityPoint) assumes r_BN_N is
        # purely central-body-relative, which is only true when the
        # central body's own SPICE position is zero. Setting zeroBase to
        # the central body makes exactly that true (the central body's own
        # planetStateOutMsg reports (0, 0, 0) relative to itself), the
        # same fix Basilisk's own official example applies for the same
        # reason -- see examples/scenarioHohmann.py's
        # `gravFactory.spiceObject.zeroBase = 'Earth'` (SPICE body-name
        # lookup is case-insensitive, so the lowercase
        # gravity.central_body value used here resolves the same way).
        self.spice_object.zeroBase = gravity.central_body
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

        # Phase 4: power budget (schema.scenario.PowerConfig),
        # station-keeping's eclipse-gated reboost burn
        # (schema.scenario.StationKeepingConfig), and SRP (enable_srp,
        # below) all need the real eclipse shadow factor -- built once,
        # shared by every spacecraft that has ANY of them configured (see
        # the per-spacecraft loop below), exactly like the ground
        # locations/magnetic-field model above. Unlike the WMM
        # magnetic-field model, eclipse geometry isn't Earth-specific, so
        # this isn't gated on gravity.central_body == "earth".
        needs_eclipse = any(
            sc.power is not None or sc.station_keeping is not None or sc.enable_srp for sc in scenario.spacecraft
        )
        if needs_eclipse:
            if self._sun_state_out_msg is None:
                raise SimulationServiceError(
                    "a spacecraft has a power budget, station-keeping, or SRP (enable_srp) configured, but "
                    "'sun' is not one of this scenario's SPICE-tracked bodies -- simpleSolarPanel/the eclipse "
                    "gate/SRP needs a sun ephemeris. Add 'sun' to gravity.third_body_perturbers."
                )
            from Basilisk.simulation import eclipse

            self._eclipse_object = eclipse.Eclipse()
            self._eclipse_object.ModelTag = "eclipse"
            self._eclipse_object.sunInMsg.subscribeTo(self._sun_state_out_msg)
            self._eclipse_object.addPlanetToModel(central_body_state_out_msg)
            self.scSim.AddModelToTask(dyn_task_name, self._eclipse_object, 370)

        # Phase 4: atmospheric drag (schema.scenario.SpacecraftConfig.enable_drag)
        # -- built once, shared by every spacecraft that enables it. Ported
        # from ../missionAnalysis/run_constellation_mission.py's identical
        # space-weather -> MSIS atmosphere -> drag-effector chain (NRLMSISE
        # -00, Earth-only, hence the central_body == "earth" requirement
        # below -- there is no non-Earth atmosphere model wired up here,
        # matching the spherical-harmonics-gravity/magnetometer precedent
        # above). Reuses engine.spaceweather's already-built resolver
        # (previously computed but never actually connected to a drag
        # model -- see this module's own "Phase 0 scope" docstring note,
        # now out of date since this fixes exactly that gap) rather than
        # loading a space-weather file ad hoc.
        needs_drag = any(sc.enable_drag for sc in scenario.spacecraft)
        atmo_module = None
        wind_model = None
        if needs_drag:
            if gravity.central_body != "earth":
                raise SimulationServiceError(
                    "atmospheric drag (enable_drag) is only wired up for 'earth' (NRLMSISE-00 has no "
                    f"non-Earth atmosphere model here); {gravity.central_body!r} needs enable_drag=False "
                    "on every spacecraft."
                )
            from Basilisk.simulation import msisAtmosphere, spaceWeatherData, zeroWindModel

            from . import spaceweather as sw

            start_utc = datetime.fromisoformat(scenario.epoch_utc)
            end_utc = start_utc + timedelta(days=sim_settings.duration_days)
            try:
                resolved_sw = sw.resolve(
                    scenario.space_weather.source, start_utc, end_utc,
                    local_file_path=scenario.space_weather.local_file_path,
                    cache_dir=scenario.space_weather.cache_dir,
                )
            except sw.SpaceWeatherError as exc:
                raise SimulationServiceError(f"could not resolve space weather for atmospheric drag: {exc}") from exc

            sw_module = spaceWeatherData.SpaceWeatherData()
            sw_module.ModelTag = "spaceWeatherData"
            sw_module.loadSpaceWeatherFile(str(resolved_sw.path))
            sw_module.epochInMsg.subscribeTo(grav_factory.epochMsg)
            self.scSim.AddModelToTask(dyn_task_name, sw_module, 400)

            atmo_module = msisAtmosphere.MsisAtmosphere()
            atmo_module.ModelTag = "msisAtmosphere"
            atmo_module.epochInMsg.subscribeTo(grav_factory.epochMsg)
            atmo_module.planetPosInMsg.subscribeTo(central_body_state_out_msg)
            for msg_index in range(23):  # fixed count of space-weather sub-messages msisAtmosphere reads
                atmo_module.swDataInMsgs[msg_index].subscribeTo(sw_module.swDataOutMsgs[msg_index])
            self.scSim.AddModelToTask(dyn_task_name, atmo_module, 390)

            wind_model = zeroWindModel.ZeroWindModel()
            wind_model.ModelTag = "zeroWind"
            wind_model.planetPosInMsg.subscribeTo(central_body_state_out_msg)
            self.scSim.AddModelToTask(dyn_task_name, wind_model, 380)

        sc_objects_in_order: List = []
        rw_effectors_in_order: List = []
        eclipse_index = 0  # only incremented for spacecraft that actually have power/station_keeping/enable_srp
        drag_index = 0  # only incremented for spacecraft that actually have enable_drag

        for sc_config in scenario.spacecraft:
            sc_object = spacecraft.Spacecraft()
            sc_object.ModelTag = sc_config.name
            # See SpacecraftConfig.dry_mass_kg's docstring: station-keeping/
            # constant-thrust propellant is additional mass on top of the
            # dry mass, not already counted in it -- independent propellant
            # budgets, so both are added if both are configured (see
            # ConstantThrustConfig's docstring).
            initial_mass_kg = sc_config.dry_mass_kg
            if sc_config.station_keeping is not None:
                initial_mass_kg += sc_config.station_keeping.propellant_kg
            if sc_config.constant_thrust is not None:
                initial_mass_kg += sc_config.constant_thrust.propellant_kg
            sc_object.hub.mHub = initial_mass_kg
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

            # Phase 4: this spacecraft's eclipse output message, shared by
            # the power-budget and station-keeping blocks below -- added to
            # the shared eclipse model at most once per spacecraft (adding
            # it twice would desync eclipseOutMsgs' indexing from
            # sc_objects_in_order for every spacecraft after it).
            sc_eclipse_out_msg = None
            if sc_config.power is not None or sc_config.station_keeping is not None or sc_config.enable_srp:
                self._eclipse_object.addSpacecraftToModel(sc_object.scStateOutMsg)
                sc_eclipse_out_msg = self._eclipse_object.eclipseOutMsgs[eclipse_index]
                eclipse_index += 1
                handle.eclipse_out_msg = sc_eclipse_out_msg

            # -- Phase 4: power budget, independent of fsw_mode/sensors like
            # the sensor block above -- a real simpleSolarPanel/battery, not
            # an analytical estimate, so generated power tracks the actual
            # simulated attitude (panel-normal-to-sun angle) and eclipse
            # state (see schema.scenario.PowerConfig's docstring). Ported
            # from ../missionAnalysis/power_budget.py's wiring pattern,
            # trimmed to a constant bus load (no per-subsystem duty-cycle
            # loads -- missionStudio has no EO-instrument/downlink data
            # model to gate them against).
            if sc_config.power is not None:
                from Basilisk.simulation import simpleBattery, simplePowerSink, simpleSolarPanel

                power_config = sc_config.power

                panel = simpleSolarPanel.SimpleSolarPanel()
                panel.ModelTag = f"{sc_config.name}SolarPanel"
                panel.setPanelParameters(power_config.panel_normal_b, power_config.panel_area_m2,
                                          power_config.panel_efficiency)
                panel.stateInMsg.subscribeTo(sc_object.scStateOutMsg)
                panel.sunInMsg.subscribeTo(self._sun_state_out_msg)
                panel.sunEclipseInMsg.subscribeTo(sc_eclipse_out_msg)
                self.scSim.AddModelToTask(dyn_task_name, panel, 50)

                bus_sink = simplePowerSink.SimplePowerSink()
                bus_sink.ModelTag = f"{sc_config.name}BusPowerSink"
                bus_sink.nodePowerOut = -power_config.bus_idle_power_w  # [W] static always-on load
                self.scSim.AddModelToTask(dyn_task_name, bus_sink, 50)

                battery = simpleBattery.SimpleBattery()
                battery.ModelTag = f"{sc_config.name}Battery"
                battery.storageCapacity = power_config.battery_capacity_wh * 3600.0  # [W*s]
                battery.storedCharge_Init = (
                    power_config.battery_initial_soc * power_config.battery_capacity_wh * 3600.0
                )  # [W*s]
                battery.addPowerNodeToModel(panel.nodePowerOutMsg)
                battery.addPowerNodeToModel(bus_sink.nodePowerOutMsg)
                # Lower priority than the panel/sink above (50) so it reads
                # this tick's fresh generation/load values, not last tick's.
                self.scSim.AddModelToTask(dyn_task_name, battery, 40)

                handle.battery_recorder = battery.batPowerOutMsg.recorder()
                self.scSim.AddModelToTask(dyn_task_name, handle.battery_recorder)
                handle.battery_module = battery

            # -- Phase 4: station-keeping (schema.scenario.StationKeepingConfig)
            # -- independent of fsw_mode/sensors/power like the blocks
            # above; see engine.orbit_maintenance's module docstring.
            if sc_config.station_keeping is not None:
                handle.station_keeping_controller = orbit_maintenance.build_station_keeping(
                    self.scSim, dyn_task_name, sc_config.name, sc_object, mu, central_body.radEquator,
                    sc_config.dry_mass_kg, sc_config.station_keeping, eclipse_out_msg=sc_eclipse_out_msg,
                )

            # -- Phase 5: continuous constant-frame thrust
            # (schema.scenario.ConstantThrustConfig) -- independent of
            # fsw_mode/sensors/power/station_keeping like the blocks above;
            # see engine.orbit_maintenance's ConstantFrameThrustController
            # docstring. Uses its OWN extForceTorque effector (not shared
            # with station_keeping's), so both may be configured together.
            if sc_config.constant_thrust is not None:
                handle.constant_thrust_controller = orbit_maintenance.build_constant_thrust(
                    self.scSim, dyn_task_name, sc_config.name, sc_object,
                    sc_config.dry_mass_kg, sc_config.constant_thrust,
                )

            # -- Phase 4: atmospheric drag (schema.scenario.SpacecraftConfig
            # .enable_drag) -- see the needs_drag/atmo_module/wind_model
            # setup above this loop. addSpacecraftToModel() must only be
            # called for spacecraft that enable it, so drag_index stays in
            # lockstep with atmo_module.envOutMsgs/wind_model.envOutMsgs.
            if sc_config.enable_drag:
                from Basilisk.simulation import dragDynamicEffector

                drag_effector = dragDynamicEffector.DragDynamicEffector()
                drag_effector.ModelTag = f"{sc_config.name}Drag"
                drag_effector.coreParams.projectedArea = sc_config.drag_area_m2  # [m^2]
                drag_effector.coreParams.dragCoeff = sc_config.drag_coeff  # [-]
                sc_object.addDynamicEffector(drag_effector)
                atmo_module.addSpacecraftToModel(sc_object.scStateOutMsg)
                wind_model.addSpacecraftToModel(sc_object.scStateOutMsg)
                drag_effector.atmoDensInMsg.subscribeTo(atmo_module.envOutMsgs[drag_index])
                drag_effector.windVelInMsg.subscribeTo(wind_model.envOutMsgs[drag_index])
                drag_index += 1
                self.scSim.AddModelToTask(dyn_task_name, drag_effector, 100)

            # -- Phase 4: solar radiation pressure (schema.scenario.
            # SpacecraftConfig.enable_srp) -- shares the eclipse model/
            # sc_eclipse_out_msg computed above (the eclipse-needs condition
            # above this loop already includes enable_srp, so
            # sc_eclipse_out_msg is non-None whenever this branch runs).
            if sc_config.enable_srp:
                from Basilisk.simulation import radiationPressure

                srp_effector = radiationPressure.RadiationPressure()
                srp_effector.ModelTag = f"{sc_config.name}Srp"
                srp_effector.area = sc_config.srp_area_m2  # [m^2]
                srp_effector.coefficientReflection = sc_config.srp_coeff  # [-]
                sc_object.addDynamicEffector(srp_effector)
                srp_effector.sunEphmInMsg.subscribeTo(self._sun_state_out_msg)
                srp_effector.sunEclipseInMsg.subscribeTo(sc_eclipse_out_msg)
                self.scSim.AddModelToTask(dyn_task_name, srp_effector, 100)

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

        # Phase 4: constellation phasing-keeping (schema.scenario.PhasingKeepingConfig)
        # -- needs every spacecraft's sc_object/StationKeepingController to
        # already exist (a follower's chief may be defined later in
        # scenario.spacecraft than the follower itself), so this is its
        # own pass after the main per-spacecraft loop above, mirroring
        # access analysis/Vizard setup below. Scenario.validate() already
        # guarantees phasing_keeping implies station_keeping on the same
        # spacecraft and that chief_spacecraft names a real spacecraft.
        spacecraft_by_name = {sc_config.name: sc_config for sc_config in scenario.spacecraft}
        for sc_config in scenario.spacecraft:
            if sc_config.phasing_keeping is None:
                continue
            chief_config = spacecraft_by_name[sc_config.phasing_keeping.chief_spacecraft]
            if chief_config.orbit.type != "classical_elements":
                raise SimulationServiceError(
                    f"{sc_config.name}: phasing_keeping.chief_spacecraft "
                    f"{chief_config.name!r}'s orbit must be type 'classical_elements' (phasing needs its "
                    f"semi-major axis) -- got {chief_config.orbit.type!r}"
                )
            follower_handle = self._handles[sc_config.name]
            chief_handle = self._handles[chief_config.name]
            follower_handle.phasing_keeping_controller = orbit_maintenance.build_phasing_keeping(
                self.scSim, dyn_task_name, sc_config.name, mu,
                chief_sc_object=chief_handle.sc_object, follower_sc_object=follower_handle.sc_object,
                follower_station_keeping_controller=follower_handle.station_keeping_controller,
                follower_eclipse_out_msg=follower_handle.eclipse_out_msg,
                chief_semi_major_axis_km=chief_config.orbit.semi_major_axis_km,
                config=sc_config.phasing_keeping,
            )

        # Phase 3: access analysis -- every ground station sees every
        # spacecraft, now that all spacecraft exist (see fsw.add_access_analysis).
        # accessOutMsgs[i] corresponds to sc_objects_in_order[i]: fsw.add_access_analysis
        # calls addSpacecraftToModel in exactly that order (verified indexing
        # convention, see that function's docstring).
        for gs_name, ground_location in self._ground_locations.items():
            fsw.add_access_analysis(ground_location, sc_objects_in_order)
            for index, sc_object in enumerate(sc_objects_in_order):
                access_out_msg = ground_location.accessOutMsgs[index]
                recorder = access_out_msg.recorder()
                self.scSim.AddModelToTask(dyn_task_name, recorder)
                self._access_recorders[(gs_name, sc_object.ModelTag)] = recorder
                self._access_out_msgs[(gs_name, sc_object.ModelTag)] = access_out_msg

        if self.vizard_request is not None:
            battery_by_spacecraft = {
                name: handle.battery_module for name, handle in self._handles.items()
                if handle.battery_module is not None
            }
            station_keeping_by_spacecraft = {
                name: handle.station_keeping_controller for name, handle in self._handles.items()
                if handle.station_keeping_controller is not None
            }
            custom_models_by_spacecraft = {
                sc_config.name: {
                    "path": sc_config.vizard_model_path,
                    "offset_m": sc_config.vizard_model_offset_m,
                    "rotation_deg": sc_config.vizard_model_rotation_deg,
                    "scale": sc_config.vizard_model_scale,
                }
                for sc_config in scenario.spacecraft if sc_config.vizard_model_path is not None
            }
            try:
                self._viz, self._viz_access_indicator_bridges = vizard.enable_vizard(
                    self.scSim, dyn_task_name, sc_objects_in_order, self.vizard_request,
                    rw_effectors_by_spacecraft=rw_effectors_in_order,
                    ground_stations=self._ground_locations, central_body_name=gravity.central_body,
                    battery_by_spacecraft=battery_by_spacecraft,
                    station_keeping_by_spacecraft=station_keeping_by_spacecraft,
                    access_out_msgs=self._access_out_msgs,
                    custom_models_by_spacecraft=custom_models_by_spacecraft,
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
        position/velocity plus osculating Keplerian elements (semi-major
        axis, eccentricity, inclination, RAAN, argument of periapsis, true
        anomaly -- see :func:`_osculating_elements`), plus (Phase 2, only
        for a spacecraft that actually has them configured) attitude/
        body-rate/sun-heading, commanded control torque, reaction wheel
        speeds, and one series per attached sensor.

        See :meth:`run_live` for a variant that streams intermediate
        results back while the simulation is still running (e.g. to drive
        a live-updating plot), rather than only once at the end.
        """
        if self.scSim is None:
            self.build()
        self.scSim.ExecuteSimulation()
        return self._extract_results()

    def run_live(self, on_progress: Callable[[ResultSet, float], None],
                 live_step_s: Optional[float] = None) -> ResultSet:
        """Same as :meth:`run`, except the simulation is executed in small
        time chunks and ``on_progress(partial_result, fraction_complete)``
        is called after each one, so a caller (missionStudio's GUI) can
        redraw a plot while the run is still in flight instead of only
        once it finishes.

        This relies on a documented, supported Basilisk pattern: repeated
        ``ConfigureStopTime()``/``ExecuteSimulation()`` pairs. ``ExecuteSimulation()``
        always resumes from wherever ``TotalSim.NextTaskTime`` currently
        is (see ``SimulationBaseClass.ExecuteSimulation()``'s
        ``CheckStopCondition()`` loop) rather than restarting from t=0, so
        calling it again with a larger stop time just continues the same
        run. Recorders keep accumulating samples across chunks exactly as
        they would across one uninterrupted call, so each chunk's
        :meth:`_extract_results` is simply "whatever has been logged so
        far" -- not a separate bookkeeping path from :meth:`run`. Which
        series exist is decided once by ``self.scenario``/:meth:`build`,
        never by how much data has been recorded yet, so the set of series
        names is identical across every ``on_progress`` call (including
        the first) and matches :meth:`run`'s -- only the amount of data in
        each grows.

        Args:
            on_progress: called after each chunk with
                ``(partial_result, fraction_complete)``, ``fraction_complete``
                in ``[0, 1]`` (exactly ``1.0`` on the final call). Any
                exception it raises propagates out of ``run_live`` and
                aborts the run, same as an exception anywhere else in the
                simulation would.
            live_step_s: how much sim time to advance per chunk/callback
                [s]. Defaults to
                ``duration_days * 86400 / _LIVE_DEFAULT_FRAMES`` (about
                ``_LIVE_DEFAULT_FRAMES`` callbacks over the whole run),
                clamped to never be smaller than one dynamics tick
                (``sim_settings.dynamics_task_rate_s``) -- ``ExecuteSimulation()``
                has real per-call overhead, so a sub-tick step would only
                add Python-loop cost with no extra simulated time to show
                for it.
        """
        if self.scSim is None:
            self.build()

        stop_time_s = self.scenario.sim_settings.duration_days * 86400.0  # [s]
        stop_time_ns = macros.sec2nano(stop_time_s)
        if stop_time_ns <= 0:
            # sim_settings.validate() only requires duration_days > 0, not
            # that it's large enough to round to at least 1 ns once
            # converted -- reachable from a scenario built/edited outside
            # the GUI's spinbox floor (e.g. a hand-written or scripted
            # scenario JSON). Without this guard, fraction_complete's
            # division below would raise a bare ZeroDivisionError instead
            # of a clear, actionable error.
            raise SimulationServiceError(
                f"sim_settings.duration_days={self.scenario.sim_settings.duration_days!r} is too small to "
                f"simulate (rounds to 0 ns) -- use a larger duration"
            )
        if live_step_s is None:
            live_step_s = max(
                self.scenario.sim_settings.dynamics_task_rate_s,
                stop_time_s / _LIVE_DEFAULT_FRAMES,
            )  # [s]
        step_ns = max(1, macros.sec2nano(live_step_s))

        next_stop_ns = min(step_ns, stop_time_ns)
        while True:
            self.scSim.ConfigureStopTime(next_stop_ns)
            self.scSim.ExecuteSimulation()
            fraction_complete = min(1.0, next_stop_ns / stop_time_ns)
            on_progress(self._extract_results(), fraction_complete)
            if next_stop_ns >= stop_time_ns:
                break
            next_stop_ns = min(next_stop_ns + step_ns, stop_time_ns)

        return self._extract_results()

    def _extract_results(self) -> ResultSet:
        """Reads every recorder currently attached in ``self._handles``
        into a fresh :class:`~missionstudio.engine.results.ResultSet` --
        whatever has been logged so far, whether that's a full run's worth
        (:meth:`run`) or one chunk's worth mid-run (:meth:`run_live`)."""
        result = ResultSet(scenario_name=self.scenario.name)
        for name, handle in self._handles.items():
            t_s = handle.recorder.times() * macros.NANO2SEC
            result.add(TimeSeries(f"{name}.position_N", t_s, ("x", "y", "z"), handle.recorder.r_BN_N, units="m"))
            result.add(TimeSeries(f"{name}.velocity_N", t_s, ("x", "y", "z"), handle.recorder.v_BN_N, units="m/s"))

            # Osculating Keplerian elements -- see _osculating_elements()'s
            # docstring for the near-circular/near-equatorial caveat. One
            # TimeSeries per element (not one combined series), matching
            # this method's own convention for mixed-unit quantities below
            # (e.g. station_keeping's separate .burn_on/.delta_v series).
            oe = _osculating_elements(self.mu, handle.recorder.r_BN_N, handle.recorder.v_BN_N)
            result.add(TimeSeries(f"{name}.orbit_elements.semi_major_axis", t_s, ("a",), oe["a"], units="m"))
            result.add(TimeSeries(f"{name}.orbit_elements.eccentricity", t_s, ("e",), oe["e"], units="-"))
            result.add(TimeSeries(f"{name}.orbit_elements.inclination", t_s, ("i",), oe["i"], units="rad"))
            result.add(TimeSeries(f"{name}.orbit_elements.raan", t_s, ("raan",), oe["raan"], units="rad"))
            result.add(TimeSeries(f"{name}.orbit_elements.arg_periapsis", t_s, ("argp",), oe["argp"], units="rad"))
            result.add(TimeSeries(f"{name}.orbit_elements.true_anomaly", t_s, ("true_anomaly",),
                                   oe["true_anomaly"], units="rad"))

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

            if handle.battery_recorder is not None:
                battery_t_s = handle.battery_recorder.times() * macros.NANO2SEC
                result.add(TimeSeries(f"{name}.battery_charge", battery_t_s, ("charge",),
                                       np.asarray(handle.battery_recorder.storageLevel) / 3600.0, units="W*hr"))
                result.add(TimeSeries(f"{name}.battery_net_power", battery_t_s, ("net_power",),
                                       handle.battery_recorder.currentNetPower, units="W"))

            if handle.station_keeping_controller is not None:
                controller = handle.station_keeping_controller
                sk_t_s = np.asarray(controller.tLog)
                result.add(TimeSeries(f"{name}.station_keeping.altitude", sk_t_s, ("raw", "smoothed"),
                                       np.column_stack([controller.altLog, controller.smoothAltLog]), units="m"))
                result.add(TimeSeries(f"{name}.station_keeping.burn_on", sk_t_s, ("burn_on",),
                                       np.asarray(controller.burnLog), units="-"))
                result.add(TimeSeries(f"{name}.station_keeping.propellant_remaining", sk_t_s,
                                       ("propellant_remaining",), np.asarray(controller.propellantLog), units="kg"))
                result.add(TimeSeries(f"{name}.station_keeping.delta_v", sk_t_s, ("cumulative_delta_v",),
                                       np.asarray(controller.deltaVLog), units="m/s"))

            if handle.phasing_keeping_controller is not None:
                phase_controller = handle.phasing_keeping_controller
                pk_t_s = np.asarray(phase_controller.tLog)
                result.add(TimeSeries(f"{name}.phasing_keeping.separation_error", pk_t_s, ("error_deg",),
                                       np.asarray(phase_controller.errorDegLog), units="deg"))
                result.add(TimeSeries(f"{name}.phasing_keeping.state", pk_t_s, ("state",),
                                       np.asarray(phase_controller.stateLog, dtype=float), units="-"))
                # This controller's OWN delta-V only -- see
                # engine.orbit_maintenance.PhasingKeepingController's
                # docstring: propellant/tank is shared with (and already
                # fully reflected in) {name}.station_keeping.propellant_remaining
                # above, but each controller tracks its own delta-V
                # separately, so total delta-V for this spacecraft is the
                # sum of this series' final value and
                # {name}.station_keeping.delta_v's.
                result.add(TimeSeries(f"{name}.phasing_keeping.delta_v", pk_t_s, ("cumulative_delta_v",),
                                       np.asarray(phase_controller.deltaVLog), units="m/s"))

            if handle.constant_thrust_controller is not None:
                ct_controller = handle.constant_thrust_controller
                ct_t_s = np.asarray(ct_controller.tLog)
                result.add(TimeSeries(f"{name}.constant_thrust.propellant_remaining", ct_t_s,
                                       ("propellant_remaining",), np.asarray(ct_controller.propellantLog),
                                       units="kg"))
                result.add(TimeSeries(f"{name}.constant_thrust.delta_v", ct_t_s, ("cumulative_delta_v",),
                                       np.asarray(ct_controller.deltaVLog), units="m/s"))

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

        # Phase 4: link-budget margin -- a reported estimate computed from
        # the access-analysis series just added above (see
        # engine.link_budget's module docstring for what this does and does
        # NOT account for), only for spacecraft that opted in via
        # schema.scenario.RFLinkConfig.
        for sc_config in self.scenario.spacecraft:
            if sc_config.rf_link is None:
                continue
            for gs_config in self.scenario.ground_stations:
                result.add(link_budget.link_margin_series(
                    result, gs_config.name, sc_config.name, sc_config.rf_link, gs_config
                ))
        return result
