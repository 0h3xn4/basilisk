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
Walker-Delta/Walker-Star constellation generator: turns a small set of
high-level requirements (total satellite count, number of orbital planes,
altitude, inclination, phasing factor) into a full list of
:class:`~missionstudio.schema.scenario.SpacecraftConfig` with every
satellite's orbital elements pre-computed -- "the user only supplies the
requirement, the tool designs the constellation", per the feature request
this responds to.

Standard Walker-pattern notation (Vallado, *Fundamentals of Astrodynamics
and Applications*; Wertz, *Space Mission Analysis and Design*): a
constellation ``i:T/P/F`` puts ``T`` satellites in ``P`` equally-spaced
orbital planes (``T`` must be evenly divisible by ``P``) at inclination
``i``, with relative phasing set by ``F`` (an integer, ``0 <= F < P``).
For plane ``p`` (0-indexed) and satellite slot ``s`` within that plane
(0-indexed, ``T/P`` slots per plane):

.. code-block:: text

    RAAN_p       = raan_offset + p * (raan_spread / P)
    mean_anomaly = s * (360 / (T/P)) + p * F * (360 / T)

``raan_spread`` is 360 degrees for the "delta" pattern (RAAN planes spread
all the way around, e.g. GPS) or 180 degrees for the "star" pattern (RAAN
planes spread over one hemisphere, e.g. Iridium -- appropriate for
near-polar constellations where ascending and descending nodes of
opposite planes coincide).

Every generated satellite is a deep copy of a caller-supplied ``template``
:class:`SpacecraftConfig`, with only ``name`` and ``orbit`` replaced --
every other field (mass, sensors, actuators, FSW mode, power, station
-keeping, RF link, ...) is carried through unchanged, so the user
configures ONE representative satellite the normal way (the spacecraft
editor) and this module clones it into the full constellation, per this
feature's "you only supply what's needed" design goal. Orbits use MEAN
anomaly (``schema.scenario.OrbitIC.anomaly_type == "mean"``), the natural
choice for a phased pattern.

