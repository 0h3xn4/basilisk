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

"""Pure orbital-geometry math (no Basilisk dependency), factored out of
``engine.orbit_maintenance`` so it can be unit-tested WITHOUT a Basilisk
build -- that module imports ``Basilisk.architecture``/``Basilisk.
simulation`` at module level (its ``SysModel`` controller classes need
them), which would otherwise make even this plain vector arithmetic
untestable in a development sandbox with no Basilisk build (see
``missionStudio/README.md``'s "Environment honesty note"). Same "pure
math, no Basilisk" split ``engine.propellant_bookkeeping``,
``engine.constellation``, and ``engine.spacecraft_templates`` already use
for the same reason.

This is the fix for a real crash investigation:
``PhasingKeepingController.UpdateState()`` used to compute each
spacecraft's along-track phase via ``orbitalMotion.rv2elem()`` -> mean
anomaly, which turned out to be numerically UNSAFE for this controller's
actual use case (co-planar, near-circular formation-keeping) -- see
:func:`argument_of_latitude`'s own docstring for the full mechanism,
confirmed by hand against a real Basilisk run's exact position/velocity.
"""

from __future__ import annotations

import numpy as np


def argument_of_latitude(r_vec, v_vec) -> float:
    """Along-track phase angle [rad], measured within the orbital plane
    from a fixed inertial reference direction, computed directly from
    r/v -- NOT via ``orbitalMotion.rv2elem()``'s eccentricity-vector
    -based argument-of-periapsis/true-anomaly split, which
    ``engine.orbit_maintenance.PhasingKeepingController`` used to go
    through until a real crash investigation found it numerically UNSAFE
    for near-circular formation-keeping (this function's whole reason to
    exist).

    Root cause, confirmed by hand against a real Basilisk run's exact
    r/v: for an orbit with even a tiny non-machine-precision
    eccentricity, the eccentricity vector's DIRECTION (what argp/true
    -anomaly are measured from) is only weakly constrained by the
    dynamics -- reproducing a real formation-flying scenario's actual
    chief/follower state through the unstable formula gave
    argument-of-periapsis values 160 vs 184 degrees apart for two
    spacecraft that are physically 0.5 degrees apart, a ~24 degree
    spurious "separation." Basilisk's own ``rv2elem()``
    (``src/utilities/orbitalMotion.py``) is aware of this and has a
    dedicated near-circular branch (``elements.e < 1e-11``) that avoids
    it by measuring from the ascending node instead -- but that branch is
    gated on eccentricity being below an extremely tight 1e-11 threshold,
    which ANY real perturbation (third-body gravity, or a controller's
    own commanded thrust) can push an initially-circular orbit above,
    silently falling back to the unstable branch.

    The fix here avoids BOTH the eccentricity-vector instability (never
    used at all) and the ascending-node's own degeneracy for a
    near-equatorial orbit (which Basilisk's rv2elem() handles with a
    SEPARATE branch, gated on a similarly fragile inclination threshold):
    project a fixed inertial reference direction into THIS orbit's own
    plane (whatever it is) and measure the angle from there. Only the
    orbit-NORMAL direction matters (always well-conditioned for any
    genuine, non-degenerate orbit -- no fragile eccentricity or
    inclination threshold to accidentally cross), and a caller comparing
    two co-planar (near-identical orbit-normal) spacecraft only ever
    needs the DIFFERENCE between their two angles, which does not depend
    on which fixed reference direction is chosen as long as it is applied
    consistently to both. Two candidate references 90 degrees apart (+X,
    +Z) so at least one is never near-parallel to the orbit normal (where
    its in-plane projection would itself become unstable).

    For a genuinely circular orbit, this angle IS the mean anomaly (both
    measure "where is the spacecraft" with no periapsis to distinguish it
    from).

    Args:
        r_vec: inertial position [m] (any 3-vector-like: list, tuple,
            ``np.ndarray``).
        v_vec: inertial velocity [m/s].

    Returns:
        The angle [rad], wrapped to ``(-pi, pi]`` by ``np.arctan2``.
        ``0.0`` for a degenerate (near-zero angular momentum) input
        rather than raising -- matching this project's "never produce
        NaN, degrade instead" convention for a per-tick control-law
        input that already has nothing physically useful to compute.
    """
    r_vec = np.asarray(r_vec, dtype=float)
    v_vec = np.asarray(v_vec, dtype=float)
    h_vec = np.cross(r_vec, v_vec)
    h_norm = np.linalg.norm(h_vec)
    if h_norm < 1e-6:
        return 0.0
    h_hat = h_vec / h_norm
    reference = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(reference, h_hat)) > 0.9:
        reference = np.array([0.0, 0.0, 1.0])
    x_in_plane = reference - np.dot(reference, h_hat) * h_hat
    x_hat = x_in_plane / np.linalg.norm(x_in_plane)
    y_hat = np.cross(h_hat, x_hat)  # completes the in-plane right-handed basis
    return float(np.arctan2(np.dot(r_vec, y_hat), np.dot(r_vec, x_hat)))
