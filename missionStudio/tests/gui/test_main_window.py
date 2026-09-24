"""Tests for gui.main_window.MainWindow -- the full File/Run workflow,
with QFileDialog/QMessageBox monkeypatched so nothing blocks on a real
modal dialog. The "Run" test below genuinely exercises the no-Basilisk
error path in this development sandbox (see test_run_worker.py).
"""

import importlib.util

import pytest

pytestmark = pytest.mark.requires_gui

_BASILISK_AVAILABLE = importlib.util.find_spec("Basilisk") is not None


@pytest.fixture
def window(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from missionstudio.gui.main_window import MainWindow

    # Safety net: qtbot.addWidget()'s teardown calls .close() on the
    # window, which -- for a test that leaves it dirty on purpose (e.g.
    # test_editing_marks_dirty) -- triggers the REAL, unmocked
    # unsaved-changes QMessageBox.question() prompt. In offscreen mode
    # nothing ever answers it, so teardown hangs forever. Default to
    # "Discard" here; any test that specifically exercises the close
    # -confirmation prompt overrides this with its own monkeypatch.setattr
    # call, which simply takes over for the rest of that test.
    monkeypatch.setattr(QMessageBox, "question",
                         staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard))

    w = MainWindow()
    qtbot.addWidget(w)
    return w


def _add_valid_spacecraft(window):
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig

    window.scenario_editor.spacecraft_list.from_list([
        SpacecraftConfig(name="sat-1", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]))
    ])
    window.scenario_editor.changed.emit()


def test_initial_title_is_untitled(window):
    assert window.windowTitle() == "missionStudio -- untitled"


def test_editing_marks_dirty(window):
    assert not window._dirty
    _add_valid_spacecraft(window)
    assert window._dirty
    assert window.windowTitle().endswith("*")


def test_save_as_then_open_round_trip(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    _add_valid_spacecraft(window)
    save_path = tmp_path / "test_scenario.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(save_path), "")))
    window.on_save_as()

    assert save_path.exists()
    assert not window._dirty
    assert window._current_path == save_path

    window.on_new()
    assert window._current_path is None
    assert window.scenario_editor.spacecraft_list.to_list() == []

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(save_path), "")))
    window.on_open()
    assert window._current_path == save_path
    assert window.scenario_editor.spacecraft_list.to_list()[0].name == "sat-1"


def test_save_with_invalid_scenario_shows_error_and_does_not_write(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    save_path = tmp_path / "invalid.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(save_path), "")))
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))

    window.on_save_as()  # no spacecraft yet -- invalid

    assert not save_path.exists()
    assert len(critical_calls) == 1


def test_open_missing_file_shows_error(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(missing), "")))
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))

    window.on_open()
    assert len(critical_calls) == 1
    assert window._current_path is None


def test_window_starts_on_load_scenario_tab(window):
    assert window.left_tabs.currentWidget() is window.load_scenario_widget


def test_choosing_a_template_opens_it_and_switches_to_editor_tab(window):
    from missionstudio.gui.load_scenario_widget import TEMPLATES_DIR

    template_path = sorted(TEMPLATES_DIR.glob("*.json"))[0]

    window.load_scenario_widget.path_chosen.emit(template_path)

    assert window._current_path == template_path
    assert window.left_tabs.currentWidget() is window.scenario_editor
    assert len(window.scenario_editor.spacecraft_list.to_list()) >= 1


def test_choosing_a_template_with_unsaved_changes_prompts_first(window, monkeypatch):
    from missionstudio.gui.load_scenario_widget import TEMPLATES_DIR
    from PySide6.QtWidgets import QMessageBox

    _add_valid_spacecraft(window)
    question_calls = []
    monkeypatch.setattr(QMessageBox, "question",
                         staticmethod(lambda *a, **k: question_calls.append(1) or QMessageBox.StandardButton.Cancel))

    template_path = sorted(TEMPLATES_DIR.glob("*.json"))[0]
    window.load_scenario_widget.path_chosen.emit(template_path)

    assert len(question_calls) == 1
    # Cancelled -- the original (dirty) scenario must still be showing,
    # not the template that was about to replace it.
    assert window._current_path is None
    assert window.left_tabs.currentWidget() is window.load_scenario_widget


