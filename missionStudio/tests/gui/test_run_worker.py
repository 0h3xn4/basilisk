"""Tests for gui.run_worker.RunWorker.

Genuinely exercises the no-Basilisk path in this development sandbox
through a real background QThread (see test_kernel_status_widget.py's
docstring for the same point about kernel status).
"""

import importlib.util

import pytest

pytestmark = pytest.mark.requires_gui

_BASILISK_AVAILABLE = importlib.util.find_spec("Basilisk") is not None


def _load_two_body_scenario():
    from pathlib import Path

    from missionstudio.schema import load_scenario

    path = Path(__file__).resolve().parent.parent.parent / "missionstudio" / "scenarios" / "two_body_validation.json"
    return load_scenario(path)


@pytest.mark.skipif(_BASILISK_AVAILABLE, reason="this test's premise is specifically that Basilisk is unavailable")
def test_run_without_basilisk_emits_failed(qtbot):
    from missionstudio.gui.run_worker import RunWorker

    worker = RunWorker(_load_two_body_scenario())
    with qtbot.waitSignal(worker.failed, timeout=5000) as blocker:
        worker.start()
    assert "Basilisk is not installed" in blocker.args[0]


@pytest.mark.skipif(_BASILISK_AVAILABLE, reason="this test's premise is specifically that Basilisk is unavailable")
def test_monte_carlo_worker_without_basilisk_emits_failed(qtbot, tmp_path):
    from missionstudio.gui.run_worker import MonteCarloWorker
    from missionstudio.schema.scenario import MonteCarloConfig

    scenario = _load_two_body_scenario()
    mc_config = MonteCarloConfig(enabled=True, num_runs=2)
    worker = MonteCarloWorker(scenario, mc_config, tmp_path / "mc")
    with qtbot.waitSignal(worker.failed, timeout=5000) as blocker:
        worker.start()
    assert "Basilisk is not installed" in blocker.args[0]
