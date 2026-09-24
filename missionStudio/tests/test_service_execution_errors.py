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


def test_log_last_known_state_with_no_samples_does_not_raise(caplog):
    """The diagnostic that runs right before raise_clear_execution_error --
    see its own docstring on service.SimulationService.log_last_known_state
    -- must be safe to call even before a single dynamics tick has ever
    completed (build() alone, no ExecuteSimulation() at all yet): a
    diagnostic that itself crashes would mask the real error it exists to
    help explain.
    """
    import logging

    from missionstudio.engine.service import SimulationService

    service = SimulationService(load_scenario(SCENARIO_PATH))
    service.build()

    with caplog.at_level(logging.ERROR, logger="missionstudio.engine.service"):
        service.log_last_known_state()  # must not raise

    assert "no samples recorded yet" in caplog.text


def test_log_last_known_state_reports_the_last_real_sample(caplog):
    """After some real dynamics ticks have actually run, the diagnostic
    must report an actual r_BN_N/v_BN_N sample (not just the
    no-samples-yet fallback) -- this is the whole point: the exact
    position/velocity right before a later failure, for the user's next
    crash report.
    """
    import logging

    from missionstudio.engine.service import SimulationService

    scenario = load_scenario(SCENARIO_PATH)
    service = SimulationService(scenario)
    service.build()
    step_s = scenario.sim_settings.dynamics_task_rate_s * 5
    service.scSim.ConfigureStopTime(int(step_s * 1e9))
    service.scSim.ExecuteSimulation()

    with caplog.at_level(logging.ERROR, logger="missionstudio.engine.service"):
        service.log_last_known_state()

    assert "last recorded state before failure" in caplog.text
    assert "r_BN_N=" in caplog.text
    assert "v_BN_N=" in caplog.text