def test_on_new_switches_to_editor_tab(window):
    window.left_tabs.setCurrentWidget(window.load_scenario_widget)
    window.on_new()
    assert window.left_tabs.currentWidget() is window.scenario_editor


def test_open_path_returns_true_on_success_false_on_failure(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from missionstudio.gui.load_scenario_widget import TEMPLATES_DIR

    template_path = sorted(TEMPLATES_DIR.glob("*.json"))[0]
    assert window.open_path(template_path) is True

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    missing = tmp_path / "does_not_exist.json"
    assert window.open_path(missing) is False


@pytest.mark.skipif(_BASILISK_AVAILABLE, reason="this test's premise is specifically that Basilisk is unavailable")
def test_run_without_basilisk_shows_error_and_reenables_action(window, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _add_valid_spacecraft(window)
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))

    window.on_run()
    assert not window.run_action.isEnabled()
    qtbot.waitUntil(lambda: window.run_action.isEnabled(), timeout=5000)

    assert len(critical_calls) == 1
    assert "Basilisk is not installed" in critical_calls[0][2]


def test_run_with_invalid_scenario_shows_error_without_starting_worker(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))

    window.on_run()  # no spacecraft -- invalid, should never construct a RunWorker

    assert len(critical_calls) == 1
    assert window._run_worker is None


def test_close_with_unsaved_changes_prompts_and_cancel_blocks_close(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    _add_valid_spacecraft(window)
    monkeypatch.setattr(QMessageBox, "question",
                         staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel))

    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()


def test_close_with_unsaved_changes_discard_allows_close(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    _add_valid_spacecraft(window)
    monkeypatch.setattr(QMessageBox, "question",
                         staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard))

    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_configure_vizard_sets_request(window, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.vizard_dialog import VizardDialog

    assert window._vizard_request is None

    def fake_exec(self):
        self.live_stream_radio.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(VizardDialog, "exec", fake_exec)
    window.on_configure_vizard()

    assert window._vizard_request is not None
    assert window._vizard_request.live_stream is True


def test_configure_vizard_cancel_leaves_request_unchanged(window, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.vizard_dialog import VizardDialog

    monkeypatch.setattr(VizardDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window.on_configure_vizard()
    assert window._vizard_request is None


def test_run_passes_vizard_request_to_worker(window, monkeypatch):
    from missionstudio.gui.main_window import MainWindow
    from missionstudio.gui.run_worker import RunWorker
    from missionstudio.engine.vizard import VizardRequest

    _add_valid_spacecraft(window)
    window._vizard_request = VizardRequest(live_stream=True)
    # on_run() now confirms Vizard is connected before starting a
    # live-stream run (see its own comment) -- stubbed out here since
    # this test is about vizard_request passthrough, not the Vizard
    # process itself (see test_run_ensures_vizard_is_running_before_a_
    # live_stream_run for that).
    monkeypatch.setattr(MainWindow, "on_launch_vizard", lambda self: True)

    captured = {}
    original_init = RunWorker.__init__

    def spy_init(self, scenario, vizard_request=None, live=False, parent=None):
        captured["vizard_request"] = vizard_request
        original_init(self, scenario, vizard_request=vizard_request, live=live, parent=parent)

    monkeypatch.setattr(RunWorker, "__init__", spy_init)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)  # don't actually spin up the thread

    window.on_run()
    assert captured["vizard_request"] is window._vizard_request


def test_run_starts_busy_indicator_and_disables_other_run_actions(window, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)  # don't actually spin up the thread

    window.on_run()
    assert window._busy_timer.isActive()
    assert not window.run_action.isEnabled()
    assert not window.live_plot_action.isEnabled()  # can't toggle it mid-run either
    assert not window.monte_carlo_action.isEnabled()  # can't start a second run while one is in flight
    assert "Running" in window.statusBar().currentMessage()


def test_live_plot_action_is_checked_by_default(window):
    assert window.live_plot_action.isChecked()


def test_run_passes_live_flag_from_action_to_worker(window, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    captured = {}
    original_init = RunWorker.__init__

    def spy_init(self, scenario, vizard_request=None, live=False, parent=None):
        captured["live"] = live
        original_init(self, scenario, vizard_request=vizard_request, live=live, parent=parent)

    monkeypatch.setattr(RunWorker, "__init__", spy_init)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)

    window.live_plot_action.setChecked(True)
    window.on_run()
    assert captured["live"] is True

    window.live_plot_action.setChecked(False)
    window.on_run()
    assert captured["live"] is False


def test_run_with_live_plot_clears_previous_result_and_shows_results_tab(window, monkeypatch):
    from missionstudio.engine.results import ResultSet, TimeSeries
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)

    stale = ResultSet(scenario_name="stale")
    stale.add(TimeSeries("sat-1.position_N", [0.0], ("x", "y", "z"), [[0.0, 0.0, 0.0]], units="m"))
    window.results_widget.set_result(stale)
    window.right_tabs.setCurrentWidget(window.kernel_status_widget)

    window.live_plot_action.setChecked(True)
    window.on_run()

    assert window.results_widget.series_combo.count() == 0
    assert window.right_tabs.currentWidget() is window.results_widget


def test_run_finished_preserves_users_series_selection(window):
    """Regression test for an audit finding: _on_run_finished() used to
    call ResultsWidget.set_result(), which unconditionally rebuilds
    series_combo and resets its selection to the first series -- so the
    instant a live-watched run actually finished, whatever series the
    user had picked to watch snapped back to the first one. It must use
    set_live_result() instead, which only rebuilds when the series set
    itself changes.
    """
    from missionstudio.engine.results import ResultSet, TimeSeries

    def _result():
        rs = ResultSet(scenario_name="test")
        rs.add(TimeSeries("sat-1.position_N", [0.0], ("x", "y", "z"), [[0.0, 0.0, 0.0]], units="m"))
        rs.add(TimeSeries("sat-1.velocity_N", [0.0], ("x", "y", "z"), [[0.0, 0.0, 0.0]], units="m/s"))
        return rs

    window._on_run_progress(_result(), 0.5)
    window.results_widget.series_combo.setCurrentIndex(1)  # "sat-1.velocity_N"

    window._on_run_finished(_result())

    assert window.results_widget.series_combo.currentIndex() == 1


def test_close_while_run_in_progress_is_blocked(window, qtbot, monkeypatch):
    import threading

    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    info_calls = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: info_calls.append(a)))

    release = threading.Event()
    monkeypatch.setattr(RunWorker, "run", lambda self: release.wait(5))

    window.on_run()
    qtbot.waitUntil(lambda: window._run_worker.isRunning(), timeout=5000)

    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert len(info_calls) == 1

    release.set()
    qtbot.waitUntil(lambda: not window._run_worker.isRunning(), timeout=5000)


