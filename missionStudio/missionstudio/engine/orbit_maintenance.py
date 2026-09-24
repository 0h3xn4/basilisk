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
Automated orbit maintenance: independent altitude/semi-major-axis
station-keeping (``schema.scenario.StationKeepingConfig``) and
constellation-wide phasing maintenance
(``schema.scenario.PhasingKeepingConfig``), both with delta-V and
propellant bookkeeping.

:class:`StationKeepingController` is ported from
``../missionAnalysis/constellation_controllers.py``'s
``AltitudeKeepingController`` -- the burn logic (orbit-period-smoothed
altitude, deadband/hysteresis, eclipse gating) and the propellant/delta-V
bookkeeping math (explicit-Euler rocket equation, thrust-to-mass fed back
into ``scObject.hub.mHub`` every tick so achieved acceleration stays
physically consistent as propellant depletes) are unchanged. Two things
differ from the original:

* No separate fast-dynamics/coarse-control task split. ``missionAnalysis``
  needed that to keep a 5-year multi-satellite run tractable; missionStudio
  scenarios are much shorter and single-spacecraft-scale, so this runs on
  the same dynamics task as everything else, at
  ``schema.scenario.SimSettings.dynamics_task_rate_s`` -- see
  :func:`build_station_keeping`.
* ``orbit_period_s`` is not a caller-supplied argument -- computed here
  from ``mu``/``nominal_alt_m``/``r_planet_m`` via Kepler's third law
  instead (one fewer thing ``engine.service`` needs to compute).
* No ``log_decimation`` -- missionStudio scenarios are short enough that
  logging every tick (matching how every other recorder in
  ``engine.service`` already behaves) doesn't need thinning.
* Publishes ``fuelTankOutMsg`` (a real ``FuelTankMsgPayload``, not part of
  the original ``AltitudeKeepingController``) purely so ``engine.vizard``
  can drive a live "propellant remaining" bar in Vizard off of it (see
  that module) -- this controller still does NOT use a Basilisk
  ``fuelTank`` state effector for the actual physics, only for this one
  output message.

Uses a dedicated ``extForceTorque`` effector for the reboost force
(``extForce_N``, inertial-frame), independent of whatever effector
``engine.fsw.build_idealized_actuation`` may also be using for attitude
-control torque on the same spacecraft (``extTorquePntB_B``) -- multiple
dynamic effectors on one hub sum additively, the same pattern
``../missionAnalysis`` itself uses for drag/SRP/thrust as three separate
effectors.

