"""Tests for engine.service.raise_clear_execution_error and its wiring
into SimulationService.run()/run_live() -- the fix for a real crash a
user hit twice on the same template scenario: ExecuteSimulation()
failing with a bare ``RuntimeError: std::bad_alloc`` (or
``basic_string::_M_create``), with no explanation anywhere. See
raise_clear_execution_error's own docstring for the root cause (a NaN
state defeats Basilisk's adaptive integrator's step-acceptance check,
which then loops forever reallocating memory) found by reading Basilisk's
own C++ source.

Requires a Basilisk build (marked ``requires_basilisk``; see
tests/conftest.py) to construct a real SimulationService/scSim -- the
RuntimeError itself is injected via monkeypatch rather than actually
triggering the underlying integrator bug (reproducing that for real would
need a genuinely diverging trajectory, which isn't a reliable thing to
build a fast unit test around).
"""

from pathlib import Path

import pytest

from missionstudio.schema import load_scenario

pytestmark = pytest.mark.requires_basilisk

SCENARIO_PATH = Path(__file__).resolve().parent.parent / "missionstudio" / "scenarios" / "two_body_validation.json"


def test_raise_clear_execution_error_wraps_with_actionable_message():
    from missionstudio.engine.service import SimulationServiceError, raise_clear_execution_error

    original = RuntimeError("std::bad_alloc")
    with pytest.raises(SimulationServiceError) as exc_info:
        raise_clear_execution_error(original)

    message = str(exc_info.value)
    assert "std::bad_alloc" in message
    assert "non-physical" in message
    assert exc_info.value.__cause__ is original


def test_run_translates_execute_simulation_runtime_error(monkeypatch):
    from missionstudio.engine.service import SimulationService, SimulationServiceError

    service = SimulationService(load_scenario(SCENARIO_PATH))
    service.build()

    def _boom():
        raise RuntimeError("std::bad_alloc")

    monkeypatch.setattr(service.scSim, "ExecuteSimulation", _boom)

    with pytest.raises(SimulationServiceError, match="non-physical"):
        service.run()


def test_run_live_translates_execute_simulation_runtime_error(monkeypatch):
    from missionstudio.engine.service import SimulationService, SimulationServiceError

    service = SimulationService(load_scenario(SCENARIO_PATH))
    service.build()

    def _boom():
        raise RuntimeError("basic_string::_M_create")

    monkeypatch.setattr(service.scSim, "ExecuteSimulation", _boom)

    with pytest.raises(SimulationServiceError, match="non-physical"):
        service.run_live(lambda partial, fraction: None)