def test_run_progress_updates_results_widget_and_busy_bar(window):
    from missionstudio.engine.results import ResultSet, TimeSeries

    window._start_busy("Running test...", determinate=True)
    partial = ResultSet(scenario_name="test")
    partial.add(TimeSeries("sat-1.position_N", [0.0, 1.0], ("x", "y", "z"),
                            [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], units="m"))

    window._on_run_progress(partial, 0.5)

    assert window.results_widget.series_combo.count() == 1
    assert window._busy_progress.value() == 50


def test_on_run_captures_epoch_and_passes_it_to_results_widget(window, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    window.scenario_editor.epoch_edit.setText("2031-05-01T00:00:00")
    monkeypatch.setattr(RunWorker, "start", lambda self: None)  # don't actually spin up the thread

    window.on_run()

    assert window._last_run_epoch_utc == "2031-05-01T00:00:00"


def test_run_finished_passes_captured_epoch_to_results_widget(window):
    from missionstudio.engine.results import ResultSet, TimeSeries

    window._last_run_epoch_utc = "2032-01-01T00:00:00"
    result = ResultSet(scenario_name="test")
    result.add(TimeSeries("sat-1.position_N", [0.0, 1.0], ("x", "y", "z"),
                           [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], units="m"))

    window._on_run_finished(result)

    assert window.results_widget._epoch_utc == "2032-01-01T00:00:00"


def test_run_finished_stops_busy_indicator_and_reenables_actions(window):
    from missionstudio.engine.results import ResultSet

    window._start_busy("Running test...")
    window._on_run_finished(ResultSet(scenario_name="test", series={}))
    assert not window._busy_timer.isActive()
    assert window.run_action.isEnabled()
    assert window.monte_carlo_action.isEnabled()


def test_run_failed_stops_busy_indicator_and_reenables_actions(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    window._start_busy("Running test...")
    window._on_run_failed("boom")
    assert not window._busy_timer.isActive()
    assert window.run_action.isEnabled()
    assert window.monte_carlo_action.isEnabled()


def test_run_monte_carlo_rejects_disabled_monte_carlo(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _add_valid_spacecraft(window)  # monte_carlo defaults to disabled
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))

    window.on_run_monte_carlo()
    assert len(critical_calls) == 1
    assert "enable monte carlo" in critical_calls[0][2].lower()
    assert window._mc_worker is None


def test_run_monte_carlo_starts_worker_with_chosen_archive_dir(window, monkeypatch, tmp_path):
    from missionstudio.gui.run_worker import MonteCarloWorker
    from missionstudio.schema.scenario import DispersionConfig, MonteCarloConfig
    from PySide6.QtWidgets import QFileDialog

    _add_valid_spacecraft(window)
    window.scenario_editor.monte_carlo_group.set_spacecraft_names(["sat-1"])
    window.scenario_editor.monte_carlo_group.from_dataclass(MonteCarloConfig(
        enabled=True, num_runs=3,
        dispersions=[DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="uniform", bounds=[90, 110])],
    ))

    archive_dir = tmp_path / "mc_archive"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(archive_dir)))
    monkeypatch.setattr(MonteCarloWorker, "start", lambda self: None)  # don't actually spin up the thread

    window.on_run_monte_carlo()
    assert window._mc_worker is not None
    assert window._mc_worker.archive_dir == archive_dir
    assert window._mc_worker.mc_config.num_runs == 3
    assert not window.monte_carlo_action.isEnabled()
    assert not window.run_action.isEnabled()  # can't start a second run while one is in flight
    assert window._busy_timer.isActive()


