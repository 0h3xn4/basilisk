"""Tests for missionstudio.engine.orbit_maintenance's VNB/RTN frame math
(_vnb_basis/_rtn_basis), used by ConstantFrameThrustController
(schema.scenario.ConstantThrustConfig). The whole module needs a Basilisk
build to import (its SysModel controller classes do), even though this
specific math is pure numpy -- see tests/conftest.py for the auto-skip
behavior in this development sandbox, which does not have one.
"""

import numpy as np
import pytest

pytestmark = pytest.mark.requires_basilisk


def test_vnb_basis_circular_equatorial_prograde_orbit():
    """Hand-computed reference case: r along +x, v along +y (circular,
    equatorial, prograde). Orbit normal is +z; V=[0,1,0]=v-hat by
    definition; N=[0,0,1]; B=V x N=[1,0,0], which for a circular orbit
    coincides with the radial direction.
    """
    from missionstudio.engine.orbit_maintenance import _vnb_basis

    r = np.array([7000000.0, 0.0, 0.0])
    v = np.array([0.0, 7500.0, 0.0])
    v_hat, n_hat, b_hat = _vnb_basis(r, v)
    assert np.allclose(v_hat, [0.0, 1.0, 0.0])
    assert np.allclose(n_hat, [0.0, 0.0, 1.0])
    assert np.allclose(b_hat, [1.0, 0.0, 0.0])


def test_rtn_basis_circular_equatorial_prograde_orbit():
    """Same reference case as above: R=r-hat=[1,0,0]; N=[0,0,1] (same
    orbit normal as VNB's); T=N x R=[0,1,0], which for a CIRCULAR orbit
    coincides with the velocity direction (not true in general for an
    eccentric orbit -- see _rtn_basis's docstring).
    """
    from missionstudio.engine.orbit_maintenance import _rtn_basis

    r = np.array([7000000.0, 0.0, 0.0])
    v = np.array([0.0, 7500.0, 0.0])
    r_hat, t_hat, n_hat = _rtn_basis(r, v)
    assert np.allclose(r_hat, [1.0, 0.0, 0.0])
    assert np.allclose(t_hat, [0.0, 1.0, 0.0])
    assert np.allclose(n_hat, [0.0, 0.0, 1.0])


@pytest.mark.parametrize("seed", range(5))
def test_vnb_and_rtn_bases_are_orthonormal_and_right_handed(seed):
    """General (non-hand-picked) check across several random orbit states:
    both bases must be orthonormal AND right-handed (axis1 x axis2 ==
    axis3), regardless of orbit shape/orientation.
    """
    from missionstudio.engine.orbit_maintenance import _rtn_basis, _vnb_basis

    rng = np.random.default_rng(seed)
    r = rng.uniform(-1.0e7, 1.0e7, size=3)
    v = rng.uniform(-8000.0, 8000.0, size=3)
    # Ensure r, v are not (near-)parallel -- orbit normal would be undefined.
    if np.linalg.norm(np.cross(r, v)) < 1.0:
        v = v + np.array([1000.0, 0.0, 0.0])

    for basis_fn in (_vnb_basis, _rtn_basis):
        a1, a2, a3 = basis_fn(r, v)
        for axis in (a1, a2, a3):
            assert np.isclose(np.linalg.norm(axis), 1.0)
        assert np.isclose(np.dot(a1, a2), 0.0, atol=1e-9)
        assert np.isclose(np.dot(a2, a3), 0.0, atol=1e-9)
        assert np.isclose(np.dot(a1, a3), 0.0, atol=1e-9)
        assert np.allclose(np.cross(a1, a2), a3, atol=1e-9)
