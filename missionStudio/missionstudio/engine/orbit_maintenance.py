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
Automated altitude/semi-major-axis station-keeping, with delta-V and
propellant bookkeeping (``schema.scenario.StationKeepingConfig``).

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

Verification status: same as ``engine/fsw.py``/``engine/service.py`` --
cannot be executed in this project's development sandbox (no Basilisk
build here); the burn/bookkeeping logic is copied from
``../missionAnalysis``'s already-reviewed controller, not written from
memory.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from Basilisk.architecture import messaging, sysModel
from Basilisk.simulation import extForceTorque
from Basilisk.utilities import macros

from ..schema.scenario import StationKeepingConfig


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

        currentMass = self.dryMass + self.propellant  # [kg]

        mDot = 0.0  # [kg/s]
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
