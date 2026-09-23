"""Tests for missionstudio.engine.propellant_bookkeeping.apply_propellant_burn
-- pure numpy/math, no Basilisk import, so (unlike
tests/test_orbit_maintenance.py's SysModel controllers) these run in any
sandbox, with or without a Basilisk build.

Includes permanent regression coverage for the audit-found bug this module
fixes: StationKeepingController/PhasingKeepingController/
ConstantFrameThrustController used to each recompute an ABSOLUTE
``hub.mHub = dryMass + propellant`` every tick, so whichever controller's
UpdateState ran last each tick would silently discard mass contributions
from (a) another mass-tracking controller on the same spacecraft, or (b) a
Monte Carlo dry_mass_kg dispersion applied before any controller ever runs.
apply_propellant_burn's delta-based approach fixes both.
"""

from missionstudio.engine.propellant_bookkeeping import apply_propellant_burn


def test_no_op_when_thrust_is_zero():
    new_mass, new_propellant, burned_kg, mdot = apply_propellant_burn(
        current_total_mass_kg=100.0, propellant_kg=10.0, thrust_n=0.0,
        isp_s=220.0, dt_s=1.0)
    assert new_mass == 100.0
    assert new_propellant == 10.0
    assert burned_kg == 0.0
    assert mdot == 0.0


def test_no_op_when_propellant_already_exhausted():
    new_mass, new_propellant, burned_kg, mdot = apply_propellant_burn(
        current_total_mass_kg=90.0, propellant_kg=0.0, thrust_n=1.0,
        isp_s=220.0, dt_s=1.0)
    assert new_mass == 90.0
    assert new_propellant == 0.0
    assert burned_kg == 0.0
    assert mdot == 0.0


def test_normal_burn_applies_rocket_equation_delta():
    isp_s = 220.0
    g0 = 9.80665
    thrust_n = 1.0
    dt_s = 10.0
    expected_mdot = thrust_n / (isp_s * g0)  # [kg/s]
    expected_burned = expected_mdot * dt_s  # [kg]

    new_mass, new_propellant, burned_kg, mdot = apply_propellant_burn(
        current_total_mass_kg=100.0, propellant_kg=5.0, thrust_n=thrust_n,
        isp_s=isp_s, dt_s=dt_s, g0_mps2=g0)

    assert mdot == expected_mdot
    assert burned_kg == expected_burned
    assert new_propellant == 5.0 - expected_burned
    assert new_mass == 100.0 - expected_burned


def test_burn_is_clamped_to_remaining_propellant():
    # thrust/isp/dt imply far more burned mass than is actually left.
    new_mass, new_propellant, burned_kg, mdot = apply_propellant_burn(
        current_total_mass_kg=100.0, propellant_kg=0.001, thrust_n=50.0,
        isp_s=100.0, dt_s=100.0)
    assert burned_kg == 0.001
    assert new_propellant == 0.0
    assert new_mass == 100.0 - 0.001
    assert mdot > 0.0  # unclamped rate is still reported


def test_delta_composes_across_two_controllers_sharing_a_spacecraft():
    """Regression test for audit finding 1: two independent controllers
    (e.g. station_keeping + constant_thrust) on the same spacecraft must
    both see their propellant burn reflected in the final hub.mHub, no
    matter which one's UpdateState runs last this tick.
    """
    total_mass = 104.0  # [kg] dry + both tanks' propellant
    propellant_a = 2.0  # [kg]
    propellant_b = 2.0  # [kg]

    # Controller A burns first, using the mass at the top of the tick.
    total_mass, propellant_a, burned_a, _ = apply_propellant_burn(
        total_mass, propellant_a, thrust_n=1.0, isp_s=220.0, dt_s=1.0)
    # Controller B burns next, reading the mass A just updated.
    total_mass, propellant_b, burned_b, _ = apply_propellant_burn(
        total_mass, propellant_b, thrust_n=1.0, isp_s=220.0, dt_s=1.0)

    assert burned_a > 0.0
    assert burned_b > 0.0
    assert total_mass == 104.0 - burned_a - burned_b


def test_delta_preserves_a_prior_dry_mass_dispersion():
    """Regression test for audit finding 2: a Monte Carlo dry_mass_kg
    dispersion writes directly to hub.mHub before any controller's first
    tick. apply_propellant_burn must burn a delta off of that dispersed
    value, not silently reset it back to the nominal dry mass.
    """
    nominal_dry_mass = 100.0  # [kg]
    dispersed_dry_mass = 108.0  # [kg] Monte Carlo dispersion applied before Reset()/first tick
    propellant = 2.0  # [kg]

    new_mass, new_propellant, burned_kg, _ = apply_propellant_burn(
        dispersed_dry_mass + propellant, propellant, thrust_n=1.0,
        isp_s=220.0, dt_s=1.0)

    assert burned_kg > 0.0
    # The dispersion offset (+8 kg relative to nominal) must survive the tick.
    assert new_mass == (dispersed_dry_mass + propellant) - burned_kg
    assert new_mass != (nominal_dry_mass + new_propellant)
