"""Tests for gui.sensor_actuator_editor.SensorActuatorListWidget."""

import pytest

pytestmark = pytest.mark.requires_gui


def test_from_list_to_list_round_trip(qtbot):
    from missionstudio.gui.sensor_actuator_editor import SensorActuatorListWidget
    from missionstudio.schema.scenario import SUPPORTED_SENSOR_KINDS, SensorConfig

    widget = SensorActuatorListWidget(SensorConfig, SUPPORTED_SENSOR_KINDS)
    qtbot.addWidget(widget)
    sensors = [
        SensorConfig(kind="star_tracker", name="st-1", params={"noise_arcsec": 5.0}),
        SensorConfig(kind="imu", name="imu-1", params={}),
    ]
    widget.from_list(sensors)
    assert widget.list_widget.count() == 2
    assert [s.name for s in widget.to_list()] == ["st-1", "imu-1"]
    assert widget.to_list()[0].params == {"noise_arcsec": 5.0}


def test_add_via_dialog(qtbot, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.sensor_actuator_editor import SensorActuatorListWidget, _ItemEditorDialog
    from missionstudio.schema.scenario import SUPPORTED_ACTUATOR_KINDS, ActuatorConfig

    widget = SensorActuatorListWidget(ActuatorConfig, SUPPORTED_ACTUATOR_KINDS)
    qtbot.addWidget(widget)

    def fake_exec(self):
        self.name_edit.setText("rw-1")
        index = self.kind_combo.findText("reaction_wheel")
        self.kind_combo.setCurrentIndex(index)
        self.params_edit.setPlainText('{"gsHat_B": [1, 0, 0]}')
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_ItemEditorDialog, "exec", fake_exec)
    changed_count = []
    widget.changed.connect(lambda: changed_count.append(1))

    qtbot.mouseClick(widget.add_button, Qt.MouseButton.LeftButton)

    assert widget.list_widget.count() == 1
    added = widget.to_list()[0]
    assert added.name == "rw-1"
    assert added.kind == "reaction_wheel"
    assert added.params == {"gsHat_B": [1, 0, 0]}
    assert changed_count == [1]


def test_edit_and_remove(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.sensor_actuator_editor import SensorActuatorListWidget, _ItemEditorDialog
    from missionstudio.schema.scenario import SUPPORTED_SENSOR_KINDS, SensorConfig

    widget = SensorActuatorListWidget(SensorConfig, SUPPORTED_SENSOR_KINDS)
    qtbot.addWidget(widget)
    widget.from_list([SensorConfig(kind="imu", name="orig", params={})])
    widget.list_widget.setCurrentRow(0)

    def fake_exec(self):
        self.name_edit.setText("renamed")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_ItemEditorDialog, "exec", fake_exec)
    widget._on_edit()
    assert widget.to_list()[0].name == "renamed"

    widget.list_widget.setCurrentRow(0)
    widget._on_remove()
    assert widget.to_list() == []


def test_rejects_duplicate_name_on_add(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox

    from missionstudio.gui.sensor_actuator_editor import SensorActuatorListWidget, _ItemEditorDialog
    from missionstudio.schema.scenario import SUPPORTED_SENSOR_KINDS, SensorConfig

    widget = SensorActuatorListWidget(SensorConfig, SUPPORTED_SENSOR_KINDS)
    qtbot.addWidget(widget)
    widget.from_list([SensorConfig(kind="imu", name="dup", params={})])

    def fake_exec(self):
        self.name_edit.setText("dup")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_ItemEditorDialog, "exec", fake_exec)
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))

    widget._on_add()
    assert len(widget.to_list()) == 1
    assert len(critical_calls) == 1


def test_item_editor_dialog_rejects_invalid_json(qtbot):
    from missionstudio.gui.sensor_actuator_editor import _ItemEditorDialog
    from missionstudio.schema.scenario import SUPPORTED_SENSOR_KINDS, SensorConfig

    dialog = _ItemEditorDialog(SensorConfig, SUPPORTED_SENSOR_KINDS)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("s1")
    dialog.params_edit.setPlainText("not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        dialog.to_dataclass()


def test_item_editor_dialog_rejects_empty_name(qtbot):
    from missionstudio.gui.sensor_actuator_editor import _ItemEditorDialog
    from missionstudio.schema.scenario import SUPPORTED_SENSOR_KINDS, SensorConfig

    dialog = _ItemEditorDialog(SensorConfig, SUPPORTED_SENSOR_KINDS)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("")
    with pytest.raises(ValueError, match="name must not be empty"):
        dialog.to_dataclass()