def test_monte_carlo_finished_stops_busy_indicator_and_reenables_actions(window):
    window._start_busy("Running Monte Carlo test...")
    window._on_monte_carlo_finished([])
    assert not window._busy_timer.isActive()
    assert window.run_action.isEnabled()
    assert window.monte_carlo_action.isEnabled()


def test_monte_carlo_failed_stops_busy_indicator_and_reenables_actions(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    window._start_busy("Running Monte Carlo test...")
    window._on_monte_carlo_failed("boom")
    assert not window._busy_timer.isActive()
    assert window.run_action.isEnabled()
    assert window.monte_carlo_action.isEnabled()


def test_run_monte_carlo_cancel_dialog_does_not_start_worker(window, monkeypatch):
    from missionstudio.schema.scenario import MonteCarloConfig
    from PySide6.QtWidgets import QFileDialog

    _add_valid_spacecraft(window)
    window.scenario_editor.monte_carlo_group.set_spacecraft_names(["sat-1"])
    window.scenario_editor.monte_carlo_group.from_dataclass(MonteCarloConfig(enabled=True))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))

    window.on_run_monte_carlo()
    assert window._mc_worker is None


def test_run_with_mission_sequence_ignores_live_flag_and_shows_mission_output(window, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker
    from missionstudio.schema.command import Command

    _add_valid_spacecraft(window)
    window.scenario_editor.mission_sequence_editor.from_command_list([
        Command(kind="script_block", params={"code": "pass"}),
    ])
    window.scenario_editor.changed.emit()

    captured = {}
    original_init = RunWorker.__init__

    def spy_init(self, scenario, vizard_request=None, live=False, parent=None):
        captured["live"] = live
        original_init(self, scenario, vizard_request=vizard_request, live=live, parent=parent)

    monkeypatch.setattr(RunWorker, "__init__", spy_init)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)

    window.live_plot_action.setChecked(True)
    window.on_run()

    # MissionEngine has no run_live() equivalent (see RunWorker.run()) --
    # a mission_sequence run always ignores the live-plot toggle.
    assert captured["live"] is False


def test_run_finished_with_command_summary_shows_mission_output_tab(window):
    from missionstudio.engine.results import CommandSummary, ReportEntry, ResultSet

    summary = CommandSummary(reports=[ReportEntry(label="x", t_s=1.0, values={})], commands_executed=1)
    window._on_run_finished(ResultSet(scenario_name="test", series={}), summary)

    assert window.right_tabs.currentWidget() is window.mission_output_widget
    assert "1 command(s) executed" in window.mission_output_widget.text_edit.toPlainText()


