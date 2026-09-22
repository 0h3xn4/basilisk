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
    from missionstudio.gui.run_worker import RunWorker
    from missionstudio.engine.vizard import VizardRequest

    _add_valid_spacecraft(window)
    window._vizard_request = VizardRequest(live_stream=True)

    captured = {}
    original_init = RunWorker.__init__

    def spy_init(self, scenario, vizard_request=None, parent=None):
        captured["vizard_request"] = vizard_request
        original_init(self, scenario, vizard_request=vizard_request, parent=parent)

    monkeypatch.setattr(RunWorker, "__init__", spy_init)
    monkeypatch.setattr(RunWorker, "start", lambda self: None)  # don't actually spin up the thread

    window.on_run()
    assert captured["vizard_request"] is window._vizard_request


def test_close_with_no_unsaved_changes_does_not_prompt(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    question_calls = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: question_calls.append(1)))

    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    assert question_calls == []
