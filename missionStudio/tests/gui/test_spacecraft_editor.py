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


def test_dialog_power_and_rf_link_default_to_none(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    assert not dialog.power_group.isChecked()
    assert not dialog.rf_link_group.isChecked()
    sc = dialog.to_dataclass()
    assert sc.power is None
    assert sc.rf_link is None


def test_dialog_builds_power_config_when_group_checked(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    dialog.power_group.setChecked(True)
    dialog.panel_area_m2.setValue(2.5)
    dialog.panel_efficiency.setValue(0.3)
    dialog.bus_idle_power_w.setValue(30.0)
    dialog.battery_capacity_wh.setValue(200.0)
    dialog.battery_initial_soc.setValue(0.8)

    sc = dialog.to_dataclass()
    assert sc.power is not None
    assert sc.power.panel_area_m2 == 2.5
    assert sc.power.panel_efficiency == 0.3
    assert sc.power.bus_idle_power_w == 30.0
    assert sc.power.battery_capacity_wh == 200.0
    assert sc.power.battery_initial_soc == 0.8
    assert sc.rf_link is None  # unrelated group, still unchecked


def test_dialog_builds_rf_link_config_when_group_checked(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    dialog.rf_link_group.setChecked(True)
    dialog.tx_power_w.setValue(20.0)
    dialog.frequency_ghz.setValue(2.2)
    dialog.data_rate_mbps.setValue(0.5)
    dialog.tx_antenna_gain_dbi.setValue(8.0)
    dialog.rf_implementation_loss_db.setValue(3.0)
    dialog.required_ebno_db.setValue(5.0)

    sc = dialog.to_dataclass()
    assert sc.rf_link is not None
    assert sc.rf_link.tx_power_w == 20.0
    assert sc.rf_link.frequency_hz == pytest.approx(2.2e9)
    assert sc.rf_link.data_rate_bps == pytest.approx(0.5e6)
    assert sc.rf_link.tx_antenna_gain_dbi == 8.0
    assert sc.rf_link.implementation_loss_db == 3.0
    assert sc.rf_link.required_ebno_db == 5.0
    assert sc.power is None  # unrelated group, still unchecked


def test_dialog_round_trips_power_and_rf_link(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog
    from missionstudio.schema.scenario import OrbitIC, PowerConfig, RFLinkConfig, SpacecraftConfig

    existing = SpacecraftConfig(
        name="sat-power",
        orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]),
        power=PowerConfig(panel_area_m2=1.5, panel_efficiency=0.28, panel_normal_b=[1.0, 0.0, 0.0],
                           bus_idle_power_w=20.0, battery_capacity_wh=150.0, battery_initial_soc=0.95),
        rf_link=RFLinkConfig(tx_power_w=12.0, frequency_hz=8.4e9, data_rate_bps=2.0e6),
    )
    dialog = SpacecraftEditorDialog(config=existing)
    qtbot.addWidget(dialog)

    assert dialog.power_group.isChecked()
    assert dialog.rf_link_group.isChecked()

    got = dialog.to_dataclass()
    assert got.power == existing.power
    assert got.rf_link == existing.rf_link


def test_dialog_station_keeping_defaults_to_none(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    assert not dialog.station_keeping_group.isChecked()
    sc = dialog.to_dataclass()
    assert sc.station_keeping is None


def test_dialog_builds_station_keeping_config_when_group_checked(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    dialog.station_keeping_group.setChecked(True)
    dialog.sk_target_altitude_km.setValue(600.0)
    dialog.sk_deadband_km.setValue(2.0)
    dialog.sk_thrust_n.setValue(0.02)
    dialog.sk_isp_s.setValue(1600.0)
    dialog.sk_propellant_kg.setValue(3.5)
    dialog.sk_eclipse_sunlit_threshold.setValue(0.95)

    sc = dialog.to_dataclass()
    assert sc.station_keeping is not None
    assert sc.station_keeping.target_altitude_km == 600.0
    assert sc.station_keeping.deadband_km == 2.0
    assert sc.station_keeping.thrust_n == 0.02
    assert sc.station_keeping.isp_s == 1600.0
    assert sc.station_keeping.propellant_kg == 3.5
    assert sc.station_keeping.eclipse_sunlit_threshold == 0.95


def test_dialog_round_trips_station_keeping(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig, StationKeepingConfig

    existing = SpacecraftConfig(
        name="sat-sk",
        orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]),
        station_keeping=StationKeepingConfig(target_altitude_km=550.0, deadband_km=1.5, thrust_n=0.015,
                                              isp_s=1550.0, propellant_kg=2.5),
    )
    dialog = SpacecraftEditorDialog(config=existing)
    qtbot.addWidget(dialog)

    assert dialog.station_keeping_group.isChecked()

    got = dialog.to_dataclass()
    assert got.station_keeping == existing.station_keeping


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