def test_run_finished_without_command_summary_shows_results_tab(window):
    from missionstudio.engine.results import ResultSet

    window.right_tabs.setCurrentWidget(window.kernel_status_widget)
    window._on_run_finished(ResultSet(scenario_name="test", series={}))
    assert window.right_tabs.currentWidget() is window.results_widget


class _FakeVizardProcess:
    def __init__(self, pid=999):
        self.pid = pid
        self._alive = True
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return None if self._alive else 0

    def kill_for_test(self):
        self._alive = False

    def terminate(self):
        self.terminate_calls += 1
        self._alive = False

    def kill(self):
        self.kill_calls += 1
        self._alive = False

    def wait(self, timeout=None):
        return 0


def test_launch_vizard_starts_it_when_not_running(window, monkeypatch):
    from pathlib import Path

    from missionstudio.gui import main_window

    calls = []
    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: Path("/fake/Vizard"))
    monkeypatch.setattr(main_window, "launch_vizard",
                         lambda path, direct_comm_address=None: calls.append(path) or _FakeVizardProcess())

    window.on_launch_vizard()

    assert calls == [Path("/fake/Vizard")]
    assert "Launched Vizard" in window.statusBar().currentMessage()


def test_launch_vizard_does_not_relaunch_while_already_running(window, monkeypatch):
    """The exact behavior the "Launch Vizard" action depends on: clicking
    it again while Vizard is still open must not spawn a second instance.
    """
    from pathlib import Path

    from missionstudio.gui import main_window

    calls = []
    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: Path("/fake/Vizard"))
    monkeypatch.setattr(main_window, "launch_vizard",
                         lambda path, direct_comm_address=None: calls.append(path) or _FakeVizardProcess())

    window.on_launch_vizard()
    window.on_launch_vizard()
    window.on_launch_vizard()

    assert len(calls) == 1
    assert "already running" in window.statusBar().currentMessage().lower()


def test_launch_vizard_relaunches_after_the_process_exits(window, monkeypatch):
    from pathlib import Path

    from missionstudio.gui import main_window

    processes = [_FakeVizardProcess(pid=111), _FakeVizardProcess(pid=222)]
    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: Path("/fake/Vizard"))
    monkeypatch.setattr(main_window, "launch_vizard", lambda path, direct_comm_address=None: processes.pop(0))

    window.on_launch_vizard()
    first = window._vizard_process
    first.kill_for_test()

    window.on_launch_vizard()
    assert window._vizard_process.pid == 222


def test_launch_vizard_not_found_falls_back_to_browse(window, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from pathlib import Path

    from missionstudio.gui import main_window

    picked = Path("/picked/Vizard")
    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(picked), "")))
    remembered = []
    monkeypatch.setattr(main_window, "remember_vizard_executable", lambda path: remembered.append(path))
    monkeypatch.setattr(main_window, "launch_vizard", lambda path, direct_comm_address=None: _FakeVizardProcess())

    window.on_launch_vizard()

    assert remembered == [picked]
    assert window._vizard_process is not None


def test_launch_vizard_not_found_and_browse_cancelled_does_nothing(window, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from pathlib import Path

    from missionstudio.gui import main_window

    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    launch_calls = []
    monkeypatch.setattr(main_window, "launch_vizard",
                         lambda path, direct_comm_address=None: launch_calls.append(path))

    window.on_launch_vizard()

    assert launch_calls == []
    assert window._vizard_process is None


def test_launch_vizard_failure_shows_error(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from pathlib import Path

    from missionstudio.gui import main_window

    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: Path("/fake/Vizard"))

    def raise_oserror(path, direct_comm_address=None):
        raise OSError("permission denied")

    monkeypatch.setattr(main_window, "launch_vizard", raise_oserror)
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))

    window.on_launch_vizard()

    assert len(critical_calls) == 1
    assert window._vizard_process is None


