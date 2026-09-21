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

"""
Mission and constellation design parameters for an Earth-observation
constellation, mirroring the companion GMAT mission script so the two tools
are directly comparable.

This module is intentionally dependency-light (``numpy`` + the standard library
only) so the orbit-design math -- in particular the sun-synchronous RAAN-for-LTDN
solve -- can be inspected and unit tested without a built Basilisk installation.
All Basilisk-specific simulation setup (gravity bodies, dynamic effectors,
controllers) lives in ``run_constellation_mission.py``.

Two ways to change what's in this file:

* ``configure_mission.py`` edits a single scalar constant at a time (bus
  mass, Cd/Cr/areas, propulsion, epoch, mission duration, altitude
  deadband, phasing tolerance, gravity degree) directly in this file's
  source, in place.
* ``setup_wizard.py`` is an interactive front end for everything, including
  the *structural* things a single scalar can't express -- how many
  satellites are in the constellation, each one's own orbit, and how many
  ground stations there are, at what locations. It writes those to
  ``constellation_setup.json`` next to this file, which -- if present --
  *replaces* the ``SSO_PLANE`` / ``CUSTOM_SATELLITES`` / ``GROUND_STATIONS``
  built from the scalar defaults below (see ``_load_constellation_setup()``).
  Run ``python3 setup_wizard.py`` rather than hand-writing that JSON file.

See ``README.md`` in this folder for the architecture write-up and a full list
of assumptions/placeholders.
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Epoch and mission duration
# ---------------------------------------------------------------------------
EPOCH_UTC = datetime(2028, 10, 1, 0, 0, 0)
# SPICE-recognizable epoch string, consumed by simIncludeGravBody.createSpiceInterface()
# and by simHelpers.timeStringToGregorianUTCMsg().
EPOCH_SPICE_STRING = "2028 OCT 01 00:00:00.0 (UTC)"
MISSION_DURATION_YEARS = 3  # [yr]
MISSION_END_UTC = EPOCH_UTC.replace(year=EPOCH_UTC.year + MISSION_DURATION_YEARS)
MISSION_DURATION_S = (MISSION_END_UTC - EPOCH_UTC).total_seconds()  # [s]

# ---------------------------------------------------------------------------
# Earth constants used only for the mission-design math in this file (RAAN
# solve, nominal SMA). The Basilisk simulation itself takes its Earth mu/
# radius/gravity field from simIncludeGravBody.gravBodyFactory().createEarth(),
# which is the value of record for the actual propagation.
# ---------------------------------------------------------------------------
MU_EARTH = 3.986004418e14  # [m^3/s^2]
R_EARTH_EQ = 6378136.6  # [m] equatorial radius, WGS-84-consistent placeholder

# ---------------------------------------------------------------------------
# Common bus properties (per mission statement; explicitly-flagged values are
# placeholders pending real hardware selection)
# ---------------------------------------------------------------------------
DRY_MASS_KG = 300.0  # [kg]
DRAG_COEFF = 2.2  # [-] Cd
SRP_COEFF = 1.8  # [-] Cr
DRAG_AREA_M2 = 2.2  # [m^2]
SRP_AREA_M2 = 2.6  # [m^2]

# PLACEHOLDER: the mission statement gives dry mass but not a propellant
# budget. Sized generously here to cover a 5-year LEO SSO station-keeping +
# phasing timeline at the given thrust/Isp; replace once a real propulsion
# budget/tank sizing exists.
PROPELLANT_MASS_BOL_KG = 20.0  # [kg]

# ---------------------------------------------------------------------------
# Propulsion: electric only, placeholder Hall-effect-class values pending
# actual hardware selection. THRUST_N/ISP_S drive the physics (rocket
# equation + force magnitude in constellation_controllers.py);
# PROPULSION_TYPE is a free-text label carried into logs/summaries only --
# it does not affect the simulation, it just documents which hardware
# assumption THRUST_N/ISP_S/PROPELLANT_MASS_BOL_KG correspond to.
# ---------------------------------------------------------------------------
PROPULSION_TYPE = "Hall-effect thruster (placeholder pending hardware selection)"  # [-] descriptive only
THRUST_N = 10.0e-3  # [N] ~10 mN
ISP_S = 1500.0  # [s]
G0_MPS2 = 9.80665  # [m/s^2] standard gravity, for the rocket equation (not mission-specific -- not user-configurable)

# ---------------------------------------------------------------------------
# Constellation orbit design
#
# These are the DEFAULTS used to build SSO_PLANE/CUSTOM_SATELLITES below when
# constellation_setup.json (see module docstring) is not present. Once that
# file exists it is the actual source of truth for the constellation's
# satellite count and every satellite's orbit -- these scalars stop being
# read for that purpose (configure_mission.py can still edit them, but the
# edits are then inert until/unless constellation_setup.json is removed).
# ---------------------------------------------------------------------------
ALT_NOMINAL_M = 570.0e3  # [m]
A_NOMINAL_M = R_EARTH_EQ + ALT_NOMINAL_M  # [m] nominal semimajor axis

SSO_SATELLITE_COUNT = 3  # [-] satellites sharing the SSO plane (1 chief + 2 followers)
SSO_INCLINATION_DEG = 97.6704  # [deg]
SSO_ECC = 0.0011  # [-]
SSO_AOP_DEG = 90.0  # [deg] frozen-orbit condition (nulls the J3 secular e-vector drift)
SSO_LTDN_HOURS = 10.5  # [hr] ~10:30 local time of descending node

# PLACEHOLDER reconfigurable-formation schedule, one entry per follower (so
# SSO_SATELLITE_COUNT - 1 entries): each follower holds its own along-track
# distance from the chief (SSO-1), stepping to the next value in
# distances_km every interval_days (holding at the last value thereafter --
# see constellation_controllers.SeparationSchedule). Not a real ops plan --
# it exists to demonstrate "different relative distances that reconfigure
# every few months, 1000 km down to 50 km" concretely; retune via
# setup_wizard.py once the real reconfiguration plan is known. Two
# followers deliberately run different sequences/cadences here so the
# default constellation actually shows different satellites at different
# relative distances at any given time, not just one pair with one moving
# target.
_DEFAULT_FOLLOWER_SCHEDULES = [
    dict(distances_km=[1000.0, 500.0, 250.0, 100.0, 50.0], interval_days=90.0),
    dict(distances_km=[500.0, 200.0, 750.0, 100.0], interval_days=120.0),
]

MIDINC_INCLINATION_DEG = 53.0  # [deg]
# PLACEHOLDERS: no frozen-orbit / phasing spec was given for the 53 deg plane.
MIDINC_ECC = 0.0  # [-]
MIDINC_AOP_DEG = 0.0  # [deg] undefined at e~0, unused
MIDINC_RAAN_DEG = 0.0  # [deg] "coverage-driven, TBD" per mission statement
MIDINC_MEAN_ANOM_DEG = 0.0  # [deg]

# ---------------------------------------------------------------------------
# Station-keeping / constellation-keeping control parameters
# ---------------------------------------------------------------------------
ALT_DEADBAND_M = 5.0e3  # [m] reboost triggers when altitude < nominal - deadband
# Altitude is smoothed over one nominal orbital period before being compared
# against the deadband, to reject J2 short-period oscillation (a few km peak
# -to-peak at this altitude) that would otherwise chatter the controller.
ORBIT_PERIOD_S = 2.0 * np.pi * np.sqrt(A_NOMINAL_M**3 / MU_EARTH)  # [s]

# Trigger/restore tolerances are FRACTIONS of the current target separation
# (not fixed angles): a fixed-degree tolerance doesn't scale across a
# schedule spanning 1000 km down to 50 km -- 1 deg at 570 km altitude is
# already ~120 km, bigger than the tightest target in a typical schedule.
# A wider fraction means fewer, larger corrections (a "not too tight"
# deadband, cheaper in total dV); a narrower one means tighter
# formation-keeping at the cost of more frequent burns. There is a real
# deltaV-vs-tightness trade here with no single "optimal" answer independent
# of the ops concept, so this is meant to be retuned, not treated as final.
PHASING_TOLERANCE_FRACTION = 0.10  # [-] trigger threshold, as a fraction of the current target separation
PHASING_RESTORE_TOLERANCE_FRACTION = 0.02  # [-] "close enough, stop drifting" threshold, same units
PHASING_CORRECTION_WINDOW_DAYS = 21.0  # [day] target time to null a fresh phasing error
PHASING_MAX_DRIFT_DAYS = 90.0  # [day] safety cap on the drift coast phase
PHASING_MAX_DELTA_A_M = 3000.0  # [m] safety clamp on the drift-orbit SMA offset

# Dynamics/control task cadence (see README for the tractability rationale)
DYNAMICS_TASK_RATE_S = 60.0  # [s]
CONTROL_TASK_RATE_S = 300.0  # [s]

# Earth gravity spherical-harmonics degree/order. 10-20 per mission statement;
# default kept at the low end for run-time tractability over 5 years x 3
# spacecraft. Raise toward 20 once run time on your hardware is characterized.
EARTH_GRAV_DEGREE = 10

# ---------------------------------------------------------------------------
# Communications / on-board data handling (PLACEHOLDERS: no EO payload data
# rate, downlink link budget, on-board storage capacity, or ground network
# was specified in the mission statement). Ground station locations are
# real-world reference points chosen for plausibility (a high-latitude site
# sees an SSO pass almost every orbit; Boulder matches the placeholder site
# already used elsewhere in Basilisk's own examples) -- not a claim about
# the actual ground network for this mission. This default list is only used
# when constellation_setup.json (see module docstring) is absent -- that
# file's "ground_stations" list otherwise replaces it entirely, at whatever
# count and locations you gave setup_wizard.py.
# ---------------------------------------------------------------------------
_DEFAULT_GROUND_STATIONS = [
    dict(name="Svalbard", lat_deg=78.2300, lon_deg=15.3894, alt_m=0.0, min_elevation_deg=5.0),
    dict(name="Boulder", lat_deg=40.009971, lon_deg=-105.243895, alt_m=1624.0, min_elevation_deg=10.0),
]
GROUND_STATION_MAX_RANGE_M = 1.0e9  # [m] effectively unlimited slant-range cutoff

EO_INSTRUMENT_BAUD_RATE_BPS = 50.0e6  # [bit/s] PLACEHOLDER EO payload data-generation rate, sunlit-only
DOWNLINK_BAUD_RATE_BPS = 150.0e6  # [bit/s] PLACEHOLDER X-band downlink rate
DOWNLINK_PACKET_SIZE_BITS = 1.0e6  # [bit] PLACEHOLDER downlink packet/buffer size
DOWNLINK_NUM_BUFFERS = 2  # [-] PLACEHOLDER
DATA_STORAGE_CAPACITY_BITS = 256.0e9  # [bit] PLACEHOLDER on-board storage capacity (~32 GB)

# Eclipse threshold: shadow factor above this counts as "in sunlight". Shared
# by two independent gates: electric-propulsion thrust-enable (the thruster
# pauses off battery-only power -- see constellation_controllers.py) and the
# EO instrument's data-collection duty cycle (communications.py).
ECLIPSE_SUNLIT_THRESHOLD = 0.99  # [-]


# ---------------------------------------------------------------------------
# Low-precision Sun right ascension (Vallado / Astronomical Almanac
# low-precision solar ephemeris algorithm, ~0.01 deg accurate 1950-2050).
# Used ONLY for the RAAN-for-LTDN mission-design solve below; the Basilisk
# simulation itself uses full SPICE ephemerides for Sun/Moon third-body
# gravity and SRP, which is the value of record for the actual propagation.
# ---------------------------------------------------------------------------
def _julian_date(dt: datetime) -> float:
    """Julian date for a Gregorian-calendar UTC datetime."""
    y, m = dt.year, dt.month
    d = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0  # [day]
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def sun_right_ascension_deg(epoch_utc: datetime) -> float:
    """Low-precision Sun right ascension [deg] in the EME2000/ICRF frame."""
    jd = _julian_date(epoch_utc)
    t_tdb = (jd - 2451545.0) / 36525.0  # [century] Julian centuries from J2000
    lambda_mean_deg = np.mod(280.460 + 36000.771 * t_tdb, 360.0)  # [deg]
    m_deg = np.mod(357.5291092 + 35999.05034 * t_tdb, 360.0)  # [deg] sun mean anomaly
    m_rad = np.radians(m_deg)
    lambda_ecl_deg = (
        lambda_mean_deg
        + 1.914666471 * np.sin(m_rad)
        + 0.019994643 * np.sin(2.0 * m_rad)
    )  # [deg] apparent ecliptic longitude
    eps_deg = 23.439291 - 0.0130042 * t_tdb  # [deg] mean obliquity of the ecliptic
    lambda_ecl = np.radians(lambda_ecl_deg)
    eps = np.radians(eps_deg)
    ra = np.arctan2(np.cos(eps) * np.sin(lambda_ecl), np.cos(lambda_ecl))
    return float(np.degrees(ra) % 360.0)


def raan_for_ltdn_deg(epoch_utc: datetime, ltdn_hours: float) -> float:
    """RAAN [deg] that places the orbit's descending-node local mean-solar
    time at ``ltdn_hours``.

    Equation of time is neglected (the algorithm uses the Sun's right
    ascension as a stand-in for local *mean* solar time), which carries a
    budget of roughly +/-16 minutes across the year -- acceptable for the
    "~10:30 LTDN" placeholder in the mission statement. Retarget with a
    higher-fidelity (e.g. SPICE-based) Sun ephemeris once the exact launch
    epoch and LTDN requirement are finalized.
    """
    alpha_sun_deg = sun_right_ascension_deg(epoch_utc)  # [deg]
    ltan_hours = np.mod(ltdn_hours + 12.0, 24.0)  # [hr] ascending node is 12 h from descending
    raan_deg = alpha_sun_deg + 15.0 * (ltan_hours - 12.0)  # [deg] 15 deg/hr Earth-Sun geometry
    return float(raan_deg % 360.0)


SSO_RAAN_DEG = raan_for_ltdn_deg(EPOCH_UTC, SSO_LTDN_HOURS)  # [deg] (default SSO_PLANE only; see below)


# ---------------------------------------------------------------------------
# Constellation structure: SSO_PLANE (a group of satellites evenly phased in
# mean anomaly, sharing one orbit plane/shape) + CUSTOM_SATELLITES (each
# independent, no phasing partner) + GROUND_STATIONS. Built from the scalar
# defaults above, unless constellation_setup.json (see module docstring)
# exists, in which case ITS "sso_plane" / "custom_satellites" /
# "ground_stations" entries are used instead (falling back to the default
# for any key the file omits). Run setup_wizard.py to create/edit that file
# interactively rather than hand-writing it.
# ---------------------------------------------------------------------------
CONSTELLATION_SETUP_PATH = Path(__file__).resolve().parent / "constellation_setup.json"


def _default_sso_plane() -> dict:
    return dict(
        count=SSO_SATELLITE_COUNT,
        altitude_km=ALT_NOMINAL_M / 1000.0,
        inclination_deg=SSO_INCLINATION_DEG,
        ecc=SSO_ECC,
        aop_deg=SSO_AOP_DEG,
        ltdn_hours=SSO_LTDN_HOURS,
        follower_schedules=_DEFAULT_FOLLOWER_SCHEDULES,
    )


def _default_custom_satellites() -> list:
    return [
        dict(
            name="MIDINC-1",
            altitude_km=ALT_NOMINAL_M / 1000.0,
            inclination_deg=MIDINC_INCLINATION_DEG,
            ecc=MIDINC_ECC,
            aop_deg=MIDINC_AOP_DEG,
            raan_deg=MIDINC_RAAN_DEG,
            mean_anom_deg=MIDINC_MEAN_ANOM_DEG,
        )
    ]


def _load_constellation_setup() -> tuple:
    """(sso_plane, custom_satellites, ground_stations), from
    constellation_setup.json when present (falling back to the hardcoded
    default for any of the three keys it doesn't include), otherwise from
    the hardcoded defaults alone.
    """
    sso_plane = _default_sso_plane()
    custom_satellites = _default_custom_satellites()
    ground_stations = list(_DEFAULT_GROUND_STATIONS)
    if CONSTELLATION_SETUP_PATH.exists():
        with open(CONSTELLATION_SETUP_PATH) as f:
            setup = json.load(f)
        sso_plane = setup.get("sso_plane", sso_plane)
        custom_satellites = setup.get("custom_satellites", custom_satellites)
        ground_stations = setup.get("ground_stations", ground_stations)
    return sso_plane, custom_satellites, ground_stations


SSO_PLANE, CUSTOM_SATELLITES, GROUND_STATIONS = _load_constellation_setup()


def _build_satellites(sso_plane: dict, custom_satellites: list) -> list:
    """Expand SSO_PLANE into `count` satellites sharing one physical orbit
    plane (RAAN/inclination/altitude/eccentricity) plus each independent
    CUSTOM_SATELLITES entry. Every satellite dict carries a "plane" key:
    satellites sharing a "plane" value are phased against each other by
    run_constellation_mission.py (one PhasingKeepingController per
    follower, referenced to the first satellite added to that plane as
    chief); a plane with only one member gets no phasing controller.

    Within the SSO plane, the chief (k == 0) sits at mean_anom_deg=0 with
    no schedule. Each follower (k >= 1) draws its own entry from
    "follower_schedules" (a list of {distances_km, interval_days[, loop]}
    dicts -- one per follower, see SeparationSchedule in
    constellation_controllers.py): the follower's initial mean anomaly is
    set from the first distance in its schedule, and the schedule dict
    itself is attached under "schedule" so run_constellation_mission.py
    can build a SeparationSchedule and step the target separation every
    few months. This is how "different relative distances" per follower,
    each changing over time, is represented. A follower with no matching
    "follower_schedules" entry (list too short) falls back to even
    spacing in mean anomaly with schedule=None, i.e. a fixed target
    separation held for the whole mission.
    """
    satellites = []

    count = max(0, int(sso_plane.get("count", 0)))
    if count > 0:
        sso_a_m = R_EARTH_EQ + sso_plane["altitude_km"] * 1000.0
        sso_raan_deg = raan_for_ltdn_deg(EPOCH_UTC, sso_plane["ltdn_hours"])
        follower_schedules = sso_plane.get("follower_schedules", [])
        for k in range(count):
            schedule = None
            if k == 0:
                mean_anom_deg = 0.0  # [deg] chief -- phasing reference for this plane
            else:
                follower_idx = k - 1
                if follower_idx < len(follower_schedules):
                    schedule = follower_schedules[follower_idx]
                    initial_distance_km = schedule["distances_km"][0]  # [km]
                    mean_anom_deg = float(
                        np.degrees(initial_distance_km * 1000.0 / sso_a_m)
                    ) % 360.0
                else:
                    mean_anom_deg = k * 360.0 / count  # [deg] no schedule given -- fall back to even spacing
            satellites.append(
                dict(
                    name=f"SSO-{k + 1}",
                    plane="SSO",
                    a_m=sso_a_m,
                    e=sso_plane["ecc"],
                    i_deg=sso_plane["inclination_deg"],
                    raan_deg=sso_raan_deg,
                    aop_deg=sso_plane["aop_deg"],
                    mean_anom_deg=mean_anom_deg,
                    schedule=schedule,
                )
            )

    for sat in custom_satellites:
        satellites.append(
            dict(
                name=sat["name"],
                plane=sat["name"],  # standalone -- no phasing partner
                a_m=R_EARTH_EQ + sat["altitude_km"] * 1000.0,
                e=sat["ecc"],
                i_deg=sat["inclination_deg"],
                raan_deg=sat["raan_deg"],
                aop_deg=sat["aop_deg"],
                mean_anom_deg=sat["mean_anom_deg"],
                schedule=None,
            )
        )

    if not satellites:
        raise ValueError(
            "Constellation has zero satellites (SSO_PLANE count is 0 and CUSTOM_SATELLITES "
            "is empty) -- add at least one in constellation_setup.json or via setup_wizard.py."
        )
    return satellites


SATELLITES = _build_satellites(SSO_PLANE, CUSTOM_SATELLITES)
