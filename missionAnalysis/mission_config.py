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
Mission and constellation design parameters for a 3-satellite Earth-observation
constellation, mirroring the companion GMAT mission script so the two tools are
directly comparable.

This module is intentionally dependency-light (``numpy`` + the standard library
only) so the orbit-design math -- in particular the sun-synchronous RAAN-for-LTDN
solve -- can be inspected and unit tested without a built Basilisk installation.
All Basilisk-specific simulation setup (gravity bodies, dynamic effectors,
controllers) lives in ``run_constellation_mission.py``.

See ``README.md`` in this folder for the architecture write-up and a full list
of assumptions/placeholders.
"""

from datetime import datetime

import numpy as np

# ---------------------------------------------------------------------------
# Epoch and mission duration
# ---------------------------------------------------------------------------
EPOCH_UTC = datetime(2028, 10, 1, 0, 0, 0)
# SPICE-recognizable epoch string, consumed by simIncludeGravBody.createSpiceInterface()
# and by simHelpers.timeStringToGregorianUTCMsg().
EPOCH_SPICE_STRING = "2028 OCT 01 00:00:00.0 (UTC)"
MISSION_DURATION_YEARS = 5  # [yr]
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
# actual hardware selection
# ---------------------------------------------------------------------------
THRUST_N = 10.0e-3  # [N] ~10 mN
ISP_S = 1500.0  # [s]
G0_MPS2 = 9.80665  # [m/s^2] standard gravity, for the rocket equation

# ---------------------------------------------------------------------------
# Constellation orbit design
# ---------------------------------------------------------------------------
ALT_NOMINAL_M = 570.0e3  # [m]
A_NOMINAL_M = R_EARTH_EQ + ALT_NOMINAL_M  # [m] nominal semimajor axis

SSO_INCLINATION_DEG = 97.6704  # [deg]
SSO_ECC = 0.0011  # [-]
SSO_AOP_DEG = 90.0  # [deg] frozen-orbit condition (nulls the J3 secular e-vector drift)
SSO_LTDN_HOURS = 10.5  # [hr] ~10:30 local time of descending node

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

PHASING_TOLERANCE_DEG = 1.0  # [deg] trigger threshold on |mean-anomaly error|
PHASING_RESTORE_TOLERANCE_DEG = 0.05  # [deg] "close enough, stop drifting" threshold
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

# Eclipse threshold: shadow factor above this counts as "in sunlight" for
# thrust-enable gating (electric propulsion pauses off battery-only power).
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


SSO_RAAN_DEG = raan_for_ltdn_deg(EPOCH_UTC, SSO_LTDN_HOURS)  # [deg]


# ---------------------------------------------------------------------------
# Satellite definitions consumed by run_constellation_mission.py
# ---------------------------------------------------------------------------
SATELLITES = [
    dict(
        name="SSO-1",
        role="sso",
        a_m=A_NOMINAL_M,
        e=SSO_ECC,
        i_deg=SSO_INCLINATION_DEG,
        raan_deg=SSO_RAAN_DEG,
        aop_deg=SSO_AOP_DEG,
        mean_anom_deg=0.0,  # [deg] phasing reference
    ),
    dict(
        name="SSO-2",
        role="sso",
        a_m=A_NOMINAL_M,
        e=SSO_ECC,
        i_deg=SSO_INCLINATION_DEG,
        raan_deg=SSO_RAAN_DEG,
        aop_deg=SSO_AOP_DEG,
        mean_anom_deg=180.0,  # [deg] 180 deg phased from SSO-1
    ),
    dict(
        name="MIDINC-1",
        role="midinc",
        a_m=A_NOMINAL_M,
        e=MIDINC_ECC,
        i_deg=MIDINC_INCLINATION_DEG,
        raan_deg=MIDINC_RAAN_DEG,
        aop_deg=MIDINC_AOP_DEG,
        mean_anom_deg=MIDINC_MEAN_ANOM_DEG,
    ),
]