def test_launch_vizard_passes_direct_comm_address_when_live_stream_configured(window, monkeypatch):
    """Direct user feedback: manually launching Vizard for a live-stream
    run left it sitting on its own manual launcher screen (see
    on_launch_vizard()'s own docstring) -- it must be started with its
    -directComm flag whenever Vizard Configuration is set to live-stream.
    """
    from pathlib import Path

    from missionstudio.engine.vizard import VizardRequest
    from missionstudio.gui import main_window
    from missionstudio.gui.vizard_launcher import DEFAULT_LIVE_STREAM_ADDRESS

    window._vizard_request = VizardRequest(live_stream=True)
    calls = []
    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: Path("/fake/Vizard"))
    monkeypatch.setattr(main_window, "launch_vizard",
                         lambda path, direct_comm_address=None: calls.append(direct_comm_address)
                         or _FakeVizardProcess())

    window.on_launch_vizard()

    assert calls == [DEFAULT_LIVE_STREAM_ADDRESS]


def test_launch_vizard_passes_no_direct_comm_address_without_live_stream(window, monkeypatch):
    from pathlib import Path

    from missionstudio.gui import main_window

    assert window._vizard_request is None  # save-file mode, or never configured at all
    calls = []
    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: Path("/fake/Vizard"))
    monkeypatch.setattr(main_window, "launch_vizard",
                         lambda path, direct_comm_address=None: calls.append(direct_comm_address)
                         or _FakeVizardProcess())

    window.on_launch_vizard()

    assert calls == [None]


def test_launch_vizard_relaunches_a_mismatched_already_running_instance(window, monkeypatch):
    """The known residual gap this closes: Vizard was already launched
    (by this same session's "Launch Vizard" button) before live-stream
    was ever configured -- e.g. for a save-file run, or before Vizard
    Configuration was set at all -- so the running instance has no
    -directComm connection. Simply trusting "already running" here would
    reproduce the exact original bug one launch later; it must be
    terminated and replaced with a live-stream-ready one instead.
    """
    from pathlib import Path

    from missionstudio.engine.vizard import VizardRequest
    from missionstudio.gui import main_window
    from missionstudio.gui.vizard_launcher import DEFAULT_LIVE_STREAM_ADDRESS

    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: Path("/fake/Vizard"))
    launch_calls = []
    monkeypatch.setattr(main_window, "launch_vizard",
                         lambda path, direct_comm_address=None: launch_calls.append(direct_comm_address)
                         or _FakeVizardProcess())

    # First launch: no live-stream configured yet.
    window.on_launch_vizard()
    first_process = window._vizard_process
    assert launch_calls == [None]

    # Now live-stream gets configured, and Vizard is asked for again.
    window._vizard_request = VizardRequest(live_stream=True)
    window.on_launch_vizard()

    assert first_process.terminate_calls == 1
    assert launch_calls == [None, DEFAULT_LIVE_STREAM_ADDRESS]
    assert window._vizard_process is not first_process
    assert window._vizard_direct_comm_address == DEFAULT_LIVE_STREAM_ADDRESS


def test_launch_vizard_keeps_a_live_stream_ready_instance_for_a_later_save_file_launch(window, monkeypatch):
    """The opposite direction is NOT a mismatch worth relaunching over --
    a -directComm connection doesn't stop Vizard from also being used to
    open a save file, so an already-live-stream-ready instance is kept.
    """
    from pathlib import Path

    from missionstudio.engine.vizard import VizardRequest
    from missionstudio.gui import main_window

    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: Path("/fake/Vizard"))
    launch_calls = []
    monkeypatch.setattr(main_window, "launch_vizard",
                         lambda path, direct_comm_address=None: launch_calls.append(direct_comm_address)
                         or _FakeVizardProcess())

    window._vizard_request = VizardRequest(live_stream=True)
    window.on_launch_vizard()
    first_process = window._vizard_process

    window._vizard_request = None  # switch to save-file/no request
    window.on_launch_vizard()

    assert first_process.terminate_calls == 0
    assert len(launch_calls) == 1  # never relaunched
    assert window._vizard_process is first_process


