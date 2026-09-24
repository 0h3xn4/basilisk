"""Tests for gui.vizard_status_widget.VizardStatusWidget -- with
gui.vizard_launcher's find/launch functions monkeypatched so nothing here
ever touches a real filesystem search or spawns a real process.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_gui


class _FakeProcess:
    def __init__(self, pid=1234):
        self.pid = pid
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def kill_for_test(self):
        self._alive = False


def _patch_launcher(monkeypatch, module, *, found_path=None, launch_result=None, launch_raises=None):
    monkeypatch.setattr(module, "find_vizard_executable", lambda: found_path)

    def fake_launch(path):
        if launch_raises is not None:
            raise launch_raises
        return launch_result

    monkeypatch.setattr(module, "launch_vizard", fake_launch)
    monkeypatch.setattr(module, "remember_vizard_executable", lambda path: None)


def test_initial_state_not_found_shows_browse_hint(qtbot, monkeypatch):
    from missionstudio.gui import vizard_status_widget

    _patch_launcher(monkeypatch, vizard_status_widget, found_path=None)
    widget = vizard_status_widget.VizardStatusWidget()
    qtbot.addWidget(widget)

    assert not widget.is_running()
    assert "not found" in widget.status_label.text().lower()
    assert widget.launch_button.text() == "Launch Vizard"


def test_initial_state_found_shows_its_path(qtbot, monkeypatch, tmp_path):
    from missionstudio.gui import vizard_status_widget

    exe = tmp_path / "Vizard.x86_64"
    _patch_launcher(monkeypatch, vizard_status_widget, found_path=exe)
    widget = vizard_status_widget.VizardStatusWidget()
    qtbot.addWidget(widget)

    assert str(exe) in widget.status_label.text()


def test_ensure_launched_starts_vizard_when_not_running(qtbot, monkeypatch, tmp_path):
    from missionstudio.gui import vizard_status_widget

    exe = tmp_path / "Vizard.x86_64"
    process = _FakeProcess()
    _patch_launcher(monkeypatch, vizard_status_widget, found_path=exe, launch_result=process)
    widget = vizard_status_widget.VizardStatusWidget()
    qtbot.addWidget(widget)

    widget.ensure_launched()

    assert widget.is_running()
    assert f"PID {process.pid}" in widget.status_label.text()
    assert widget.launch_button.text() == "Relaunch Vizard"


def test_ensure_launched_is_a_no_op_when_already_running(qtbot, monkeypatch, tmp_path):
    """This is the exact behavior the "click the Vizard tab" wiring
    depends on: re-selecting the tab while Vizard is still open must not
    spawn a second instance.
    """
    from missionstudio.gui import vizard_status_widget

    exe = tmp_path / "Vizard.x86_64"
    calls = []

    def fake_launch(path):
        calls.append(path)
        return _FakeProcess()

    monkeypatch.setattr(vizard_status_widget, "find_vizard_executable", lambda: exe)
    monkeypatch.setattr(vizard_status_widget, "launch_vizard", fake_launch)
    widget = vizard_status_widget.VizardStatusWidget()
    qtbot.addWidget(widget)

    widget.ensure_launched()
    widget.ensure_launched()
    widget.ensure_launched()

    assert len(calls) == 1


def test_launch_button_relaunches_after_process_exits(qtbot, monkeypatch, tmp_path):
    from missionstudio.gui import vizard_status_widget

    exe = tmp_path / "Vizard.x86_64"
    first = _FakeProcess(pid=111)
    second = _FakeProcess(pid=222)
    processes = [first, second]
    monkeypatch.setattr(vizard_status_widget, "find_vizard_executable", lambda: exe)
    monkeypatch.setattr(vizard_status_widget, "launch_vizard", lambda path: processes.pop(0))
    widget = vizard_status_widget.VizardStatusWidget()
    qtbot.addWidget(widget)

    widget.ensure_launched()
    assert widget.is_running()

    first.kill_for_test()
    widget._poll_tick()
    assert not widget.is_running()
    assert widget.launch_button.text() == "Launch Vizard"

    widget._on_launch_clicked()
    assert widget.is_running()
    assert f"PID {second.pid}" in widget.status_label.text()


def test_launch_failure_shows_error_and_leaves_widget_not_running(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from missionstudio.gui import vizard_status_widget

    exe = tmp_path / "Vizard.x86_64"
    _patch_launcher(monkeypatch, vizard_status_widget, found_path=exe, launch_raises=OSError("permission denied"))
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))
    widget = vizard_status_widget.VizardStatusWidget()
    qtbot.addWidget(widget)

    widget.ensure_launched()

    assert not widget.is_running()
    assert len(critical_calls) == 1


def test_browse_remembers_path_and_launches(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    from missionstudio.gui import vizard_status_widget

    picked = tmp_path / "Vizard.x86_64"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(picked), "")))
    remembered = []
    monkeypatch.setattr(vizard_status_widget, "remember_vizard_executable", lambda path: remembered.append(path))
    # _on_browse_clicked() re-queries find_vizard_executable() after
    # remembering rather than assuming the browsed path directly -- this
    # mock reflects what a real remember-then-find round trip would
    # return, matching test_vizard_launcher.py's own coverage of that
    # round trip with the real (unmocked) function.
    monkeypatch.setattr(vizard_status_widget, "find_vizard_executable", lambda: picked)
    monkeypatch.setattr(vizard_status_widget, "launch_vizard", lambda path: _FakeProcess())
    widget = vizard_status_widget.VizardStatusWidget()
    qtbot.addWidget(widget)

    widget._on_browse_clicked()

    assert remembered == [picked]
    assert widget.is_running()


def test_browse_cancel_does_not_launch(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    from missionstudio.gui import vizard_status_widget

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    launch_calls = []
    monkeypatch.setattr(vizard_status_widget, "find_vizard_executable", lambda: None)
    monkeypatch.setattr(vizard_status_widget, "launch_vizard", lambda path: launch_calls.append(path))
    widget = vizard_status_widget.VizardStatusWidget()
    qtbot.addWidget(widget)

    widget._on_browse_clicked()

    assert launch_calls == []
    assert not widget.is_running()
