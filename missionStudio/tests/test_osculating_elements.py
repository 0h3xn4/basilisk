"""Tests for engine.service._osculating_elements -- specifically its
defensive NaN/inf guard, added after a real crash report.

Requires a Basilisk build (marked ``requires_basilisk``; see
tests/conftest.py for the auto-skip behavior in this development sandbox,
which does not have one) -- engine.service imports Basilisk at module
level.
"""

import numpy as np
import pytest

pytestmark = pytest.mark.requires_basilisk

_MU_EARTH = 3.986004418e14  # [m^3/s^2]


def _circular_rv(n=5):
    """n samples of a trivial circular orbit -- exact values don't
    matter, only that they're finite.
    """
    r = np.tile([7000e3, 0.0, 0.0], (n, 1))
    v = np.tile([0.0, 7500.0, 0.0], (n, 1))
    return r, v


def test_finite_samples_produce_normal_elements():
    from missionstudio.engine.service import _osculating_elements

    r, v = _circular_rv()
    elements = _osculating_elements(_MU_EARTH, r, v)
    assert np.all(np.isfinite(elements["a"]))
    assert np.all(elements["a"] > 0)


def test_nan_sample_raises_a_clear_error_not_an_attribute_error():
    """Regression test for a real crash report: a spacecraft's simulated
    state went non-physical (NaN) partway through a run, and
    orbitalMotion.rv2elem()'s own NaN-input guard (src/utilities/
    orbitalMotion.py) sets ClassicElements.AN/.AP, which aren't real
    slots on that class -- so instead of a clean NaN result, it crashed
    with "AttributeError: 'ClassicElements' object has no attribute
    'AN'", a confusing symptom of the actual problem (an unstable/
    diverged simulation). _osculating_elements must catch this itself,
    before ever calling rv2elem(), and report SOMETHING actionable.
    """
    from missionstudio.engine.service import SimulationServiceError, _osculating_elements

    r, v = _circular_rv(n=3)
    r[1] = [np.nan, 0.0, 0.0]  # the dynamics "went non-physical" partway through

    with pytest.raises(SimulationServiceError, match="non-physical"):
        _osculating_elements(_MU_EARTH, r, v)


def test_inf_sample_also_raises_the_clear_error():
    from missionstudio.engine.service import SimulationServiceError, _osculating_elements

    r, v = _circular_rv(n=3)
    v[2] = [0.0, np.inf, 0.0]

    with pytest.raises(SimulationServiceError, match="non-physical"):
        _osculating_elements(_MU_EARTH, r, v)