def test_launch_vizard_never_touches_an_instance_it_did_not_itself_launch(window, monkeypatch):
    """self._vizard_process is None (this session never launched Vizard
    itself) even though Vizard may well already be running externally --
    there is no reliable way to ask it whether it's connected, so a
    fresh, correctly-configured instance is launched alongside it rather
    than guessing about (or worse, killing) a process this app doesn't
    own.
    """
    from pathlib import Path

    from missionstudio.engine.vizard import VizardRequest
    from missionstudio.gui import main_window
    from missionstudio.gui.vizard_launcher import DEFAULT_LIVE_STREAM_ADDRESS

    assert window._vizard_process is None
    window._vizard_request = VizardRequest(live_stream=True)
    monkeypatch.setattr(main_window, "find_vizard_executable", lambda: Path("/fake/Vizard"))
    launch_calls = []
    monkeypatch.setattr(main_window, "launch_vizard",
                         lambda path, direct_comm_address=None: launch_calls.append(direct_comm_address)
                         or _FakeVizardProcess())

    window.on_launch_vizard()

    assert launch_calls == [DEFAULT_LIVE_STREAM_ADDRESS]


def test_run_ensures_vizard_is_running_before_a_live_stream_run(window, monkeypatch):
    """Regression test for a real user report: a live-stream run appeared
    to hang at 0% with Abort having no effect, because Vizard was never
    actually connected (see on_run()'s own comment) -- on_run() must
    confirm Vizard first via on_launch_vizard(), not just hand the
    request to RunWorker and hope.
    """
    from missionstudio.engine.vizard import VizardRequest
    from missionstudio.gui.main_window import MainWindow
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    window._vizard_request = VizardRequest(live_stream=True)
    calls = []
    monkeypatch.setattr(MainWindow, "on_launch_vizard", lambda self: calls.append(1) or True)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)  # don't actually spin up the thread

    window.on_run()

    assert calls == [1]
    assert window._run_worker is not None  # the run actually proceeded


def test_run_refuses_to_start_when_vizard_cannot_be_confirmed(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from missionstudio.engine.vizard import VizardRequest
    from missionstudio.gui.main_window import MainWindow
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    window._vizard_request = VizardRequest(live_stream=True)
    monkeypatch.setattr(MainWindow, "on_launch_vizard", lambda self: False)
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))
    start_calls = []
    monkeypatch.setattr(RunWorker, "start", lambda self: start_calls.append(1))

    window.on_run()

    assert len(critical_calls) == 1
    assert start_calls == []
    assert window._run_worker is None  # never even constructed


def test_run_never_touches_vizard_without_a_live_stream_request(window, monkeypatch):
    """Vizard Configuration defaults to None (no request at all) --
    on_run() must not try to launch/confirm Vizard for an ordinary run.
    """
    from missionstudio.gui.main_window import MainWindow
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    assert window._vizard_request is None
    calls = []
    monkeypatch.setattr(MainWindow, "on_launch_vizard", lambda self: calls.append(1) or True)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)

    window.on_run()

    assert calls == []


def test_close_with_no_unsaved_changes_does_not_prompt(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    question_calls = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: question_calls.append(1)))

    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


# -- Abort Simulation (direct user feedback: "there should also be the
# option to abort a running simulation, if needed, without breaking the
# tool") -- see gui.run_worker.RunWorker's own module docstring for the
# cooperative-cancellation design these tests exercise the MainWindow
# wiring for.

def test_abort_action_disabled_until_a_run_starts(window):
    assert not window.abort_action.isEnabled()


def test_on_run_enables_abort_action(window, monkeypatch):
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)  # don't actually spin up the thread

    window.on_run()

    assert window.abort_action.isEnabled()


def test_on_run_monte_carlo_never_enables_abort_action(window, monkeypatch):
    """MonteCarloWorker has no request_cancel() -- see abort_action's own
    construction comment in main_window.py -- so a Monte Carlo run must
    never enable it.
    """
    from PySide6.QtWidgets import QFileDialog
    from missionstudio.gui.run_worker import MonteCarloWorker
    from missionstudio.schema.scenario import MonteCarloConfig

    _add_valid_spacecraft(window)
    window.scenario_editor.monte_carlo_group.set_spacecraft_names(["sat-1"])
    window.scenario_editor.monte_carlo_group.from_dataclass(MonteCarloConfig(enabled=True))
    window.scenario_editor.changed.emit()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: "/tmp/mc"))
    monkeypatch.setattr(MonteCarloWorker, "start", lambda self: None)

    window.on_run_monte_carlo()

    assert not window.abort_action.isEnabled()


def test_run_finished_disables_abort_action(window):
    from missionstudio.engine.results import ResultSet

    window._start_busy("Running test...")
    window.abort_action.setEnabled(True)
    window._on_run_finished(ResultSet(scenario_name="test", series={}))
    assert not window.abort_action.isEnabled()


