"""Tests for gui.sensor_actuator_editor.SensorActuatorListWidget."""

import json

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


def test_new_item_dialog_prefills_params_with_kind_template(qtbot):
    """Regression test: a brand-new sensor/actuator used to start with an
    empty ``{}`` params box no matter the kind, forcing a beginner to
    already know (from reading engine/fsw.py's source) which keys that
    kind needs. It should now start pre-filled with a working example for
    whichever kind is selected when the dialog opens (the first entry in
    SUPPORTED_SENSOR_KINDS, "star_tracker", by default).
    """
    from missionstudio.gui.sensor_actuator_editor import _ItemEditorDialog, _template_params
    from missionstudio.schema.scenario import SUPPORTED_SENSOR_KINDS, SensorConfig

    dialog = _ItemEditorDialog(SensorConfig, SUPPORTED_SENSOR_KINDS)
    qtbot.addWidget(dialog)
    assert dialog.kind_combo.currentText() == "star_tracker"
    dialog.name_edit.setText("st-1")

    config = dialog.to_dataclass()
    assert config.params == _template_params("star_tracker")


def test_switching_kind_does_not_clobber_params_until_reset_clicked(qtbot):
    """Switching Kind must not silently overwrite whatever the user has
    already typed into params -- only the explicit 'Reset to template'
    button does that (see this dialog's module docstring).
    """
    from missionstudio.gui.sensor_actuator_editor import _ItemEditorDialog, _template_params
    from missionstudio.schema.scenario import SUPPORTED_SENSOR_KINDS, SensorConfig

    dialog = _ItemEditorDialog(SensorConfig, SUPPORTED_SENSOR_KINDS)
    qtbot.addWidget(dialog)
    dialog.params_edit.setPlainText('{"hand_typed": true}')

    index = dialog.kind_combo.findText("coarse_sun_sensor")
    dialog.kind_combo.setCurrentIndex(index)
    assert json.loads(dialog.params_edit.toPlainText()) == {"hand_typed": True}

    dialog._on_reset_template()
    assert json.loads(dialog.params_edit.toPlainText()) == _template_params("coarse_sun_sensor")


def test_item_editor_dialog_catches_missing_required_key_immediately(qtbot):
    """Regression test: a missing required params key (e.g.
    coarse_sun_sensor's nHat_B) used to only be caught much later by the
    OUTER spacecraft-editor dialog's SpacecraftConfig.validate() call,
    decontextualized from the params box that actually needs fixing. This
    dialog should catch it itself, immediately.
    """
    from missionstudio.gui.sensor_actuator_editor import _ItemEditorDialog
    from missionstudio.schema.scenario import SUPPORTED_SENSOR_KINDS, SensorConfig

    dialog = _ItemEditorDialog(SensorConfig, SUPPORTED_SENSOR_KINDS)
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("coarse_sun_sensor")
    dialog.kind_combo.setCurrentIndex(index)
    dialog.name_edit.setText("css-1")
    dialog.params_edit.setPlainText("{}")  # no nHat_B

    with pytest.raises(ValueError, match="nHat_B"):
        dialog.to_dataclass()


def test_reset_to_template_button_overwrites_params(qtbot):
    from missionstudio.gui.sensor_actuator_editor import _ItemEditorDialog
    from missionstudio.schema.scenario import SUPPORTED_ACTUATOR_KINDS, ActuatorConfig

    dialog = _ItemEditorDialog(ActuatorConfig, SUPPORTED_ACTUATOR_KINDS,
                                item=ActuatorConfig(kind="reaction_wheel", name="rw-1", params={"stale": True}))
    qtbot.addWidget(dialog)
    assert dialog.params_edit.toPlainText() == json.dumps({"stale": True}, indent=2)

    dialog._on_reset_template()
    config = dialog.to_dataclass()
    assert "gsHat_B" in config.params
    assert "stale" not in config.params


def test_unimplemented_actuator_kind_shows_warning_hint(qtbot):
    from missionstudio.gui.sensor_actuator_editor import _ItemEditorDialog
    from missionstudio.schema.scenario import SUPPORTED_ACTUATOR_KINDS, ActuatorConfig

    dialog = _ItemEditorDialog(ActuatorConfig, SUPPORTED_ACTUATOR_KINDS)
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("thruster")
    dialog.kind_combo.setCurrentIndex(index)
    assert "not simulated yet" in dialog.hint_label.text()
