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
Pure-Python Basilisk ``SysModel`` controllers implementing the two automated
maintenance behaviors requested for this mission:

#. :class:`AltitudeKeepingController` -- independent altitude/SMA station
   -keeping per spacecraft (reboost via a finite low-thrust burn whenever
   altitude decays past a deadband).
#. :class:`PhasingKeepingController` -- in-plane phasing / constellation
   -keeping between two co-planar spacecraft at an arbitrary target
   separation (a drift-orbit maneuver: temporary SMA offset, drift, restore).

Both act on an :ref:`extForceTorque` dynamic effector by writing its
``extForce_N`` (inertial-frame force) directly, rather than by commanding a
body-frame thruster. This is a deliberate scope choice: this mission-analysis
study does not need attitude/GNC fidelity, so there is no attitude control
loop to point a real thruster with, and modeling the force directly in the
inertial frame (along the local velocity direction) keeps the orbital
dynamics fully physical while skipping 6-DOF entirely. See ``README.md`` for
the full architecture rationale.

Both controllers are meant to run on a *coarse* control task (order ~minutes),
decoupled from the *fine* dynamics task that actually integrates the orbits
(order ~seconds to a minute). See ``run_constellation_mission.py``.
"""

import numpy as np
from Basilisk.architecture import sysModel, messaging
from Basilisk.utilities import macros, orbitalMotion


def _wrap_pm_pi(angle_rad: float) -> float:
    """Wrap an angle [rad] to (-pi, pi]."""
    return (angle_rad + np.pi) % (2.0 * np.pi) - np.pi


class AltitudeKeepingController(sysModel.SysModel):
    """Independent altitude/SMA station-keeping for one spacecraft.

    Monitors an orbit-period-smoothed altitude estimate and fires a
    continuous prograde (tangential, along the inertial velocity direction)
    low-thrust reboost burn whenever it decays past ``deadband_m`` below
    ``nominal_alt_m``, holding the burn until the smoothed altitude is
    restored to nominal (simple deadband/hysteresis control -- no
    differential corrector is needed for this task). The burn is gated off
    whenever the spacecraft is eclipsed, approximating a solar-electric bus
    that cannot run the thruster off battery alone.

    Propellant is tracked as a simple bookkeeping mass budget (explicit-Euler
    integration of the rocket equation at the control cadence) and fed back
    into ``scObject.hub.mHub`` so thrust-to-mass and every other force-to
    -acceleration conversion stay consistent as propellant depletes. This is
    a deliberate simplification in place of Basilisk's ``fuelTank`` state
    effector, which is normally driven through a body-frame
    ``thrusterDynamicEffector`` and would reintroduce the attitude-geometry
    modeling this study is explicitly avoiding.
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
        orbit_period_s: float,
        eclipse_sunlit_threshold: float = 0.99,
        g0_mps2: float = 9.80665,
        log_decimation: int = 12,
    ):
        super().__init__()
        self.ModelTag = name

        # Message-based inputs (wired up externally via subscribeTo)
        self.scStateInMsg = messaging.SCStatesMsgReader()
        self.eclipseInMsg = messaging.EclipseMsgReader()

        # Direct object references (wired up externally, not via message):
        # the extForceTorque effector this controller commands, and the
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
        self.smoothingWindowS = orbit_period_s  # [s]
        self.sunlitThreshold = eclipse_sunlit_threshold  # [-]
        # Telemetry is recorded every Nth control tick: at the default 300 s
        # control cadence and decimation of 12, this logs hourly over the
        # full 5-year mission (~43800 points/satellite) instead of ~526000,
        # which keeps post-run plotting/memory usage reasonable without
        # affecting the control decisions themselves (those run every tick).
        self.logDecimation = max(1, int(log_decimation))
        self._tickCount = 0

        self.burnOn = False
        self._lastT = None  # [s]
        self._altHistory = []  # list of (t [s], alt [m]) for the smoothing window

        # Python-side telemetry (cheap; avoids extra BSK messages/recorders
        # for what is ultimately just a handful of scalars per control tick).
        self.tLog = []
        self.altLog = []
        self.smoothAltLog = []
        self.burnLog = []
        self.propellantLog = []
        self.deltaVLog = []
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
        alt = float(np.linalg.norm(rVec) - self.rPlanet)  # [m]

        # Orbit-period boxcar smoothing to reject J2 short-period altitude
        # oscillation and only respond to secular (drag-driven) decay.
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

        currentMass = self.dryMass + self.propellant  # [kg]

        if thrustMag > 0.0:
            self._cumulativeDv += (thrustMag / currentMass) * dt  # [m/s]
            mDot = thrustMag / (self.ispS * self.g0)  # [kg/s]
            self.propellant = max(0.0, self.propellant - mDot * dt)

        if self.scObject is not None:
            self.scObject.hub.mHub = self.dryMass + self.propellant

        forceVec = np.zeros(3)
        if thrustMag > 0.0:
            vHat = vVec / np.linalg.norm(vVec)
            forceVec = thrustMag * vHat
        if self.extForceEffector is not None:
            self.extForceEffector.extForce_N = forceVec.tolist()

        self._tickCount += 1
        if self._tickCount % self.logDecimation == 0:
            self.tLog.append(t)
            self.altLog.append(alt)
            self.smoothAltLog.append(smoothAlt)
            self.burnLog.append(1 if thrustMag > 0.0 else 0)
            self.propellantLog.append(self.propellant)
            self.deltaVLog.append(self._cumulativeDv)


