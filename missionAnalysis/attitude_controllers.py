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
Pure-Python Basilisk ``SysModel`` implementing per-satellite attitude
pointing: :class:`AttitudePointingController` drives the spacecraft to point
a body-fixed vector at whichever target currently matters more --

* the downlink antenna boresight at the best (highest-elevation) ground
  station currently in access range, or, when no ground station is in
  range,
* the solar panel normal at the sun,

i.e. "point the antenna at the ground station whenever in contact, point
the panels at the sun the rest of the time." This priority is a deliberate
simplification: both directions are body-fixed (no gimbaled panel/antenna
is modeled -- see README.md), so only one can be satisfied at a time, and a
downlink pass is short and schedule-driven while sun-pointing is not
time-critical, so downlink wins the conflict.

Guidance math (attitude tracking error ``sigma_BR`` from a body-fixed
pointing vector and an inertial target direction) follows the same
eigen-axis / ``-tan(phi/4)`` construction documented for Basilisk's own
:ref:`locationPointing` module, reimplemented directly in Python here rather
than wiring that C module (plus a second instance for the sun, plus a
mode-arbitration message router) -- this keeps the same "custom Python
control loop" architecture already used for station-keeping/phasing in
``constellation_controllers.py``, and lets one controller own the
antenna-vs-sun priority decision directly instead of splitting it across
multiple wired-together modules. See ``README.md`` for the full rationale
and its limitations (no reaction wheels, no slew-rate limiting, coarse
control cadence).

The control law is the textbook simple MRP regulator (Schaub & Junkins),
the same law Basilisk's own :ref:`mrpFeedback` reduces to with no reaction
wheels, no reference angular rate, and no integral term::

    Lr = -K * sigma_BR - P * omega_BR_B

