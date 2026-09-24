"""Tests for engine.orbital_geometry.argument_of_latitude -- see its own
module/function docstrings for the real crash investigation this exists
to fix: ``engine.orbit_maintenance.PhasingKeepingController`` used to
compute each spacecraft's along-track phase via
``orbitalMotion.rv2elem()`` -> mean anomaly, which is numerically UNSAFE
for near-circular orbits (this controller's whole use case) -- the
eccentricity vector's DIRECTION, which the argument-of-periapsis/true
-anomaly split is measured from, is only weakly constrained by the
dynamics once eccentricity is tiny.

No Basilisk dependency (pure ``numpy``), so these run unconditionally,
unlike most of this test suite -- exactly the point of factoring this out
of engine.orbit_maintenance (which cannot even be imported without a
Basilisk build).
"""

import numpy as np
import pytest

from missionstudio.engine.orbital_geometry import argument_of_latitude

MU_EARTH = 3.986004418e14  # [m^3/s^2]


def _circular_state(a_m: float, inclination_rad: float, true_longitude_rad: float):
    """A circular orbit's r/v at a given angle past the ascending node,
    for an orbit of semi-major axis ``a_m`` and inclination
    ``inclination_rad`` (RAAN fixed at 0 -- ascending node along +X).
    """
    v_circ = np.sqrt(MU_EARTH / a_m)
    # Position/velocity in the orbital plane, then rotated by inclination
    # about the (here, +X) node line.
    r_plane = a_m * np.array([np.cos(true_longitude_rad), np.sin(true_longitude_rad), 0.0])
    v_plane = v_circ * np.array([-np.sin(true_longitude_rad), np.cos(true_longitude_rad), 0.0])

    c, s = np.cos(inclination_rad), np.sin(inclination_rad)
    rot_x = np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
    return rot_x @ r_plane, rot_x @ v_plane


def _angle_diff_deg(a_rad: float, b_rad: float) -> float:
    diff = np.degrees(a_rad - b_rad)
    return float((diff + 180.0) % 360.0 - 180.0)


def test_matches_true_longitude_for_a_known_inclined_circular_orbit():
    """At the ascending node itself (true_longitude=0), the angle from
    +X projected into the plane is 0 by construction -- the simplest
    possible sanity check.
    """
    r, v = _circular_state(7000e3, np.radians(45.0), 0.0)
    u = argument_of_latitude(r, v)
    assert abs(np.degrees(u)) < 1e-6


def test_two_inclined_satellites_a_half_degree_apart_read_a_half_degree_apart():
    """Direct regression test for the actual bug: two co-planar,
    near-circular, inclined satellites a small angle apart must read
    back as being separated by (very close to) that same small angle --
    not tens of degrees of spurious noise, which is what the old
    rv2elem()-based mean-anomaly computation produced on a real Basilisk
    run's actual state (see this module's own docstring).
    """
    a_m = 6928e3
    inclination = np.radians(45.0)
    r_chief, v_chief = _circular_state(a_m, inclination, 0.0)
    r_follower, v_follower = _circular_state(a_m, inclination, np.radians(-0.5))

    u_chief = argument_of_latitude(r_chief, v_chief)
    u_follower = argument_of_latitude(r_follower, v_follower)

    assert _angle_diff_deg(u_follower, u_chief) == pytest.approx(-0.5, abs=1e-6)


def test_matches_true_longitude_for_an_equatorial_circular_orbit():
    """The ascending node itself is undefined for an equatorial orbit --
    this is the case the fixed-reference-projection approach exists to
    handle without a separate, similarly-fragile branch (see the
    function's own docstring on why Basilisk's own rv2elem() needs one).
    """
    r, v = _circular_state(7000e3, 0.0, np.radians(30.0))
    u = argument_of_latitude(r, v)
    assert np.degrees(u) == pytest.approx(30.0, abs=1e-6)


def test_two_equatorial_satellites_ninety_degrees_apart():
    """Matches the geometry of an existing engine.orbit_maintenance test
    fixture (test_phasing_keeping_runs_normally_with_finite_state):
    chief at (a, 0, 0)/(0, vCirc, 0), follower at (0, a, 0)/(-vCirc, 0, 0)
    -- both equatorial, 90 degrees apart.
    """
    a_m = 7000e3
    v_circ = np.sqrt(MU_EARTH / a_m)
    r_chief, v_chief = np.array([a_m, 0.0, 0.0]), np.array([0.0, v_circ, 0.0])
    r_follower, v_follower = np.array([0.0, a_m, 0.0]), np.array([-v_circ, 0.0, 0.0])

    u_chief = argument_of_latitude(r_chief, v_chief)
    u_follower = argument_of_latitude(r_follower, v_follower)

    assert _angle_diff_deg(u_follower, u_chief) == pytest.approx(90.0, abs=1e-6)


def test_a_slightly_eccentric_orbit_does_not_blow_up():
    """The whole point of avoiding the eccentricity-vector-based approach
    -- this must stay well-behaved (no huge jump) for an orbit with a
    small but non-machine-precision eccentricity, exactly the case that
    made orbitalMotion.rv2elem()'s argp/true-anomaly split numerically
    unstable in the first place (see this module's own docstring: even a
    tiny nonzero eccentricity is enough to destabilize that formula).
    """
    a_m = 6928e3
    e = 1e-6
    p = a_m * (1.0 - e ** 2)
    r_mag = p  # true anomaly = 0 (periapsis-ish direction, but e is tiny)
    r = np.array([r_mag, 0.0, 0.0])
    v_mag = np.sqrt(MU_EARTH * (2.0 / r_mag - 1.0 / a_m))
    v = np.array([0.0, v_mag, 0.0])

    u = argument_of_latitude(r, v)
    assert abs(np.degrees(u)) < 1.0  # near the reference direction, not tens of degrees off


def test_degenerate_zero_angular_momentum_returns_zero_not_nan():
    """A radial (straight-line) 'orbit' has no well-defined orbital plane
    -- must degrade to a finite fallback, matching this project's "never
    produce NaN, degrade instead" convention for a per-tick control-law
    input, rather than dividing by a near-zero norm.
    """
    r = np.array([7000e3, 0.0, 0.0])
    v = np.array([100.0, 0.0, 0.0])  # parallel to r -> zero angular momentum

    assert argument_of_latitude(r, v) == 0.0


def test_orbit_normal_nearly_parallel_to_primary_reference_axis():
    """An orbit whose normal is close to the primary (+X) reference
    direction -- must fall back to the secondary (+Z) reference rather
    than dividing by a near-zero in-plane projection of +X.
    """
    a_m = 7000e3
    h_hat = np.array([0.995, 0.0999, 0.0])  # ~94 degrees off +X -- triggers the >0.9 fallback
    h_hat = h_hat / np.linalg.norm(h_hat)
    r_dir = np.array([0.0, 0.0, 1.0]) - np.dot([0.0, 0.0, 1.0], h_hat) * h_hat
    r_dir = r_dir / np.linalg.norm(r_dir)
    r = a_m * r_dir
    v = np.sqrt(MU_EARTH / a_m) * np.cross(h_hat, r_dir)

    u = argument_of_latitude(r, v)
    assert np.isfinite(u)
