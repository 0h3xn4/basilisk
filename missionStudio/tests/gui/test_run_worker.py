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
def test_live_run_without_basilisk_emits_failed(qtbot):
    """The live=True path fails the same way as live=False -- the
    ImportError happens before either run()/run_live() is ever reached
    (see RunWorker.run()'s try block).
    """
    from missionstudio.gui.run_worker import RunWorker

    worker = RunWorker(_load_two_body_scenario(), live=True)
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


# -- RunWorker's dispatch/cancellation logic, via a faked engine.service/
# engine.mission_engine (installed into sys.modules before RunWorker.run()'s
# own lazy `from ..engine.service import ...` executes) rather than a real
# Basilisk build -- runs on any machine, with or without Basilisk actually
# installed, unlike the ImportError-path tests above. See run_worker.py's
# own module docstring for the "abort a running simulation" feature this
# is testing the plumbing for.

class _FakeResultSet:
    def __init__(self, series=None):
        self.series = series if series is not None else {"sat-1.position_N": object()}


class _FakeSimulationCancelled(Exception):
    def __init__(self, partial_result):
        super().__init__("cancelled")
        self.partial_result = partial_result


class _FakeMissionEngineCancelled(Exception):
    def __init__(self, partial_result, summary):
        super().__init__("cancelled")
        self.partial_result = partial_result
        self.summary = summary


def _install_fake_engine_service(monkeypatch, run_live_impl):
    import sys
    import types

    class FakeSimulationService:
        def __init__(self, scenario, vizard_request=None):
            self.scenario = scenario
            self.vizard_request = vizard_request

        def run_live(self, on_progress, should_cancel=None):
            return run_live_impl(self, on_progress, should_cancel)

    fake_module = types.ModuleType("missionstudio.engine.service")
    fake_module.SimulationService = FakeSimulationService
    fake_module.SimulationCancelled = _FakeSimulationCancelled
    monkeypatch.setitem(sys.modules, "missionstudio.engine.service", fake_module)
    return fake_module


def _install_fake_mission_engine(monkeypatch, run_impl):
    import sys
    import types

    class FakeMissionEngine:
        def __init__(self, scenario, service=None, should_cancel=None):
            self.scenario = scenario
            self.service = service
            self.should_cancel = should_cancel

        def run(self):
            return run_impl(self)

    fake_module = types.ModuleType("missionstudio.engine.mission_engine")
    fake_module.MissionEngine = FakeMissionEngine
    fake_module.MissionEngineCancelled = _FakeMissionEngineCancelled
    monkeypatch.setitem(sys.modules, "missionstudio.engine.mission_engine", fake_module)
    return fake_module


def test_run_always_uses_run_live_and_passes_should_cancel(qtbot, monkeypatch):
    """Confirms the non-mission_sequence path is always chunked via
    run_live() now (for cancellability), regardless of live=False -- see
    this module's own docstring on why.
    """
    from missionstudio.gui.run_worker import RunWorker

    calls = {}

    def run_live_impl(service, on_progress, should_cancel):
        calls["should_cancel"] = should_cancel
        on_progress(_FakeResultSet(), 0.5)
        on_progress(_FakeResultSet(), 1.0)
        return _FakeResultSet()

    _install_fake_engine_service(monkeypatch, run_live_impl)
    worker = RunWorker(_load_two_body_scenario(), live=False)

    with qtbot.waitSignal(worker.finished_ok, timeout=5000):
        worker.start()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)

    # Bound methods aren't singletons (worker._should_cancel is
    # worker._should_cancel is False in general), so compare what it's
    # bound to/backed by instead of object identity.
    assert calls["should_cancel"].__self__ is worker
    assert calls["should_cancel"].__func__ is type(worker)._should_cancel


