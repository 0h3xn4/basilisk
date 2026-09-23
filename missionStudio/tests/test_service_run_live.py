"""Tests for engine.service.SimulationService.run_live() -- the chunked
ExecuteSimulation() variant that streams intermediate ResultSets back via
an on_progress callback so gui.results_widget can show a live-updating
plot while a run is still in flight (see gui.run_worker.RunWorker's
``live`` flag and gui.main_window.MainWindow's "Live Plot" action).

Requires a Basilisk build (marked ``requires_basilisk``; see
tests/conftest.py for the auto-skip behavior in this development sandbox,
which does not have one).
"""

from pathlib import Path

import numpy as np
import pytest

from missionstudio.schema import load_scenario

pytestmark = pytest.mark.requires_basilisk

SCENARIO_PATH = Path(__file__).resolve().parent.parent / "missionstudio" / "scenarios" / "two_body_validation.json"


def test_run_live_reports_progress_and_matches_run():
    from missionstudio.engine.service import SimulationService

    scenario = load_scenario(SCENARIO_PATH)
    sc_name = scenario.spacecraft[0].name

    calls = []
    live_service = SimulationService(load_scenario(SCENARIO_PATH))
    live_result = live_service.run_live(lambda partial, fraction: calls.append((partial, fraction)))

    assert len(calls) > 1, "expected more than one chunk over the scenario's duration"

    fractions = [fraction for _, fraction in calls]
    assert fractions == sorted(fractions), "fraction_complete must never go backwards"
    assert fractions[-1] == 1.0
    assert all(0.0 < f <= 1.0 for f in fractions)

    # Series names are fixed from the very first callback -- only the
    # amount of data grows.
    first_partial, _ = calls[0]
    assert set(first_partial.series) == set(live_result.series)

    # Each chunk's data is a strict, growing prefix in time of the final
    # result -- never fewer nor more series, monotonically more samples.
    sample_counts = [len(partial.series[f"{sc_name}.position_N"].time_s) for partial, _ in calls]
    assert sample_counts == sorted(sample_counts)
    assert sample_counts[-1] == len(live_result.series[f"{sc_name}.position_N"].time_s)

    # Running in chunks must not change the actual simulated dynamics --
    # same integrator, same fixed task rate, only the outer stop time
    # differs -- so the final result must match a plain, single-shot run()
    # on an identical scenario exactly.
    plain_service = SimulationService(load_scenario(SCENARIO_PATH))
    plain_result = plain_service.run()

    live_pos = live_result.series[f"{sc_name}.position_N"]
    plain_pos = plain_result.series[f"{sc_name}.position_N"]
    assert np.array_equal(live_pos.time_s, plain_pos.time_s)
    assert np.array_equal(live_pos.data, plain_pos.data)


def test_run_live_honors_explicit_step():
    from missionstudio.engine.service import SimulationService

    scenario = load_scenario(SCENARIO_PATH)
    duration_s = scenario.sim_settings.duration_days * 86400.0

    calls = []
    service = SimulationService(scenario)
    service.run_live(lambda partial, fraction: calls.append(fraction), live_step_s=duration_s / 4.0)

    # ~4 chunks requested -> expect roughly that many callbacks (exact
    # count depends on how the dynamics task rate divides the duration,
    # since a chunk can never be shorter than one task tick).
    assert 3 <= len(calls) <= 6
    assert calls[-1] == 1.0
