"""Tests for gui.spacecraft_editor."""

import pytest

pytestmark = pytest.mark.requires_gui


def test_dialog_default_spacecraft(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    sc = dialog.to_dataclass()
    assert sc.name == "sat-1"
    assert sc.orbit.type == "classical_elements"
    assert sc.inertia_kg_m2 == [10.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0]


def test_dialog_edits_existing_config(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig

    existing = SpacecraftConfig(
        name="sat-existing",
        orbit=OrbitIC(type="cartesian", position_km=[1.0, 2.0, 3.0], velocity_km_s=[4.0, 5.0, 6.0]),
        dry_mass_kg=250.0,
    )
    dialog = SpacecraftEditorDialog(config=existing)
    qtbot.addWidget(dialog)
    got = dialog.to_dataclass()
    assert got.name == "sat-existing"
    assert got.dry_mass_kg == 250.0
    assert got.orbit.position_km == [1.0, 2.0, 3.0]


def test_dialog_round_trips_sensors_actuators_and_fsw_mode(qtbot):
    """Regression test: editing an existing spacecraft used to silently
    DROP sensors/actuators/fsw_mode/fsw_params/control_params (the dialog
    built a brand new SpacecraftConfig without passing them through). This
    is exactly the round trip that bug broke.
    """
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog
    from missionstudio.schema.scenario import ActuatorConfig, OrbitIC, SensorConfig, SpacecraftConfig

    existing = SpacecraftConfig(
        name="sat-with-fsw",
        orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]),
        sensors=[SensorConfig(kind="star_tracker", name="st-1", params={"noise_arcsec": 5.0})],
        actuators=[ActuatorConfig(kind="reaction_wheel", name="rw-1", params={"gsHat_B": [1, 0, 0]})],
        fsw_mode="hillPoint",
        fsw_params={"foo": "bar"},
        control_params={"K": 4.0, "P": 25.0},
    )
    dialog = SpacecraftEditorDialog(config=existing)
    qtbot.addWidget(dialog)
    got = dialog.to_dataclass()

    assert len(got.sensors) == 1
    assert got.sensors[0].kind == "star_tracker"
    assert got.sensors[0].params == {"noise_arcsec": 5.0}
    assert len(got.actuators) == 1
    assert got.actuators[0].params == {"gsHat_B": [1, 0, 0]}
    assert got.fsw_mode == "hillPoint"
    assert got.fsw_params == {"foo": "bar"}
    assert got.control_params == {"K": 4.0, "P": 25.0}


def test_dialog_defaults_fsw_mode_to_none(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    sc = dialog.to_dataclass()
    assert sc.fsw_mode is None
    assert sc.sensors == []
    assert sc.actuators == []


def test_dialog_rejects_invalid_fsw_params_json(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    dialog.fsw_params_edit.setPlainText("{not valid json")
    with pytest.raises(ValueError, match="not valid JSON"):
        dialog.to_dataclass()


def test_dialog_rejects_empty_name(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog
    from missionstudio.schema.scenario import ScenarioValidationError

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("")
    with pytest.raises(ScenarioValidationError, match="name must not be empty"):
        dialog.to_dataclass()


def test_list_widget_from_list_to_list_round_trip(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftListWidget
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig

    lw = SpacecraftListWidget()
    qtbot.addWidget(lw)
    configs = [
        SpacecraftConfig(name="a", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0])),
        SpacecraftConfig(name="b", orbit=OrbitIC(type="cartesian", position_km=[8000, 0, 0], velocity_km_s=[0, 7.0, 0])),
    ]
    lw.from_list(configs)
    assert lw.list_widget.count() == 2
    assert [c.name for c in lw.to_list()] == ["a", "b"]


def test_list_widget_add_via_dialog(qtbot, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog, SpacecraftListWidget

    lw = SpacecraftListWidget()
    qtbot.addWidget(lw)

    def fake_exec(self):
        self.name_edit.setText("added-sat")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SpacecraftEditorDialog, "exec", fake_exec)
    changed_count = []
    lw.changed.connect(lambda: changed_count.append(1))

    qtbot.mouseClick(lw.add_button, Qt.MouseButton.LeftButton)

    assert lw.list_widget.count() == 1
    assert lw.to_list()[0].name == "added-sat"
    assert changed_count == [1]


def test_list_widget_edit_and_remove(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog, SpacecraftListWidget
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig

    lw = SpacecraftListWidget()
    qtbot.addWidget(lw)
    lw.from_list([SpacecraftConfig(name="orig",
                                    orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]))])
    lw.list_widget.setCurrentRow(0)

    def fake_exec(self):
        self.name_edit.setText("renamed")
        self.dry_mass_kg.setValue(321.0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SpacecraftEditorDialog, "exec", fake_exec)
    lw._on_edit()
    assert lw.to_list()[0].name == "renamed"
    assert lw.to_list()[0].dry_mass_kg == 321.0

    lw.list_widget.setCurrentRow(0)
    lw._on_remove()
    assert lw.to_list() == []


def test_list_widget_rejects_duplicate_name_on_add(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox

    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog, SpacecraftListWidget
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig

    lw = SpacecraftListWidget()
    qtbot.addWidget(lw)
    lw.from_list([SpacecraftConfig(name="dup",
                                    orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]))])

    def fake_exec(self):
        self.name_edit.setText("dup")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SpacecraftEditorDialog, "exec", fake_exec)
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))

    lw._on_add()
    assert len(lw.to_list()) == 1  # not added
    assert len(critical_calls) == 1