def test_live_false_never_emits_progress(qtbot, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    def run_live_impl(service, on_progress, should_cancel):
        on_progress(_FakeResultSet(), 0.5)
        on_progress(_FakeResultSet(), 1.0)
        return _FakeResultSet()

    _install_fake_engine_service(monkeypatch, run_live_impl)
    worker = RunWorker(_load_two_body_scenario(), live=False)
    progress_calls = []
    worker.progress.connect(lambda *a: progress_calls.append(a))

    with qtbot.waitSignal(worker.finished_ok, timeout=5000):
        worker.start()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)

    assert progress_calls == []


def test_live_true_emits_progress(qtbot, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    def run_live_impl(service, on_progress, should_cancel):
        on_progress(_FakeResultSet(), 0.5)
        on_progress(_FakeResultSet(), 1.0)
        return _FakeResultSet()

    _install_fake_engine_service(monkeypatch, run_live_impl)
    worker = RunWorker(_load_two_body_scenario(), live=True)
    progress_calls = []
    worker.progress.connect(lambda *a: progress_calls.append(a))

    with qtbot.waitSignal(worker.finished_ok, timeout=5000):
        worker.start()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)

    assert len(progress_calls) == 2


def test_request_cancel_makes_should_cancel_true(qtbot, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    seen = []

    def run_live_impl(service, on_progress, should_cancel):
        seen.append(should_cancel())
        return _FakeResultSet()

    _install_fake_engine_service(monkeypatch, run_live_impl)
    worker = RunWorker(_load_two_body_scenario())
    assert worker._should_cancel() is False
    worker.request_cancel()
    assert worker._should_cancel() is True

    with qtbot.waitSignal(worker.finished_ok, timeout=5000):
        worker.start()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)
    assert seen == [True]


def test_simulation_cancelled_emits_cancelled_signal_with_partial_result(qtbot, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    partial = _FakeResultSet()

    def run_live_impl(service, on_progress, should_cancel):
        on_progress(partial, 0.3)
        raise _FakeSimulationCancelled(partial)

    _install_fake_engine_service(monkeypatch, run_live_impl)
    worker = RunWorker(_load_two_body_scenario())

    with qtbot.waitSignal(worker.cancelled, timeout=5000) as blocker:
        worker.start()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)

    assert blocker.args == [partial, None]


def test_mission_sequence_dispatch_passes_should_cancel_to_mission_engine(qtbot, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    from missionstudio.schema.command import Command

    calls = {}

    def run_impl(engine):
        calls["should_cancel"] = engine.should_cancel
        return _FakeResultSet(), object()

    _install_fake_engine_service(monkeypatch, lambda *a: (_ for _ in ()).throw(AssertionError("should not be called")))
    _install_fake_mission_engine(monkeypatch, run_impl)

    scenario = _load_two_body_scenario()
    scenario.mission_sequence = [Command(kind="script_block", params={"code": "pass"})]
    worker = RunWorker(scenario)

    with qtbot.waitSignal(worker.finished_ok, timeout=5000):
        worker.start()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)

    # Bound methods aren't singletons (worker._should_cancel is
    # worker._should_cancel is False in general), so compare what it's
    # bound to/backed by instead of object identity.
    assert calls["should_cancel"].__self__ is worker
    assert calls["should_cancel"].__func__ is type(worker)._should_cancel


def test_mission_engine_cancelled_emits_cancelled_signal_with_partial_result_and_summary(qtbot, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    from missionstudio.schema.command import Command

    partial = _FakeResultSet()
    summary = object()

    def run_impl(engine):
        raise _FakeMissionEngineCancelled(partial, summary)

    _install_fake_engine_service(monkeypatch, lambda *a: (_ for _ in ()).throw(AssertionError("should not be called")))
    _install_fake_mission_engine(monkeypatch, run_impl)

    scenario = _load_two_body_scenario()
    scenario.mission_sequence = [Command(kind="script_block", params={"code": "pass"})]
    worker = RunWorker(scenario)

    with qtbot.waitSignal(worker.cancelled, timeout=5000) as blocker:
        worker.start()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)

    assert blocker.args == [partial, summary]