applied as an idealized external torque (``extForceTorque.extTorquePntB_B``,
set directly, the same way the station-keeping/phasing controllers set
``extForce_N`` -- see ``constellation_controllers.py``) rather than through
a reaction wheel array, consistent with this study's existing choice not to
model real actuator hardware.
"""

import numpy as np
from Basilisk.architecture import sysModel, messaging
from Basilisk.utilities import macros


def _mrp_to_dcm(sigma):
    """[BN] direction cosine matrix from MRP ``sigma_BN`` (Schaub & Junkins eq. 3.87)."""
    s = np.asarray(sigma, dtype=float)
    s2 = float(s.dot(s))
    sTilde = np.array([[0.0, -s[2], s[1]], [s[2], 0.0, -s[0]], [-s[1], s[0], 0.0]])
    return np.eye(3) + (8.0 * sTilde.dot(sTilde) - 4.0 * (1.0 - s2) * sTilde) / (1.0 + s2) ** 2


class AttitudePointingController(sysModel.SysModel):
    """Body-fixed-vector pointing controller for one spacecraft -- antenna
    boresight at the best in-range ground station, else solar panel normal
    at the sun. See the module docstring for the guidance/control math.

    Ground stations are registered after construction via
    :meth:`add_ground_station` (one call per station in the constellation,
    not just the ones this satellite happens to be near -- access is
    evaluated every tick from each station's own access message, so a
    satellite can switch which station it points at as passes change).
    """

    ANTENNA, SUN = range(2)
    _MODE_NAMES = {ANTENNA: "ANTENNA", SUN: "SUN"}

    def __init__(
        self,
        name: str,
        sat_index: int,
        antenna_boresight_B,
        panel_normal_B,
        k_gain: float,
        p_gain: float,
        max_torque_nm: float,
        log_decimation: int = 120,
    ):
        super().__init__()
        self.ModelTag = name
        self.satIndex = sat_index

        self.scStateInMsg = messaging.SCStatesMsgReader()
        self.sunStateInMsg = messaging.SpicePlanetStateMsgReader()
        self._groundStations = []  # list of (name, GroundStateMsgReader, AccessMsgReader)

        # Direct object reference (wired up externally): the extForceTorque
        # effector this controller commands. Shared with the satellite's own
        # AltitudeKeepingController/PhasingKeepingController -- extForce_N
        # (translational) and extTorquePntB_B (rotational) are independent
        # fields on the same effector, so there is no conflict.
        self.extForceEffector = None

        antenna = np.asarray(antenna_boresight_B, dtype=float)
        panel = np.asarray(panel_normal_B, dtype=float)
        self.antennaBoresight_B = antenna / np.linalg.norm(antenna)
        self.panelNormal_B = panel / np.linalg.norm(panel)
        self.K = k_gain  # [N*m]
        self.P = p_gain  # [N*m*s]
        self.maxTorque = max_torque_nm  # [N*m]

        self.mode = self.SUN
        self.contactName = None  # ground station name while mode == ANTENNA, else None
        self.pointingErrorDeg = 0.0  # [deg] current |phi| to the active target

        self._lastT = None  # [s]
        self._sigmaBROld = None

        # Telemetry is recorded every Nth control tick -- default 120 at the
        # default 30 s attitude-control cadence gives hourly logging (same
        # target cadence as the other controllers' decimated telemetry, see
        # constellation_controllers.py) despite this task running 10x more
        # often than the 300 s orbital control task those use.
        self.logDecimation = max(1, int(log_decimation))
        self._tickCount = 0

        # Python-side telemetry (cheap; same rationale as the other
        # controllers' decimated logging -- see constellation_controllers.py).
        self.tLog = []
        self.modeLog = []  # 1 == ANTENNA, 0 == SUN
        self.pointingErrorDegLog = []

    def add_ground_station(self, name: str, ground_location_module) -> None:
        """Register a :ref:`GroundLocation` module as a candidate antenna
        target. ``ground_location_module.accessOutMsgs`` must already have
        this satellite's entry, i.e. ``addSpacecraftToModel()`` must have
        been called for every satellite (in the same order, see
        ``communications.build_ground_stations()``) before this is called.
        """
        gsReader = messaging.GroundStateMsgReader()
        gsReader.subscribeTo(ground_location_module.currentGroundStateOutMsg)
        accessReader = messaging.AccessMsgReader()
        accessReader.subscribeTo(ground_location_module.accessOutMsgs[self.satIndex])
        self._groundStations.append((name, gsReader, accessReader))

    def Reset(self, CurrentSimNanos):
        self._lastT = CurrentSimNanos * macros.NANO2SEC
        self._sigmaBROld = None
        self.mode = self.SUN
        self.contactName = None
        if self.extForceEffector is not None:
            self.extForceEffector.extTorquePntB_B = [0.0, 0.0, 0.0]

    @staticmethod
    def _perp_axis(v):
        """Any unit vector perpendicular to ``v`` -- used only in the rare
        exactly-180-deg case, where the true rotation axis is undefined.
        """
        axis = np.array([1.0, 0.0, 0.0]) if abs(v[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        perp = np.cross(v, axis)
        return perp / np.linalg.norm(perp)

    def UpdateState(self, CurrentSimNanos):
        t = CurrentSimNanos * macros.NANO2SEC  # [s]
        dt = t - self._lastT if self._lastT is not None else 0.0  # [s]
        self._lastT = t

        scState = self.scStateInMsg()
        rSat_N = np.array(scState.r_BN_N)  # [m]
        sigma_BN = np.array(scState.sigma_BN)
        BN = _mrp_to_dcm(sigma_BN)

        # Best (highest-elevation) ground station currently in access, if any.
        bestName, bestElev, bestTarget_N = None, -np.inf, None
        for gsName, gsReader, accessReader in self._groundStations:
            access = accessReader()
            if access.hasAccess and access.elevation > bestElev:
                bestName, bestElev = gsName, access.elevation
                bestTarget_N = np.array(gsReader().r_LN_N)

        if bestName is not None:
            target_N, pHat_B, mode = bestTarget_N, self.antennaBoresight_B, self.ANTENNA
        else:
            sunState = self.sunStateInMsg()
            target_N, pHat_B, mode = np.array(sunState.PositionVector), self.panelNormal_B, self.SUN

        rTarget_N = target_N - rSat_N
        norm = np.linalg.norm(rTarget_N)
        rHat_N = rTarget_N / norm if norm > 1e-6 else np.array([1.0, 0.0, 0.0])
        rHat_B = BN.dot(rHat_N)

        dot = float(np.clip(pHat_B.dot(rHat_B), -1.0, 1.0))
        phi = float(np.arccos(dot))  # [rad]

        crossVec = np.cross(pHat_B, rHat_B)
        crossNorm = np.linalg.norm(crossVec)
        if crossNorm < 1e-8:
            sigma_BR = np.zeros(3) if dot > 0.0 else -np.tan(phi / 4.0) * self._perp_axis(pHat_B)
        else:
            sigma_BR = -np.tan(phi / 4.0) * (crossVec / crossNorm)

        # Crude body-rate-error proxy via finite differencing sigma_BR (the
        # same simplification Basilisk's own locationPointing.rst documents
        # for its numerical differentiation), with a guard against the MRP
        # shadow-set switch: a very negative dot product between successive
        # sigma_BR values means the representation flipped, not that the
        # error actually jumped, so treat that tick's rate as unknown (0)
        # rather than propagate a spurious spike into the torque command.
        omega_BR_B = np.zeros(3)
        if self._sigmaBROld is not None and dt > 0.0 and sigma_BR.dot(self._sigmaBROld) > -0.5:
            omega_BR_B = 4.0 * (sigma_BR - self._sigmaBROld) / dt
        self._sigmaBROld = sigma_BR

        torque = -self.K * sigma_BR - self.P * omega_BR_B  # [N*m]
        torque = np.clip(torque, -self.maxTorque, self.maxTorque)

        if self.extForceEffector is not None:
            self.extForceEffector.extTorquePntB_B = torque.tolist()

        self.mode = mode
        self.contactName = bestName
        self.pointingErrorDeg = np.degrees(phi)

        self._tickCount += 1
        if self._tickCount % self.logDecimation == 0:
            self.tLog.append(t)
            self.modeLog.append(1 if mode == self.ANTENNA else 0)
            self.pointingErrorDegLog.append(np.degrees(phi))
