"""The end-to-end validation scenario required before this tool is
trusted for anything else: propagate a single spacecraft under Earth
point-mass gravity only (no perturbations) and check the result against
an INDEPENDENT analytical two-body (Kepler) solution, plus the two
fundamental conserved quantities of the unperturbed two-body problem
(specific orbital energy and angular momentum).

"Independent" here specifically means: the analytical reference state at
each sample time is built by solving Kepler's equation directly
(``orbitalMotion.M2E``/``E2f``/``elem2rv``), a completely different code
path from the numerical ODE integration
(``svIntegratorRKF78`` + ``gravityEffector``) that
``engine.service.SimulationService`` actually exercises -- this is not a
tautological "compare the propagator against itself" check.

Requires a Basilisk build (marked ``requires_basilisk``; see
``tests/conftest.py`` for the auto-skip behavior in this development
sandbox, which does not have one).
"""

from pathlib import Path

import numpy as np
import pytest

from missionstudio.schema import load_scenario

pytestmark = pytest.mark.requires_basilisk

SCENARIO_PATH = Path(__file__).resolve().parent.parent / "missionstudio" / "scenarios" / "two_body_validation.json"

# Tolerances: RKF78 is a high-order adaptive integrator on a smooth,
# unperturbed two-body force field, so agreement with the closed-form
# Kepler solution should be extremely tight -- these are deliberately
# generous relative to what's actually expected (sub-meter/sub-mm-per-s is
# typical for this kind of test), so a failure here means a real bug, not
# integrator tuning noise.
POSITION_TOL_M = 10.0
VELOCITY_TOL_M_S = 0.01
ENERGY_REL_TOL = 1e-8
ANGULAR_MOMENTUM_REL_TOL = 1e-8


def _analytical_state_at(mu, oe0, elapsed_s):
    """Kepler-propagate classical elements ``oe0`` forward by ``elapsed_s``
    (mean anomaly advances linearly for an unperturbed two-body orbit) and
    return (r_N, v_N) [m], [m/s] -- the independent analytical reference.
    """
    from Basilisk.utilities import orbitalMotion as om

    n = np.sqrt(mu / oe0.a ** 3)  # [rad/s] mean motion
    E0 = om.f2E(oe0.f, oe0.e)
    M0 = om.E2M(E0, oe0.e)
    M = M0 + n * elapsed_s

    oe = om.ClassicElements()
    oe.a, oe.e, oe.i, oe.Omega, oe.omega = oe0.a, oe0.e, oe0.i, oe0.Omega, oe0.omega
    E = om.M2E(M, oe0.e)
    oe.f = om.E2f(E, oe0.e)
    return om.elem2rv(mu, oe)


def test_two_body_propagation_matches_analytical_kepler_solution():
    from missionstudio.engine.service import SimulationService
    from Basilisk.utilities import orbitalMotion as om

    scenario = load_scenario(SCENARIO_PATH)
    service = SimulationService(scenario)
    result = service.run()

    sc_name = scenario.spacecraft[0].name
    pos = result.series[f"{sc_name}.position_N"]
    vel = result.series[f"{sc_name}.velocity_N"]
    assert len(pos.time_s) > 10, "expected many recorded samples over the scenario duration"

    mu = service.mu
    orbit = scenario.spacecraft[0].orbit
    oe0 = om.ClassicElements()
    oe0.a = orbit.semi_major_axis_km * 1000.0
    oe0.e = orbit.eccentricity
    oe0.i = np.radians(orbit.inclination_deg)
    oe0.Omega = np.radians(orbit.raan_deg)
    oe0.omega = np.radians(orbit.arg_periapsis_deg)
    oe0.f = np.radians(orbit.true_anomaly_deg)

    max_pos_err, max_vel_err = 0.0, 0.0
    for i, t in enumerate(pos.time_s):
        r_analytical, v_analytical = _analytical_state_at(mu, oe0, float(t))
        pos_err = np.linalg.norm(pos.data[i] - np.array(r_analytical))
        vel_err = np.linalg.norm(vel.data[i] - np.array(v_analytical))
        max_pos_err = max(max_pos_err, pos_err)
        max_vel_err = max(max_vel_err, vel_err)

    assert max_pos_err < POSITION_TOL_M, (
        f"propagated position diverged from the analytical Kepler solution by up to "
        f"{max_pos_err:.3f} m (tolerance {POSITION_TOL_M} m)"
    )
    assert max_vel_err < VELOCITY_TOL_M_S, (
        f"propagated velocity diverged from the analytical Kepler solution by up to "
        f"{max_vel_err:.6f} m/s (tolerance {VELOCITY_TOL_M_S} m/s)"
    )


def test_two_body_propagation_conserves_energy_and_angular_momentum():
    from missionstudio.engine.service import SimulationService

    scenario = load_scenario(SCENARIO_PATH)
    service = SimulationService(scenario)
    result = service.run()

    sc_name = scenario.spacecraft[0].name
    pos = result.series[f"{sc_name}.position_N"].data
    vel = result.series[f"{sc_name}.velocity_N"].data
    mu = service.mu

    r_mag = np.linalg.norm(pos, axis=1)
    v_mag = np.linalg.norm(vel, axis=1)
    specific_energy = 0.5 * v_mag ** 2 - mu / r_mag  # [J/kg]
    angular_momentum = np.linalg.norm(np.cross(pos, vel), axis=1)  # [m^2/s]

    energy_rel_spread = (specific_energy.max() - specific_energy.min()) / abs(specific_energy[0])
    h_rel_spread = (angular_momentum.max() - angular_momentum.min()) / angular_momentum[0]

    assert energy_rel_spread < ENERGY_REL_TOL, (
        f"specific orbital energy varied by a relative {energy_rel_spread:.2e} over the run "
        f"(tolerance {ENERGY_REL_TOL:.0e}) -- should be conserved to numerical precision for an "
        f"unperturbed two-body orbit"
    )
    assert h_rel_spread < ANGULAR_MOMENTUM_REL_TOL, (
        f"angular momentum magnitude varied by a relative {h_rel_spread:.2e} over the run "
        f"(tolerance {ANGULAR_MOMENTUM_REL_TOL:.0e})"
    )
