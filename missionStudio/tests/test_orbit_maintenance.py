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


# -- Non-finite/degenerate spacecraft state must never reach
# engine.orbital_geometry.argument_of_latitude()'s np.cross/np.arctan2
# math from inside UpdateState() -----------------------
#
# Real crash report: a formation-flying scenario (station_keeping +
# phasing_keeping) crashed with two DIFFERENT native signatures on
# different runs ("basic_string::_M_create", "std::bad_alloc") -- the
# classic symptom of memory corruption, not a deterministic failure.
# UpdateState() used to compute its along-track phase error via
# orbitalMotion.rv2elem() (see engine.orbital_geometry.
# argument_of_latitude's own docstring for why that was replaced -- a
# genuine numerical-instability bug for near-circular orbits, found and
# fixed separately from this guard); this guard predates that fix and is
# unrelated to it -- a non-finite state was never safe input to feed ANY
# per-tick math here, regardless of which formula computes the phase
# error. These tests confirm UpdateState() never reaches that math with
# non-finite input in the first place.

def _write_sc_state(msg, r_bn_n, v_bn_n, time_ns=0):
    from Basilisk.architecture import messaging

    payload = messaging.SCStatesMsgPayload()
    payload.r_BN_N = list(r_bn_n)
    payload.v_BN_N = list(v_bn_n)
    msg.write(payload, time_ns, -1)


def _flat(vec3) -> list:
    """extForce_N read back from a real ExtForceTorque as a nested
    [[x], [y], [z]] column-vector shape (confirmed against a real
    Basilisk build -- not the flat [x, y, z] list it's assigned as, via
    forceVec.tolist()), rather than guess at exactly which SWIG
    Eigen-vector property shapes do this and which don't.
    """
    return list(np.asarray(vec3).flatten())


def test_station_keeping_skips_thrust_on_nan_state():
    from Basilisk.architecture import messaging
    from Basilisk.simulation import extForceTorque

    from missionstudio.engine.orbit_maintenance import StationKeepingController

    controller = StationKeepingController(
        name="sk", mu=3.986004418e14, nominal_alt_m=550e3, deadband_m=2e3, r_planet_m=6378137.0,
        thrust_n=0.05, isp_s=1500.0, dry_mass_kg=400.0, propellant_kg=5.0,
    )
    controller.extForceEffector = extForceTorque.ExtForceTorque()
    sc_state_msg = messaging.SCStatesMsg()
    _write_sc_state(sc_state_msg, [np.nan, 0.0, 0.0], [0.0, 7500.0, 0.0])
    controller.scStateInMsg.subscribeTo(sc_state_msg)
    controller.Reset(0)

    controller.UpdateState(0)  # must not raise

    assert _flat(controller.extForceEffector.extForce_N) == [0.0, 0.0, 0.0]
    assert controller.burnLog[-1] == 0
    assert np.isnan(controller.altLog[-1])


def test_station_keeping_skips_thrust_on_zero_velocity():
    """A separate degenerate case from NaN -- np.linalg.norm(vVec) below
    would otherwise divide by zero when computing the thrust direction.
    """
    from Basilisk.architecture import messaging
    from Basilisk.simulation import extForceTorque

    from missionstudio.engine.orbit_maintenance import StationKeepingController

    controller = StationKeepingController(
        name="sk", mu=3.986004418e14, nominal_alt_m=550e3, deadband_m=2e3, r_planet_m=6378137.0,
        thrust_n=0.05, isp_s=1500.0, dry_mass_kg=400.0, propellant_kg=5.0,
    )
    controller.extForceEffector = extForceTorque.ExtForceTorque()
    sc_state_msg = messaging.SCStatesMsg()
    _write_sc_state(sc_state_msg, [7000e3, 0.0, 0.0], [0.0, 0.0, 0.0])
    controller.scStateInMsg.subscribeTo(sc_state_msg)
    controller.Reset(0)

    controller.UpdateState(0)  # must not raise

    assert _flat(controller.extForceEffector.extForce_N) == [0.0, 0.0, 0.0]


def test_phasing_keeping_skips_thrust_on_nan_state():
    from Basilisk.architecture import messaging
    from Basilisk.simulation import extForceTorque

    from missionstudio.engine.orbit_maintenance import PhasingKeepingController, SeparationSchedule

    controller = PhasingKeepingController(
        name="pk", mu=3.986004418e14, nominal_a_m=6928e3,
        separation_schedule=SeparationSchedule(distances_km=[50.0], interval_days=0.0, semi_major_axis_m=6928e3),
        tolerance_fraction=0.1, restore_tolerance_fraction=0.5, correction_window_days=1.0,
        max_drift_days=5.0, max_delta_a_m=1000.0, thrust_n=0.05, isp_s=1500.0, dry_mass_kg=400.0,
    )
    controller.extForceEffectorB = extForceTorque.ExtForceTorque()
    state_a = messaging.SCStatesMsg()
    state_b = messaging.SCStatesMsg()
    _write_sc_state(state_a, [7000e3, 0.0, 0.0], [0.0, 7500.0, 0.0])
    _write_sc_state(state_b, [np.nan, np.nan, np.nan], [np.nan, np.nan, np.nan])
    controller.scStateInMsgA.subscribeTo(state_a)
    controller.scStateInMsgB.subscribeTo(state_b)
    controller.Reset(0)

    controller.UpdateState(0)  # must not raise -- would otherwise feed NaN into argument_of_latitude()

    assert _flat(controller.extForceEffectorB.extForce_N) == [0.0, 0.0, 0.0]
    assert np.isnan(controller.errorDegLog[-1])


def test_phasing_keeping_runs_normally_with_finite_state():
    """Confirms the new guard doesn't change behavior for the ordinary,
    finite-state case -- the state machine still runs its normal IDLE
    logic (with a huge starting error, immediately transitions to
    BURN_OUT).
    """
    from Basilisk.architecture import messaging
    from Basilisk.simulation import extForceTorque

    from missionstudio.engine.orbit_maintenance import PhasingKeepingController, SeparationSchedule

    controller = PhasingKeepingController(
        name="pk", mu=3.986004418e14, nominal_a_m=6928e3,
        separation_schedule=SeparationSchedule(distances_km=[50.0], interval_days=0.0, semi_major_axis_m=6928e3),
        tolerance_fraction=0.1, restore_tolerance_fraction=0.5, correction_window_days=1.0,
        max_drift_days=5.0, max_delta_a_m=1000.0, thrust_n=0.05, isp_s=1500.0, dry_mass_kg=400.0,
    )
    controller.extForceEffectorB = extForceTorque.ExtForceTorque()
    state_a = messaging.SCStatesMsg()
    state_b = messaging.SCStatesMsg()
    _write_sc_state(state_a, [7000e3, 0.0, 0.0], [0.0, 7500.0, 0.0])
    _write_sc_state(state_b, [0.0, 7000e3, 0.0], [-7500.0, 0.0, 0.0])
    controller.scStateInMsgA.subscribeTo(state_a)
    controller.scStateInMsgB.subscribeTo(state_b)
    controller.Reset(0)

    controller.UpdateState(0)

    # The exact control-law numerics aren't what this test is about (see
    # the *_skips_thrust_on_nan_state tests above for that) -- only that
    # the new guard doesn't block the ordinary, finite-state path from
    # running its real logic and logging a real (non-placeholder) value.
    assert not np.isnan(controller.errorDegLog[-1])
    assert len(controller.tLog) == 1