Shared mass bookkeeping (audit fix)
------------------------------------
:class:`StationKeepingController`, :class:`PhasingKeepingController`, and
:class:`ConstantFrameThrustController` each track propellant use and feed
it back into ``scObject.hub.mHub`` so thrust-to-mass stays physically
consistent as propellant depletes. An earlier version of all three
UpdateState methods did this by unconditionally OVERWRITING
``hub.mHub = self.dryMass + self.propellant`` (an absolute value, each
controller's own construction-time-captured belief) every tick -- a real
bug, found by audit and fixed here: with more than one such controller on
the same spacecraft (``station_keeping`` + ``constant_thrust`` is an
explicitly supported combination -- see ``ConstantThrustConfig``'s
docstring), whichever one's ``UpdateState`` happened to run last each
tick silently discarded the other's propellant contribution to the
simulated mass; the same overwrite also silently undid any
``engine.monte_carlo`` ``dry_mass_kg`` dispersion (applied to ``hub.mHub``
once, before ``InitializeSimulation()`` -- see that module's docstring)
the moment the first tick ran.

Fixed by having each controller read the spacecraft's CURRENT
``hub.mHub`` at the top of its own ``UpdateState`` (rather than
recomputing an absolute value from its own captured ``dryMass``) and then
subtract only the propellant mass it ITSELF burns that tick. This
composes correctly no matter how many other controllers or an external
dispersion are also adjusting the same ``hub.mHub`` -- each one's edit is
a self-contained delta, order-independent by construction, rather than a
snapshot that can stomp on someone else's. It also makes each
controller's OWN delta-V bookkeeping marginally more physically accurate
as a side effect: ``currentMass`` is now the spacecraft's real total mass
(dry + every tank currently aboard), not just this one controller's own
belief about it.

Verification status: same as ``engine/fsw.py``/``engine/service.py`` --
cannot be executed in this project's development sandbox (no Basilisk
build here); the burn/bookkeeping logic is copied from
``../missionAnalysis``'s already-reviewed controller, not written from
memory (the shared-mass-bookkeeping fix above is this project's own,
found and fixed after a full codebase audit).
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from Basilisk.architecture import messaging, sysModel
from Basilisk.simulation import extForceTorque
from Basilisk.utilities import macros, orbitalMotion

from ..schema.scenario import ConstantThrustConfig, PhasingKeepingConfig, StationKeepingConfig
from .constellation import SeparationSchedule
from .propellant_bookkeeping import apply_propellant_burn


def _wrap_pm_pi(angle_rad: float) -> float:
    """Wrap an angle [rad] to (-pi, pi]."""
    return (angle_rad + np.pi) % (2.0 * np.pi) - np.pi


class StationKeepingController(sysModel.SysModel):
    """Independent altitude/SMA station-keeping for one spacecraft -- see
    this module's docstring and ``schema.scenario.StationKeepingConfig``'s
    docstring for the control law and bookkeeping. Construct via
    :func:`build_station_keeping` rather than directly; that function
    wires ``scStateInMsg``/``eclipseInMsg``/``extForceEffector``/
    ``scObject``, which this class needs set before ``UpdateState`` runs.
    """

    def __init__(
        self,
        name: str,
        mu: float,
        nominal_alt_m: float,
        deadband_m: float,
        r_planet_m: float,
        thrust_n: float,
        isp_s: float,
        dry_mass_kg: float,
        propellant_kg: float,
        eclipse_sunlit_threshold: float = 0.99,
        g0_mps2: float = 9.80665,
    ):
        super().__init__()
        self.ModelTag = name

        self.scStateInMsg = messaging.SCStatesMsgReader()
        self.eclipseInMsg = messaging.EclipseMsgReader()
        # Live propellant telemetry, for Vizard's GenericStorage "fuel tank"
        # panel (see engine.vizard) -- this controller tracks propellant as
        # a plain Python scalar (see module docstring for why: no
        # fuelTank state effector), so there is no Basilisk message
        # carrying it unless this module publishes one itself.
        self.fuelTankOutMsg = messaging.FuelTankMsg()

        # Wired up externally (see build_station_keeping): the
        # extForceTorque effector this controller commands, and the
        # spacecraft hub whose mass it updates as propellant depletes.
        self.extForceEffector = None
        self.scObject = None

        self.mu = mu  # [m^3/s^2]
        self.nominalAlt = nominal_alt_m  # [m]
        self.deadband = deadband_m  # [m]
        self.rPlanet = r_planet_m  # [m]
        self.thrustN = thrust_n  # [N]
        self.ispS = isp_s  # [s]
        self.g0 = g0_mps2  # [m/s^2]
        self.dryMass = dry_mass_kg  # [kg]
        self.propellant = propellant_kg  # [kg]
        self._initialPropellantKg = propellant_kg  # [kg] fixed tank capacity, for fuelTankOutMsg.maxFuelMass
        semi_major_axis_m = r_planet_m + nominal_alt_m  # [m]
        self.smoothingWindowS = float(2.0 * np.pi * np.sqrt(semi_major_axis_m ** 3 / mu))  # [s] orbit period
        self.sunlitThreshold = eclipse_sunlit_threshold  # [-]

        self.burnOn = False
        self._lastT: Optional[float] = None  # [s]
        self._altHistory: list = []  # list of (t [s], alt [m]) for the smoothing window

        # Python-side telemetry (cheap; avoids extra BSK messages/recorders
        # for what is ultimately just a handful of scalars per tick).
        self.tLog: list = []
        self.altLog: list = []
        self.smoothAltLog: list = []
        self.burnLog: list = []
        self.propellantLog: list = []
        self.deltaVLog: list = []
        self._cumulativeDv = 0.0  # [m/s]

    def Reset(self, CurrentSimNanos):
        self.burnOn = False
        self._lastT = CurrentSimNanos * macros.NANO2SEC
        self._altHistory = []
        if self.extForceEffector is not None:
            self.extForceEffector.extForce_N = [0.0, 0.0, 0.0]

    def UpdateState(self, CurrentSimNanos):
        t = CurrentSimNanos * macros.NANO2SEC  # [s]
        dt = t - self._lastT if self._lastT is not None else 0.0  # [s]
        self._lastT = t

        scState = self.scStateInMsg()
        rVec = np.array(scState.r_BN_N)  # [m]
        vVec = np.array(scState.v_BN_N)  # [m/s]

        # Same reasoning as PhasingKeepingController.UpdateState()'s own
        # matching guard: a non-finite (or, for vVec, exactly zero --
        # np.linalg.norm(vVec) below would divide by it) state must never
        # be allowed to propagate into a commanded force -- command no
        # thrust and hold state this tick instead.
        if not (np.all(np.isfinite(rVec)) and np.all(np.isfinite(vVec)) and np.linalg.norm(vVec) > 0.0):
            if self.extForceEffector is not None:
                self.extForceEffector.extForce_N = [0.0, 0.0, 0.0]
            self.tLog.append(t)
            self.altLog.append(float("nan"))
            self.smoothAltLog.append(float("nan"))
            self.burnLog.append(0)
            self.propellantLog.append(self.propellant)
            self.deltaVLog.append(self._cumulativeDv)
            return

        alt = float(np.linalg.norm(rVec) - self.rPlanet)  # [m]

        # Orbit-period boxcar smoothing to reject short-period altitude
        # oscillation and only respond to secular (e.g. drag-driven) decay.
        self._altHistory.append((t, alt))
        while self._altHistory and (t - self._altHistory[0][0]) > self.smoothingWindowS:
            self._altHistory.pop(0)
        smoothAlt = float(np.mean([a for _, a in self._altHistory]))

        if not self.burnOn and smoothAlt < (self.nominalAlt - self.deadband):
            self.burnOn = True
        elif self.burnOn and smoothAlt >= self.nominalAlt:
            self.burnOn = False

        inSun = True
        if self.eclipseInMsg.isLinked():
            inSun = self.eclipseInMsg().shadowFactor > self.sunlitThreshold

        thrustMag = self.thrustN if (self.burnOn and inSun) else 0.0  # [N]
        if thrustMag > 0.0 and self.propellant <= 1e-9:
            thrustMag = 0.0
            self.bskLogger.warning(f"{self.ModelTag}: propellant depleted, reboost inhibited")

        # Read the spacecraft's CURRENT total mass rather than
        # recomputing dryMass + this controller's own propellant -- see
        # this module's "Shared mass bookkeeping" docstring note for why.
        currentMass = self.scObject.hub.mHub if self.scObject is not None else (self.dryMass + self.propellant)
        if thrustMag > 0.0:
            self._cumulativeDv += (thrustMag / currentMass) * dt  # [m/s]

        newMass, self.propellant, _burnedKg, mDot = apply_propellant_burn(
            currentMass, self.propellant, thrustMag, self.ispS, dt, self.g0)
        if self.scObject is not None:
            self.scObject.hub.mHub = newMass

        forceVec = np.zeros(3)
        if thrustMag > 0.0:
            vHat = vVec / np.linalg.norm(vVec)
            forceVec = thrustMag * vHat
        if self.extForceEffector is not None:
            self.extForceEffector.extForce_N = forceVec.tolist()

        fuelTankMsg = messaging.FuelTankMsgPayload()
        fuelTankMsg.fuelMass = self.propellant  # [kg]
        fuelTankMsg.fuelMassDot = -mDot  # [kg/s] negative: mass decreasing
        fuelTankMsg.maxFuelMass = self._initialPropellantKg  # [kg]
        self.fuelTankOutMsg.write(fuelTankMsg, CurrentSimNanos, self.moduleID)

        self.tLog.append(t)
        self.altLog.append(alt)
        self.smoothAltLog.append(smoothAlt)
        self.burnLog.append(1 if thrustMag > 0.0 else 0)
        self.propellantLog.append(self.propellant)
        self.deltaVLog.append(self._cumulativeDv)


def build_station_keeping(scSim, task_name: str, tag: str, sc_object, mu: float, r_planet_m: float,
                           dry_mass_kg: float, config: StationKeepingConfig,
                           eclipse_out_msg=None) -> StationKeepingController:
    """Builds and wires one spacecraft's :class:`StationKeepingController`:
    a dedicated ``extForceTorque`` effector for the reboost force, the
    controller itself subscribed to the spacecraft's own state (and, if
    given, an eclipse output message for sunlit gating -- see
    ``engine.service``'s shared eclipse-model wiring, the same one
    ``PowerConfig`` uses). Adds both to ``task_name``.

    ``dry_mass_kg`` is the spacecraft's mass WITHOUT station-keeping
    propellant (``SpacecraftConfig.dry_mass_kg`` -- the caller is
    responsible for having already set ``sc_object.hub.mHub`` to
    ``dry_mass_kg + config.propellant_kg`` before calling this, so the
    initial simulated mass matches what this controller believes it is
    depleting from).
    """
    controller = StationKeepingController(
        name=f"{tag}StationKeeping",
        mu=mu,
        nominal_alt_m=config.target_altitude_km * 1000.0,
        deadband_m=config.deadband_km * 1000.0,
        r_planet_m=r_planet_m,
        thrust_n=config.thrust_n,
        isp_s=config.isp_s,
        dry_mass_kg=dry_mass_kg,
        propellant_kg=config.propellant_kg,
        eclipse_sunlit_threshold=config.eclipse_sunlit_threshold,
    )

    thruster = extForceTorque.ExtForceTorque()
    thruster.ModelTag = f"{tag}StationKeepingThruster"
    sc_object.addDynamicEffector(thruster)
    scSim.AddModelToTask(task_name, thruster)

    controller.extForceEffector = thruster
    controller.scObject = sc_object
    controller.scStateInMsg.subscribeTo(sc_object.scStateOutMsg)
    if eclipse_out_msg is not None:
        controller.eclipseInMsg.subscribeTo(eclipse_out_msg)
    scSim.AddModelToTask(task_name, controller)
    return controller


class PhasingKeepingController(sysModel.SysModel):
    """In-plane phasing / constellation-keeping between two co-planar
    spacecraft -- see this module's docstring and
    ``schema.scenario.PhasingKeepingConfig``'s docstring for the control
    law and why this always shares a thruster/tank with a co-located
    :class:`StationKeepingController`. Construct via
    :func:`build_phasing_keeping` rather than directly.

    Ported from ``../missionAnalysis/constellation_controllers.py``'s
    controller of the same name -- the drift-orbit state machine
    (IDLE/BURN_OUT/DRIFT/BURN_RESTORE), the mean-anomaly error computation
    (osculating, smoothed over one orbital period to reject J2
    short-period noise), and the thruster-arbitration/shared-propellant
    logic are unchanged. Differs the same two ways
    :class:`StationKeepingController` differs from its own original (no
    fast-dyn/coarse-ctrl task split, no ``log_decimation``), plus:
    ``thrust_n``/``isp_s``/``dry_mass_kg`` are not schema fields here --
    :func:`build_phasing_keeping` always reads them off the co-located
    ``StationKeepingController`` (see ``PhasingKeepingConfig``'s
    docstring for why: one physical thruster/tank, so there is no
    schema-level way for the two to disagree about it).
    """

    IDLE, BURN_OUT, DRIFT, BURN_RESTORE = range(4)

    def __init__(
        self,
        name: str,
        mu: float,
        nominal_a_m: float,
        separation_schedule: SeparationSchedule,
        tolerance_fraction: float,
        restore_tolerance_fraction: float,
        correction_window_days: float,
        max_drift_days: float,
        max_delta_a_m: float,
        thrust_n: float,
        isp_s: float,
        dry_mass_kg: float,
        eclipse_sunlit_threshold: float = 0.99,
        g0_mps2: float = 9.80665,
    ):
        super().__init__()
        self.ModelTag = name

        self.scStateInMsgA = messaging.SCStatesMsgReader()  # chief
        self.scStateInMsgB = messaging.SCStatesMsgReader()  # follower (maneuvered)
        self.eclipseInMsgB = messaging.EclipseMsgReader()

        # Wired up externally (see build_phasing_keeping): the follower's
        # extForceTorque effector and hub, and the co-located
        # StationKeepingController this shares a thruster/tank with (also
        # used for thruster-arbitration -- see UpdateState).
        self.extForceEffectorB = None
        self.scObjectB = None
        self.altitudeControllerB = None

        self.mu = mu  # [m^3/s^2]
        self.aNom = nominal_a_m  # [m]
        self.separationSchedule = separation_schedule
        self.toleranceFraction = tolerance_fraction  # [-] of the current target separation
        self.restoreToleranceFraction = restore_tolerance_fraction  # [-] of the active maneuver's target
        # Snapshot of the target this controller is actively maneuvering
        # toward, taken once at IDLE -> BURN_OUT and held fixed through
        # BURN_OUT/DRIFT/BURN_RESTORE even if the schedule ticks over to a
        # new target mid-maneuver.
        self._activeTargetRad = 0.0
        self.correctionWindowS = correction_window_days * 86400.0  # [s]
        self.maxDriftS = max_drift_days * 86400.0  # [s]
        self.maxDeltaA = max_delta_a_m  # [m]
        self.thrustN = thrust_n  # [N]
        self.ispS = isp_s  # [s]
        self.g0 = g0_mps2  # [m/s^2]
        self.dryMass = dry_mass_kg  # [kg]
        # Fallback propellant tracker, used only if altitudeControllerB is
        # never set -- see _propellant_tracker(). missionStudio always
        # sets it (PhasingKeepingConfig requires station_keeping), so this
        # is defensive, not the normal path.
        self.propellant = 0.0  # [kg]
        self.sunlitThreshold = eclipse_sunlit_threshold  # [-]

        semi_major_axis_m = nominal_a_m  # already the chief/follower shared SMA
        self.smoothingWindowS = float(2.0 * np.pi * np.sqrt(semi_major_axis_m ** 3 / mu))  # [s] orbit period
        self._errorHistory: list = []  # list of (t [s], rawError [rad])

        self.state = self.IDLE
        self._lastT: Optional[float] = None  # [s]
        self._targetDv = 0.0  # [m/s]
        self._accumDv = 0.0  # [m/s]
        self._burnSign = 1.0  # [-] +1 prograde (raise a), -1 retrograde (lower a)
        self._driftStartT = 0.0  # [s]

        self.tLog: list = []
        self.errorDegLog: list = []
        self.stateLog: list = []
        self.propellantLog: list = []
        self.deltaVLog: list = []
        self._cumulativeDv = 0.0  # [m/s]

    def Reset(self, CurrentSimNanos):
        self.state = self.IDLE
        self._lastT = CurrentSimNanos * macros.NANO2SEC
        self._accumDv = 0.0
        # Mirrors StationKeepingController.Reset()'s own self._altHistory
        # clear -- this smoothing window is per-tick algorithmic state, not
        # cumulative telemetry (unlike tLog/errorDegLog/... below, which
        # intentionally keep accumulating across a Reset() the same way
        # every other controller's logs do), so a second Reset() on this
        # same instance (Basilisk permits calling it more than once, even
        # though every current caller in this codebase only ever does so
        # once) must not let stale pre-reset error samples leak into the
        # smoothed error average computed just after it.
        self._errorHistory = []
        if self.extForceEffectorB is not None:
            self.extForceEffectorB.extForce_N = [0.0, 0.0, 0.0]

    @staticmethod
    def _mean_anomaly(mu, rVec, vVec):
        oe = orbitalMotion.rv2elem(mu, rVec, vVec)
        eccAnom = orbitalMotion.f2E(oe.f, oe.e)
        meanAnom = orbitalMotion.E2M(eccAnom, oe.e)
        return oe.a, meanAnom

    @staticmethod
    def _circular_mean(angles_rad):
        # Mean of a circular (wrapped) quantity via the resultant vector,
        # correct near the +/-pi wrap boundary -- a plain arithmetic mean
        # is not (e.g. averaging +179 deg and -179 deg should give +/-180
        # deg, not 0).
        return float(np.arctan2(np.mean(np.sin(angles_rad)), np.mean(np.cos(angles_rad))))

    def UpdateState(self, CurrentSimNanos):
        t = CurrentSimNanos * macros.NANO2SEC  # [s]
        dt = t - self._lastT if self._lastT is not None else 0.0  # [s]
        self._lastT = t

        stateA = self.scStateInMsgA()
        stateB = self.scStateInMsgB()
        rA, vA = np.array(stateA.r_BN_N), np.array(stateA.v_BN_N)
        rB, vB = np.array(stateB.r_BN_N), np.array(stateB.v_BN_N)

        # Real crash found on an actual run: orbitalMotion.rv2elem() (called
        # via _mean_anomaly below) has a genuine bug in ITS OWN NaN-input
        # guard (src/utilities/orbitalMotion.py sets ClassicElements.AN/.AP,
        # neither of which is a real slot on that class -- see
        # engine.service._osculating_elements's matching comment) -- it
        # crashes with AttributeError instead of returning a clean NaN
        # result.
        #
        # An EARLIER version of this comment claimed that AttributeError
        # would escape UpdateState() (a SWIG director callback) as
        # undefined behavior -- wrong, corrected after actually reading
        # Basilisk's own C++ source (architecture/system_model/sim_model.cpp):
        # SimThreadExecution's worker loop wraps every tick in `catch (...)`
        # and cleanly re-throws on the parent thread, so a Python exception
        # raised from here becomes an ordinary, catchable Python
        # RuntimeError, not UB. The two different native-looking crash
        # signatures this scenario produced (basic_string::_M_create,
        # std::bad_alloc) have a different, now-confirmed cause instead:
        # once ANY dynamics state goes non-finite (from whatever source),
        # Basilisk's adaptive integrator (rkf45/rkf78 -- see
        # simulation/dynamics/_GeneralModuleFiles/svIntegratorAdaptiveRungeKutta.h)
        # computes a NaN error estimate, and every comparison against NaN
        # is false -- so its "is this step good enough" check never
        # succeeds and its integration loop never exits, reallocating
        # temporaries every iteration until the heap is exhausted. See
        # engine.service.raise_clear_execution_error's own docstring for
        # the full mechanism and where that's now caught and turned into a
        # clear error instead of a bare native exception string.
        #
        # Guarding this call site never hurts (a non-finite state was
        # never safe input regardless of what happens after), but it is
        # NOT sufficient by itself to prevent the crash above -- the state
        # can go non-finite entirely inside Basilisk's own EOM/integrator,
        # between one tick's finite read here and the next, with no
        # Python-level hook in between to catch it. Command no thrust and
        # hold state this tick instead (the non-finite state read here is
        # either before either spacecraft's dynamics has published a first
        # real sample yet, or the simulation has already gone non-physical
        # -- either way, nothing useful can be computed from it).
        if not (np.all(np.isfinite(rA)) and np.all(np.isfinite(vA))
                and np.all(np.isfinite(rB)) and np.all(np.isfinite(vB))):
            if self.extForceEffectorB is not None:
                self.extForceEffectorB.extForce_N = [0.0, 0.0, 0.0]
            self.tLog.append(t)
            self.errorDegLog.append(float("nan"))
            self.stateLog.append(self.state)
            self.propellantLog.append(self._propellant_tracker().propellant)
            self.deltaVLog.append(self._cumulativeDv)
            return

        _, mA = self._mean_anomaly(self.mu, rA, vA)
        _, mB = self._mean_anomaly(self.mu, rB, vB)

        scheduledTargetRad = self.separationSchedule.value_at(t)
        referenceTargetRad = scheduledTargetRad if self.state == self.IDLE else self._activeTargetRad

        # error > 0 means B's phase leads the target separation (B is "too
        # far ahead" of A); error < 0 means B trails. Smoothed over one
        # orbital period to reject J2 short-period osculating-element noise.
        rawError = _wrap_pm_pi((mB - mA) - referenceTargetRad)  # [rad]
        self._errorHistory.append((t, rawError))
        while self._errorHistory and (t - self._errorHistory[0][0]) > self.smoothingWindowS:
            self._errorHistory.pop(0)
        error = self._circular_mean(np.array([e for _, e in self._errorHistory]))  # [rad]

        inSun = True
        if self.eclipseInMsgB.isLinked():
            inSun = self.eclipseInMsgB().shadowFactor > self.sunlitThreshold

        # Thruster arbitration: altitude keeping owns the effector whenever
        # it is actively burning. Log telemetry and return without
        # touching the effector or advancing the state machine's clocks.
        thrusterHeldByAltCtrl = self.altitudeControllerB is not None and self.altitudeControllerB.burnOn
        if thrusterHeldByAltCtrl:
            self.tLog.append(t)
            self.errorDegLog.append(np.degrees(error))
            self.stateLog.append(self.state)
            self.propellantLog.append(self._propellant_tracker().propellant)
            self.deltaVLog.append(self._cumulativeDv)
            return

        thrustMag = 0.0  # [N]

        if self.state == self.IDLE:
            # Tolerance scales with the CURRENT target, not a fixed angle.
            tolRad = self.toleranceFraction * abs(scheduledTargetRad)
            if abs(error) > tolRad:
                self._activeTargetRad = scheduledTargetRad
                n = np.sqrt(self.mu / self.aNom ** 3)  # [rad/s] mean motion
                # Two-body mean-motion offset from an SMA offset:
                #   dn = -1.5 * n * (deltaA / a)
                # Solve deltaA so the accumulated drift over the correction
                # window exactly cancels the current error:
                #   error + dn * T = 0  =>  deltaA = error * a / (1.5 * n * T)
                deltaA = error * self.aNom / (1.5 * n * self.correctionWindowS)  # [m]
                deltaA = float(np.clip(deltaA, -self.maxDeltaA, self.maxDeltaA))
                vCirc = np.sqrt(self.mu / self.aNom)  # [m/s]
                # Linearized tangential-burn SMA change: deltaA/a = 2*dv/vCirc
                dv = deltaA / self.aNom * vCirc / 2.0  # [m/s]
                self._targetDv = abs(dv)
                self._burnSign = 1.0 if dv >= 0.0 else -1.0
                self._accumDv = 0.0
                self.state = self.BURN_OUT

        elif self.state == self.BURN_OUT:
            thrustMag = self.thrustN if inSun else 0.0
            if self._accumDv >= self._targetDv:
                self._accumDv = 0.0
                self._driftStartT = t
                self.state = self.DRIFT
                thrustMag = 0.0

        elif self.state == self.DRIFT:
            restoreTolRad = self.restoreToleranceFraction * abs(self._activeTargetRad)
            overshot = np.sign(error) != self._burnSign if error != 0.0 else False
            if abs(error) < restoreTolRad or overshot or (t - self._driftStartT) > self.maxDriftS:
                self.state = self.BURN_RESTORE

        elif self.state == self.BURN_RESTORE:
            thrustMag = self.thrustN if inSun else 0.0
            if self._accumDv >= self._targetDv:
                self.state = self.IDLE
                thrustMag = 0.0

        tracker = self._propellant_tracker()
        # Read the spacecraft's CURRENT total mass rather than
        # recomputing dryMass + tracker.propellant -- see this module's
        # "Shared mass bookkeeping" docstring note for why.
        currentMass = self.scObjectB.hub.mHub if self.scObjectB is not None else (self.dryMass + tracker.propellant)

        if thrustMag > 0.0:
            accel = thrustMag / currentMass  # [m/s^2]
            self._accumDv += accel * dt
            self._cumulativeDv += accel * dt

        newMass, tracker.propellant, _burnedKg, _mDot = apply_propellant_burn(
            currentMass, tracker.propellant, thrustMag, self.ispS, dt, self.g0)
        if self.scObjectB is not None:
            self.scObjectB.hub.mHub = newMass

        forceVec = np.zeros(3)
        if thrustMag > 0.0:
            vHatB = vB / np.linalg.norm(vB)
            sign = self._burnSign if self.state == self.BURN_OUT else -self._burnSign
            forceVec = thrustMag * sign * vHatB
        if self.extForceEffectorB is not None:
            self.extForceEffectorB.extForce_N = forceVec.tolist()

        self.tLog.append(t)
        self.errorDegLog.append(np.degrees(error))
        self.stateLog.append(self.state)
        self.propellantLog.append(tracker.propellant)
        self.deltaVLog.append(self._cumulativeDv)

    def _propellant_tracker(self):
        # Satellite B's thruster (and hence its one physical propellant
        # tank) is shared with its own StationKeepingController (see the
        # thruster-arbitration check above); track mass through that same
        # object rather than keeping an independent second belief about
        # how much propellant is left. Falls back to this controller's own
        # (never independently depleted) tracker only if none was wired up.
        return self.altitudeControllerB if self.altitudeControllerB is not None else self


def build_phasing_keeping(scSim, task_name: str, tag: str, mu: float, chief_sc_object, follower_sc_object,
                           follower_station_keeping_controller: StationKeepingController,
                           follower_eclipse_out_msg, chief_semi_major_axis_km: float,
                           config: PhasingKeepingConfig) -> PhasingKeepingController:
    """Builds and wires one follower spacecraft's :class:`PhasingKeepingController`.

    Shares ``follower_station_keeping_controller``'s ``extForceEffector``
    (no second effector is created -- see ``PhasingKeepingConfig``'s
    docstring on why phasing and altitude-keeping share one physical
    thruster) and reads ``thrust_n``/``isp_s``/``dry_mass_kg``/
    ``eclipse_sunlit_threshold`` off it rather than off ``config``, which
    has no such fields of its own.
    """
    nominal_a_m = chief_semi_major_axis_km * 1000.0
    schedule = SeparationSchedule(
        distances_km=config.target_separation_km,
        interval_days=config.reconfiguration_interval_days,
        semi_major_axis_m=nominal_a_m,
    )
    controller = PhasingKeepingController(
        name=f"{tag}PhasingKeeping",
        mu=mu,
        nominal_a_m=nominal_a_m,
        separation_schedule=schedule,
        tolerance_fraction=config.tolerance_fraction,
        restore_tolerance_fraction=config.restore_tolerance_fraction,
        correction_window_days=config.correction_window_days,
        max_drift_days=config.max_drift_days,
        max_delta_a_m=config.max_delta_semi_major_axis_km * 1000.0,
        thrust_n=follower_station_keeping_controller.thrustN,
        isp_s=follower_station_keeping_controller.ispS,
        dry_mass_kg=follower_station_keeping_controller.dryMass,
        eclipse_sunlit_threshold=follower_station_keeping_controller.sunlitThreshold,
    )

    controller.scStateInMsgA.subscribeTo(chief_sc_object.scStateOutMsg)
    controller.scStateInMsgB.subscribeTo(follower_sc_object.scStateOutMsg)
    if follower_eclipse_out_msg is not None:
        controller.eclipseInMsgB.subscribeTo(follower_eclipse_out_msg)
    controller.extForceEffectorB = follower_station_keeping_controller.extForceEffector
    controller.scObjectB = follower_sc_object
    # Thruster-arbitration link: phasing pauses while the follower's own
    # altitude controller is actively reboosting (see UpdateState).
    controller.altitudeControllerB = follower_station_keeping_controller
    scSim.AddModelToTask(task_name, controller)
    return controller


def _vnb_basis(r_vec: np.ndarray, v_vec: np.ndarray):
    """(V, N, B) unit vectors of the velocity-normal-binormal frame at this
    instant: V = velocity direction, N = orbit-normal (angular-momentum
    direction, r x v), B = V x N (completes the right-handed triad).
    Re-evaluated fresh from the spacecraft's CURRENT r/v every call -- this
    is an osculating, instantaneously-rotating frame, not a fixed one.
    """
    v_hat = v_vec / np.linalg.norm(v_vec)
    h_vec = np.cross(r_vec, v_vec)
    n_hat = h_vec / np.linalg.norm(h_vec)
    b_hat = np.cross(v_hat, n_hat)
    return v_hat, n_hat, b_hat


def _rtn_basis(r_vec: np.ndarray, v_vec: np.ndarray):
    """(R, T, N) unit vectors of the radial-transverse-normal frame at this
    instant: R = radial (outward from the central body), N = orbit-normal
    (angular-momentum direction, r x v), T = N x R (completes the
    right-handed triad; in-plane, perpendicular to R -- coincides with the
    velocity direction only at periapsis/apoapsis or for a circular orbit,
    NOT in general, unlike VNB's V). Re-evaluated fresh every call, like
    :func:`_vnb_basis`.
    """
    r_hat = r_vec / np.linalg.norm(r_vec)
    h_vec = np.cross(r_vec, v_vec)
    n_hat = h_vec / np.linalg.norm(h_vec)
    t_hat = np.cross(n_hat, r_hat)
    return r_hat, t_hat, n_hat


class ConstantFrameThrustController(sysModel.SysModel):
    """Continuous (always-on), constant-magnitude thrust with a fixed
    DIRECTION IN A ROTATING FRAME (VNB or RTN -- see
    :class:`schema.scenario.ConstantThrustConfig`'s docstring for why: an
    orbit-only "cannonball" scenario needs a delta-V/propellant budgeting
    tool that doesn't require any attitude modeling, and a thrust
    direction fixed in the INERTIAL frame would drift relative to the
    orbit as the spacecraft moves -- VNB/RTN are the standard
    astrodynamics frames for exactly this, re-evaluated every tick from
    the spacecraft's current state, see :func:`_vnb_basis`/:func:`_rtn_basis`).

    Propellant/delta-V bookkeeping (explicit-Euler rocket equation, mass
    fed back into ``scObject.hub.mHub``) is the same approach
    :class:`StationKeepingController` uses, just with no
    altitude-deadband/eclipse trigger -- this fires every tick until
    propellant is exhausted (then silently stays at zero thrust, same as
    station-keeping's own depletion behavior, just without the repeated
    per-tick warning log -- running out is the expected steady state for
    a continuous-thrust budget scenario, not a surprise).

    Construct via :func:`build_constant_thrust` rather than directly.
    """

    def __init__(self, name: str, frame: str, direction, thrust_n: float, isp_s: float,
                 dry_mass_kg: float, propellant_kg: float, g0_mps2: float = 9.80665):
        super().__init__()
        self.ModelTag = name

        self.scStateInMsg = messaging.SCStatesMsgReader()
        # Live propellant telemetry for Vizard's GenericStorage "fuel tank"
        # panel -- same rationale as StationKeepingController's own
        # fuelTankOutMsg (see that class's docstring).
        self.fuelTankOutMsg = messaging.FuelTankMsg()

        # Wired up externally (see build_constant_thrust): the
        # extForceTorque effector this controller commands, and the
        # spacecraft hub whose mass it updates as propellant depletes.
        self.extForceEffector = None
        self.scObject = None

        self.frame = frame  # "VNB" or "RTN" -- trusted pre-validated (ConstantThrustConfig.validate())
        direction_arr = np.array(direction, dtype=float)
        norm = np.linalg.norm(direction_arr)
        self.direction = direction_arr / norm if norm > 0.0 else direction_arr  # unit vector in `frame`
        self.thrustN = thrust_n  # [N]
        self.ispS = isp_s  # [s]
        self.g0 = g0_mps2  # [m/s^2]
        self.dryMass = dry_mass_kg  # [kg]
        self.propellant = propellant_kg  # [kg]
        self._initialPropellantKg = propellant_kg  # [kg] fixed tank capacity, for fuelTankOutMsg.maxFuelMass

        self._lastT: Optional[float] = None  # [s]
        self.tLog: list = []
        self.propellantLog: list = []
        self.deltaVLog: list = []
        self._cumulativeDv = 0.0  # [m/s]

    def Reset(self, CurrentSimNanos):
        self._lastT = CurrentSimNanos * macros.NANO2SEC
        if self.extForceEffector is not None:
            self.extForceEffector.extForce_N = [0.0, 0.0, 0.0]

    def UpdateState(self, CurrentSimNanos):
        t = CurrentSimNanos * macros.NANO2SEC  # [s]
        dt = t - self._lastT if self._lastT is not None else 0.0  # [s]
        self._lastT = t

        scState = self.scStateInMsg()
        rVec = np.array(scState.r_BN_N)  # [m]
        vVec = np.array(scState.v_BN_N)  # [m/s]

        axis1, axis2, axis3 = _vnb_basis(rVec, vVec) if self.frame == "VNB" else _rtn_basis(rVec, vVec)
        dirHat_N = self.direction[0] * axis1 + self.direction[1] * axis2 + self.direction[2] * axis3

        thrustMag = self.thrustN if self.propellant > 1e-9 else 0.0  # [N]
        # Read the spacecraft's CURRENT total mass rather than
        # recomputing dryMass + this controller's own propellant -- see
        # this module's "Shared mass bookkeeping" docstring note for why.
        currentMass = self.scObject.hub.mHub if self.scObject is not None else (self.dryMass + self.propellant)

        if thrustMag > 0.0:
            self._cumulativeDv += (thrustMag / currentMass) * dt  # [m/s]

        newMass, self.propellant, _burnedKg, mDot = apply_propellant_burn(
            currentMass, self.propellant, thrustMag, self.ispS, dt, self.g0)
        if self.scObject is not None:
            self.scObject.hub.mHub = newMass

        forceVec = thrustMag * dirHat_N
        if self.extForceEffector is not None:
            self.extForceEffector.extForce_N = forceVec.tolist()

        fuelTankMsg = messaging.FuelTankMsgPayload()
        fuelTankMsg.fuelMass = self.propellant  # [kg]
        fuelTankMsg.fuelMassDot = -mDot  # [kg/s] negative: mass decreasing
        fuelTankMsg.maxFuelMass = self._initialPropellantKg  # [kg]
        self.fuelTankOutMsg.write(fuelTankMsg, CurrentSimNanos, self.moduleID)

        self.tLog.append(t)
        self.propellantLog.append(self.propellant)
        self.deltaVLog.append(self._cumulativeDv)


def build_constant_thrust(scSim, task_name: str, tag: str, sc_object, dry_mass_kg: float,
                           config: ConstantThrustConfig) -> ConstantFrameThrustController:
    """Builds and wires one spacecraft's :class:`ConstantFrameThrustController`:
    a DEDICATED ``extForceTorque`` effector -- independent of
    station-keeping's own effector, if also configured on this spacecraft
    (multiple dynamic effectors on one hub sum additively, same pattern
    this module's docstring already notes for attitude-control/
    station-keeping). Adds both to ``task_name``.

    ``dry_mass_kg`` is the spacecraft's mass WITHOUT this controller's own
    propellant, same convention as :func:`build_station_keeping`'s
    ``dry_mass_kg`` argument -- see that function's docstring. If BOTH
    station_keeping and constant_thrust are configured on the same
    spacecraft, the caller is responsible for including both propellant
    masses in the spacecraft's initial simulated mass (they are
    independent propellant budgets/tanks, unlike station_keeping +
    phasing_keeping which deliberately share one) -- see this module's
    "Shared mass bookkeeping" docstring note for how each controller's
    ``UpdateState`` now preserves that initial total correctly tick over
    tick, instead of each one recomputing (and clobbering) its own.
    """
    controller = ConstantFrameThrustController(
        name=f"{tag}ConstantThrust",
        frame=config.frame,
        direction=config.direction,
        thrust_n=config.thrust_n,
        isp_s=config.isp_s,
        dry_mass_kg=dry_mass_kg,
        propellant_kg=config.propellant_kg,
    )

    thruster = extForceTorque.ExtForceTorque()
    thruster.ModelTag = f"{tag}ConstantThrustThruster"
    sc_object.addDynamicEffector(thruster)
    scSim.AddModelToTask(task_name, thruster)

    controller.extForceEffector = thruster
    controller.scObject = sc_object
    controller.scStateInMsg.subscribeTo(sc_object.scStateOutMsg)
    scSim.AddModelToTask(task_name, controller)
    return controller