class PhasingKeepingController(sysModel.SysModel):
    """In-plane phasing / constellation-keeping between two co-planar satellites.

    Holds the mean-anomaly separation between a reference satellite A and a
    maneuvering satellite B at ``target_separation_deg`` (to within
    ``tolerance_deg``) using a "drift-orbit" maneuver: a small, temporary
    tangential burn changes B's semimajor axis (and hence mean motion) just
    enough that, over ``correction_window_days`` of natural drift, the
    accumulated mean-anomaly difference removes the phase error; a second
    burn then restores B's nominal SMA.

    For an N-satellite plane evenly spaced in mean anomaly, instantiate one
    of these per follower (satellites 2..N), all referencing the same chief
    (satellite 1) with ``target_separation_deg = k * 360/N`` for the k-th
    follower -- see ``run_constellation_mission.py``, which builds one
    controller per (chief, follower) pair for every multi-satellite plane.

    This mirrors, at mission-design fidelity, the classic drift-orbit
    technique that a differential corrector (e.g. GMAT's Target/Vary/Achieve)
    would normally automate -- here it is a single explicit two-body
    (Kepler mean-motion) calculation rather than an iterative solve. Because
    the controller re-evaluates continuously, a sequence of these
    open-loop-per-maneuver corrections is still closed-loop at the mission
    timescale: any residual error from one correction simply triggers
    another.

    Only satellite B is maneuvered; satellite A's orbit is left undisturbed
    and serves as the phasing reference (it still receives its own,
    independent :class:`AltitudeKeepingController`).

    Actuator arbitration
    ---------------------
    Satellite B shares its single electric thruster (and hence its
    ``extForceTorque`` effector) with its own :class:`AltitudeKeepingController`.
    Orbit-safety altitude keeping takes priority: if
    ``altitude_controller_b.burnOn`` is true on a given control tick, this
    controller leaves the effector's commanded force untouched and simply
    pauses (it does not advance its burn/drift bookkeeping that tick, so no
    phasing progress -- planned or accounted -- is lost, only delayed).
    """

    IDLE, BURN_OUT, DRIFT, BURN_RESTORE = range(4)
    _STATE_NAMES = {IDLE: "IDLE", BURN_OUT: "BURN_OUT", DRIFT: "DRIFT", BURN_RESTORE: "BURN_RESTORE"}

    def __init__(
        self,
        name: str,
        mu: float,
        nominal_a_m: float,
        target_separation_deg: float,
        tolerance_deg: float,
        restore_tolerance_deg: float,
        correction_window_days: float,
        max_drift_days: float,
        max_delta_a_m: float,
        thrust_n: float,
        isp_s: float,
        dry_mass_kg: float,
        propellant_kg: float,
        orbit_period_s: float,
        eclipse_sunlit_threshold: float = 0.99,
        g0_mps2: float = 9.80665,
        log_decimation: int = 12,
    ):
        super().__init__()
        self.ModelTag = name

        self.scStateInMsgA = messaging.SCStatesMsgReader()
        self.scStateInMsgB = messaging.SCStatesMsgReader()
        self.eclipseInMsgB = messaging.EclipseMsgReader()

        self.extForceEffectorB = None
        self.scObjectB = None
        # Set externally to the co-located AltitudeKeepingController for
        # satellite B, for the thruster-arbitration check described above.
        self.altitudeControllerB = None

        self.mu = mu  # [m^3/s^2]
        self.aNom = nominal_a_m  # [m]
        self.targetSeparationRad = np.radians(target_separation_deg)  # [rad]
        self.tolRad = np.radians(tolerance_deg)  # [rad]
        self.restoreTolRad = np.radians(restore_tolerance_deg)  # [rad]
        self.correctionWindowS = correction_window_days * 86400.0  # [s]
        self.maxDriftS = max_drift_days * 86400.0  # [s]
        self.maxDeltaA = max_delta_a_m  # [m]
        self.thrustN = thrust_n  # [N]
        self.ispS = isp_s  # [s]
        self.g0 = g0_mps2  # [m/s^2]
        self.dryMass = dry_mass_kg  # [kg]
        # Fallback propellant tracker, used only if altitudeControllerB is
        # never set. Normally this controller shares satellite B's ONE
        # physical tank with its AltitudeKeepingController (see
        # _propellant_tracker()) rather than keeping an independent belief
        # about how much propellant is left -- two controllers commanding
        # the same extForceTorque effector must not track two different
        # masses for the same tank.
        self.propellant = propellant_kg  # [kg]
        self.sunlitThreshold = eclipse_sunlit_threshold  # [-]
        self.logDecimation = max(1, int(log_decimation))
        self._tickCount = 0

        # Phase error is computed from OSCULATING mean anomaly, which carries
        # J2 short-period oscillation (co-planar satellites separated in
        # mean anomaly sample very different points of that oscillation at
        # any instant even when their MEAN elements match exactly). Smoothing
        # over one orbital
        # period rejects that noise so the controller reacts to real secular
        # drift only -- the same reasoning as AltitudeKeepingController's
        # altitude smoothing, applied to the error signal here.
        self.smoothingWindowS = orbit_period_s  # [s]
        self._errorHistory = []  # list of (t [s], rawError [rad])

        self.state = self.IDLE
        self._lastT = None  # [s]
        self._targetDv = 0.0  # [m/s]
        self._accumDv = 0.0  # [m/s]
        self._burnSign = 1.0  # [-] +1 prograde (raise a), -1 retrograde (lower a)
        self._driftStartT = 0.0  # [s]

        self.tLog = []
        self.errorDegLog = []
        self.stateLog = []
        self.propellantLog = []
        self.deltaVLog = []
        self._cumulativeDv = 0.0  # [m/s]

    def Reset(self, CurrentSimNanos):
        self.state = self.IDLE
        self._lastT = CurrentSimNanos * macros.NANO2SEC
        self._accumDv = 0.0
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

        _, mA = self._mean_anomaly(self.mu, rA, vA)
        _, mB = self._mean_anomaly(self.mu, rB, vB)

        # error > 0 means B's phase leads the target separation (B is "too
        # far ahead" of A); error < 0 means B trails. Smoothed over one
        # orbital period to reject J2 short-period osculating-element noise
        # (see the smoothingWindowS comment in __init__) -- using the raw,
        # un-smoothed value here would make the controller chase that noise
        # once per orbit instead of real secular drift.
        rawError = _wrap_pm_pi((mB - mA) - self.targetSeparationRad)  # [rad]
        self._errorHistory.append((t, rawError))
        while self._errorHistory and (t - self._errorHistory[0][0]) > self.smoothingWindowS:
            self._errorHistory.pop(0)
        error = self._circular_mean(np.array([e for _, e in self._errorHistory]))  # [rad]

        inSun = True
        if self.eclipseInMsgB.isLinked():
            inSun = self.eclipseInMsgB().shadowFactor > self.sunlitThreshold

        # Thruster arbitration: altitude keeping owns the effector whenever
        # it is actively burning. Log telemetry and return without touching
        # the effector or advancing the state machine's clocks.
        thrusterHeldByAltCtrl = (
            self.altitudeControllerB is not None and self.altitudeControllerB.burnOn
        )
        if thrusterHeldByAltCtrl:
            self._tickCount += 1
            if self._tickCount % self.logDecimation == 0:
                self.tLog.append(t)
                self.errorDegLog.append(np.degrees(error))
                self.stateLog.append(self.state)
                self.propellantLog.append(self._propellant_tracker().propellant)
                self.deltaVLog.append(self._cumulativeDv)
            return

        thrustMag = 0.0  # [N]

        if self.state == self.IDLE:
            if abs(error) > self.tolRad:
                n = np.sqrt(self.mu / self.aNom**3)  # [rad/s] mean motion
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
            overshot = np.sign(error) != self._burnSign if error != 0.0 else False
            if abs(error) < self.restoreTolRad or overshot or (t - self._driftStartT) > self.maxDriftS:
                self.state = self.BURN_RESTORE

        elif self.state == self.BURN_RESTORE:
            thrustMag = self.thrustN if inSun else 0.0
            if self._accumDv >= self._targetDv:
                self.state = self.IDLE
                thrustMag = 0.0

        tracker = self._propellant_tracker()
        currentMass = self.dryMass + tracker.propellant  # [kg]

        if thrustMag > 0.0:
            accel = thrustMag / currentMass  # [m/s^2]
            self._accumDv += accel * dt
            self._cumulativeDv += accel * dt
            mDot = thrustMag / (self.ispS * self.g0)  # [kg/s]
            tracker.propellant = max(0.0, tracker.propellant - mDot * dt)

        if self.scObjectB is not None:
            self.scObjectB.hub.mHub = self.dryMass + tracker.propellant

        forceVec = np.zeros(3)
        if thrustMag > 0.0:
            vHatB = vB / np.linalg.norm(vB)
            sign = self._burnSign if self.state == self.BURN_OUT else -self._burnSign
            forceVec = thrustMag * sign * vHatB
        if self.extForceEffectorB is not None:
            self.extForceEffectorB.extForce_N = forceVec.tolist()

        self._tickCount += 1
        if self._tickCount % self.logDecimation == 0:
            self.tLog.append(t)
            self.errorDegLog.append(np.degrees(error))
            self.stateLog.append(self.state)
            self.propellantLog.append(tracker.propellant)
            self.deltaVLog.append(self._cumulativeDv)

    def _propellant_tracker(self):
        # Satellite B's thruster (and hence its one physical propellant
        # tank) is shared with its own AltitudeKeepingController (see the
        # thruster-arbitration check above); track mass through that same
        # object when it is available rather than keeping an independent
        # second belief about how much propellant is left. Falls back to
        # this controller's own tracker only if none was wired up.
        return self.altitudeControllerB if self.altitudeControllerB is not None else self
