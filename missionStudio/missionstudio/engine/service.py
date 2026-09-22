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
drag, SRP, sensors, actuators, FSW modes, ground stations, space weather,
Monte Carlo. The Phase 1 GUI (see ``gui/``) deliberately does not expose
editors for any of these either, for the same reason: a control that
looks like it configures simulated behavior but silently doesn't is worse
than not offering it yet.

Verification status
--------------------
Requires a Basilisk build -- cannot be executed in this development
sandbox (no Basilisk build here; a from-source build was attempted and
failed because this sandbox's network policy blocks Conan Center -- see
``missionStudio/README.md``). Written directly against the same verified
API calls already exercised (and long since run against a real Basilisk
build) in ``../missionAnalysis/run_constellation_mission.py`` earlier in
this project -- see that file for the calling conventions this mirrors
(``gravBodyFactory``, ``spacecraft.Spacecraft``, ``svIntegrators``,
``orbitalMotion``). The one call sequence in this file that is NOT
mirrored from already-verified code is the integrator class lookup (see
``_INTEGRATORS`` below) -- those class names were confirmed by directly
listing ``src/simulation/dynamics/Integrators/`` in this checkout, not by
example usage, since only ``svIntegratorRKF78`` happens to already appear
in ``../missionAnalysis``.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from Basilisk.simulation import spacecraft, svIntegrators
from Basilisk.utilities import SimulationBaseClass, macros, orbitalMotion, simHelpers, simIncludeGravBody
from Basilisk.utilities.supportDataTools.dataFetcher import DataFile, get_path

from ..schema.scenario import OrbitIC, Scenario
from . import kernels, time_system
from .results import ResultSet, TimeSeries

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


class SimulationService:
    """One instance per run -- create a fresh :class:`SimulationService`
    for each :class:`Scenario` you execute rather than reusing one across
    structurally different scenarios (mirrors Basilisk's own
    ``SimBaseClass``, which is not designed to be reset and rebuilt).
    """

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.scSim: Optional[SimulationBaseClass.SimBaseClass] = None
        self.mu: Optional[float] = None
        self._handles: Dict[str, _SpacecraftHandle] = {}

    def build(self) -> None:
        """Assemble the Basilisk simulation from ``self.scenario`` without
        running it. Safe to call at most once per instance (see the class
        docstring); :meth:`run` calls this automatically if it hasn't been
        called yet.
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

            self._handles[sc_config.name] = _SpacecraftHandle(sc_config.name, sc_object, recorder)

        self.dyn_task_name = dyn_task_name
        self.scSim.InitializeSimulation()
        stop_time_s = sim_settings.duration_days * 86400.0
        self.scSim.ConfigureStopTime(macros.sec2nano(stop_time_s))

    def run(self) -> ResultSet:
        """Build (if not already built) and execute the simulation, then
        extract every spacecraft's position/velocity time history into a
        :class:`~missionstudio.engine.results.ResultSet`.
        """
        if self.scSim is None:
            self.build()

        self.scSim.ExecuteSimulation()

        result = ResultSet(scenario_name=self.scenario.name)
        for name, handle in self._handles.items():
            t_s = handle.recorder.times() * macros.NANO2SEC
            result.add(TimeSeries(f"{name}.position_N", t_s, ("x", "y", "z"), handle.recorder.r_BN_N, units="m"))
            result.add(TimeSeries(f"{name}.velocity_N", t_s, ("x", "y", "z"), handle.recorder.v_BN_N, units="m/s"))
        return result