This module has NO Basilisk import and is fully unit-testable here (pure
orbital mechanics, no simulation) -- central-body equatorial radii (needed
to convert altitude to semi-major axis) are hardcoded from Basilisk's own
``astroConstants.h`` ``REQ_*`` values (as consumed by
``simIncludeGravBody.py``'s ``createXxx()`` helpers), copied here rather
than re-derived, so the semi-major axis this module computes matches
exactly what ``engine.service`` will actually simulate for the same
``gravity.central_body``.

Also holds :class:`SeparationSchedule` -- the pure-math schedule
:class:`~missionstudio.schema.scenario.PhasingKeepingConfig` /
``engine.orbit_maintenance.PhasingKeepingController`` use for a
constellation's along-track phasing maintenance over time, kept here
(rather than in ``engine.orbit_maintenance``, which needs Basilisk) so it
stays unit-testable alongside the generator that produces the
constellations it maintains.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import List

from ..schema.scenario import OrbitIC, ScenarioValidationError, SpacecraftConfig

# [km] equatorial radius -- see module docstring for provenance. Kept in
# sync manually with astroConstants.h's REQ_* values; only bodies
# schema.scenario.SUPPORTED_CENTRAL_BODIES actually offers are listed.
CENTRAL_BODY_EQUATORIAL_RADIUS_KM = {
    "sun": 695000.0,
    "mercury": 2439.7,
    "venus": 6051.8,
    "earth": 6378.1366,
    "moon": 1737.4,
    "mars": 3396.19,
    "mars barycenter": 3396.19,
    "jupiter": 71492.0,
}

WALKER_PATTERNS = ("delta", "star")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioValidationError(message)


@dataclass
class WalkerConstellationRequest:
    """See module docstring for the Walker-pattern math this drives."""

    total_satellites: int  # T
    num_planes: int  # P -- must evenly divide total_satellites
    phasing_factor: int  # F, 0 <= F < num_planes
    altitude_km: float  # [km] circular-orbit altitude (constant across the constellation)
    inclination_deg: float  # [deg] shared by every satellite
    central_body: str = "earth"
    eccentricity: float = 0.0  # [-] shared by every satellite; 0 for the usual circular case
    arg_periapsis_deg: float = 0.0  # [deg] shared by every satellite
    pattern: str = "delta"  # one of WALKER_PATTERNS
    raan_offset_deg: float = 0.0  # [deg] rotates the whole constellation's RAAN reference
    name_prefix: str = "sat"  # generated names: "{name_prefix}-{plane:02d}-{slot:02d}"

    def validate(self) -> None:
        _require(self.total_satellites > 0, "constellation.total_satellites must be > 0")
        _require(self.num_planes > 0, "constellation.num_planes must be > 0")
        _require(self.total_satellites % self.num_planes == 0,
                  f"constellation.total_satellites ({self.total_satellites}) must be evenly divisible by "
                  f"num_planes ({self.num_planes})")
        _require(0 <= self.phasing_factor < self.num_planes,
                  f"constellation.phasing_factor must be in [0, num_planes) == [0, {self.num_planes})")
        _require(self.altitude_km > 0, "constellation.altitude_km must be > 0")
        _require(0.0 <= self.inclination_deg <= 180.0, "constellation.inclination_deg must be in [0, 180]")
        _require(0.0 <= self.eccentricity < 1.0, "constellation.eccentricity must be in [0, 1) (elliptical only)")
        _require(self.pattern in WALKER_PATTERNS,
                  f"constellation.pattern {self.pattern!r} must be one of {WALKER_PATTERNS}")
        _require(self.central_body in CENTRAL_BODY_EQUATORIAL_RADIUS_KM,
                  f"constellation.central_body {self.central_body!r} has no known equatorial radius in "
                  f"engine.constellation -- supported: {sorted(CENTRAL_BODY_EQUATORIAL_RADIUS_KM)}")
        _require(bool(self.name_prefix.strip()), "constellation.name_prefix must not be empty")


def generate_walker_constellation(request: WalkerConstellationRequest,
                                   template: SpacecraftConfig) -> List[SpacecraftConfig]:
    """Returns ``request.total_satellites`` :class:`SpacecraftConfig`
    copies of ``template``, each with ``name``/``orbit`` replaced per the
    Walker pattern (see module docstring) -- every other field (mass,
    sensors, actuators, FSW, power, station-keeping, RF link, ...) is
    carried through unchanged from ``template``. Raises
    :class:`~missionstudio.schema.scenario.ScenarioValidationError` if
    ``request`` itself is invalid; does not validate ``template`` (the
    caller already has/will, e.g. via ``Scenario.validate()`` once these
    are added to a scenario).
    """
    request.validate()

    radius_km = CENTRAL_BODY_EQUATORIAL_RADIUS_KM[request.central_body]
    semi_major_axis_km = radius_km + request.altitude_km

    sats_per_plane = request.total_satellites // request.num_planes
    raan_spread_deg = 360.0 if request.pattern == "delta" else 180.0
    delta_raan_deg = raan_spread_deg / request.num_planes
    delta_mean_anomaly_deg = 360.0 / sats_per_plane

    spacecraft: List[SpacecraftConfig] = []
    for plane in range(request.num_planes):
        raan_deg = (request.raan_offset_deg + plane * delta_raan_deg) % 360.0
        for slot in range(sats_per_plane):
            mean_anomaly_deg = (
                slot * delta_mean_anomaly_deg + plane * request.phasing_factor * 360.0 / request.total_satellites
            ) % 360.0

            sc = copy.deepcopy(template)
            sc.name = f"{request.name_prefix}-{plane + 1:02d}-{slot + 1:02d}"
            sc.orbit = OrbitIC(
                type="classical_elements",
                semi_major_axis_km=semi_major_axis_km,
                eccentricity=request.eccentricity,
                inclination_deg=request.inclination_deg,
                raan_deg=raan_deg,
                arg_periapsis_deg=request.arg_periapsis_deg,
                anomaly_type="mean",
                mean_anomaly_deg=mean_anomaly_deg,
            )
            spacecraft.append(sc)
    return spacecraft


class SeparationSchedule:
    """A time-varying along-track target separation between a
    ``PhasingKeepingConfig`` follower and its chief, stepping through a
    list of distances [km] every ``interval_days``, holding at the last
    entry after the list is exhausted (no looping) -- e.g.
    ``distances_km=[1000, 500, 100]`` with ``interval_days=90`` tightens
    the formation baseline every ~3 months, then holds at 100 km for the
    rest of the mission. A single-entry list holds that one separation for
    the whole mission regardless of ``interval_days``.

    Distance is converted to a mean-anomaly-equivalent angle via the
    small-angle arc-length approximation ``theta = distance / a`` (exact
    for a circular orbit; ``engine.orbit_maintenance.PhasingKeepingController``
    re-evaluates ``value_at`` every tick rather than reading it once, so
    this is what "reconfigures the formation every few months" means
    concretely. Ported unchanged from
    ``../missionAnalysis/constellation_controllers.py``'s class of the
    same name (pure math, no Basilisk dependency either there or here).
    """

    def __init__(self, distances_km, interval_days: float, semi_major_axis_m: float, loop: bool = False):
        if not distances_km:
            raise ValueError("SeparationSchedule needs at least one distance")
        self.targetsRad = [d * 1000.0 / semi_major_axis_m for d in distances_km]  # [rad] arc length s = a*theta
        self.intervalS = interval_days * 86400.0  # [s]
        self.loop = loop

    def value_at(self, t_s: float) -> float:
        """Current target separation [rad] at mission-elapsed time t_s [s]."""
        if self.intervalS <= 0.0 or len(self.targetsRad) == 1:
            return self.targetsRad[0]
        idx = int(t_s // self.intervalS)
        idx = (idx % len(self.targetsRad)) if self.loop else min(idx, len(self.targetsRad) - 1)
        return self.targetsRad[idx]