def test_run_failed_disables_abort_action(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    window._start_busy("Running test...")
    window.abort_action.setEnabled(True)
    window._on_run_failed("boom")
    assert not window.abort_action.isEnabled()


def test_on_abort_run_calls_request_cancel_on_the_running_worker(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from missionstudio.gui.run_worker import RunWorker

    # isRunning() is patched to always return True below (to simulate an
    # in-flight worker without a real thread) -- if that patch is still
    # in effect when qtbot's teardown closes this window, closeEvent()
    # would hit its own real, unmocked "run in progress" QMessageBox and
    # block forever in this offscreen test session waiting for a click
    # that never comes. Mocked here too, same as
    # test_close_while_run_in_progress_is_blocked, so teardown can't hang
    # on it regardless of fixture teardown ordering.
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    _add_valid_spacecraft(window)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)
    window.on_run()
    assert window.abort_action.isEnabled()

    cancel_calls = []
    monkeypatch.setattr(RunWorker, "isRunning", lambda self: True)
    monkeypatch.setattr(RunWorker, "request_cancel", lambda self: cancel_calls.append(1))

    window.on_abort_run()

    assert cancel_calls == [1]
    assert not window.abort_action.isEnabled()


def test_on_abort_run_is_a_no_op_without_a_running_worker(window):
    # No run ever started -- window._run_worker is still None -- must not
    # raise.
    window.on_abort_run()
    assert not window.abort_action.isEnabled()


def test_run_cancelled_updates_results_widget_and_status(window):
    from missionstudio.engine.results import ResultSet, TimeSeries

    window._start_busy("Running test...")
    window.abort_action.setEnabled(True)
    window._last_run_epoch_utc = "2032-01-01T00:00:00"
    partial = ResultSet(scenario_name="test")
    partial.add(TimeSeries("sat-1.position_N", [0.0, 1.0], ("x", "y", "z"),
                            [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], units="m"))

    window._on_run_cancelled(partial)

    assert not window._busy_timer.isActive()
    assert not window.abort_action.isEnabled()
    assert window.run_action.isEnabled()
    assert window.results_widget.series_combo.count() == 1
    assert window.results_widget._epoch_utc == "2032-01-01T00:00:00"
    assert window.right_tabs.currentWidget() is window.results_widget
    assert window.statusBar().currentMessage() == "Run cancelled by user."


def test_run_cancelled_with_command_summary_shows_mission_output_tab(window):
    from missionstudio.engine.results import CommandSummary, ReportEntry, ResultSet

    summary = CommandSummary(reports=[ReportEntry(label="x", t_s=1.0, values={})], commands_executed=1)
    window._on_run_cancelled(ResultSet(scenario_name="test", series={}), summary)

    assert window.right_tabs.currentWidget() is window.mission_output_widget
    assert "1 command(s) executed" in window.mission_output_widget.text_edit.toPlainText()


def test_end_to_end_cancel_signal_updates_window_without_crashing(window, qtbot, monkeypatch):
    """Drives the real signal/slot connection (RunWorker.cancelled ->
    MainWindow._on_run_cancelled) through a real background QThread,
    matching test_close_while_run_in_progress_is_blocked's approach for
    the same reason: this is the one thing a pure method-call test like
    the ones above can't prove -- that the Signal(object, object) really
    is connected end to end.
    """
    from missionstudio.engine.results import ResultSet
    from missionstudio.gui.run_worker import RunWorker

    _add_valid_spacecraft(window)
    partial = ResultSet(scenario_name="test", series={})

    def fake_run(self):
        self.cancelled.emit(partial, None)

    monkeypatch.setattr(RunWorker, "run", fake_run)

    window.on_run()
    qtbot.waitUntil(lambda: window._run_worker is not None, timeout=5000)
    qtbot.waitUntil(lambda: not window._run_worker.isRunning(), timeout=5000)
    # cancelled is a queued (cross-thread) connection -- the QThread
    # reporting not-running any more doesn't guarantee the GUI thread has
    # actually processed the queued slot invocation yet, so wait on the
    # slot's own observable effect rather than the thread state.
    qtbot.waitUntil(lambda: not window.abort_action.isEnabled(), timeout=5000)

    assert window.statusBar().currentMessage() == "Run cancelled by user."
