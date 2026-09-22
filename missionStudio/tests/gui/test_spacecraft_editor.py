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


def test_dialog_phasing_keeping_defaults_to_none(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    assert not dialog.phasing_keeping_group.isChecked()
    sc = dialog.to_dataclass()
    assert sc.phasing_keeping is None


def test_dialog_phasing_keeping_chief_combo_lists_other_spacecraft(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog(other_spacecraft_names=["chief", "follower-2"])
    qtbot.addWidget(dialog)
    dialog.phasing_keeping_group.setChecked(True)  # a checkable QGroupBox disables its children while unchecked
    assert dialog.pk_chief_combo.isEnabled()
    names = {dialog.pk_chief_combo.itemData(i) for i in range(dialog.pk_chief_combo.count())}
    assert names == {"chief", "follower-2"}


def test_dialog_phasing_keeping_disabled_combo_with_no_other_spacecraft(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog()
    qtbot.addWidget(dialog)
    dialog.phasing_keeping_group.setChecked(True)  # isolate this widget's OWN disabled state from the group's
    assert not dialog.pk_chief_combo.isEnabled()
    assert dialog.pk_chief_combo.currentData() is None


def test_dialog_phasing_keeping_requires_a_selectable_chief(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog
    from missionstudio.schema.scenario import ScenarioValidationError

    dialog = SpacecraftEditorDialog()  # no other_spacecraft_names -- combo disabled
    qtbot.addWidget(dialog)
    dialog.station_keeping_group.setChecked(True)
    dialog.phasing_keeping_group.setChecked(True)
    with pytest.raises(ScenarioValidationError, match="no chief spacecraft is selectable"):
        dialog.to_dataclass()


def test_dialog_builds_phasing_keeping_config_when_group_checked(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog

    dialog = SpacecraftEditorDialog(other_spacecraft_names=["chief"])
    qtbot.addWidget(dialog)
    dialog.station_keeping_group.setChecked(True)  # phasing_keeping requires this
    dialog.phasing_keeping_group.setChecked(True)
    dialog.pk_target_separation_edit.setText("1000, 500, 100")
    dialog.pk_reconfiguration_interval_days.setValue(60.0)
    dialog.pk_tolerance_fraction.setValue(0.2)
    dialog.pk_restore_tolerance_fraction.setValue(0.05)
    dialog.pk_correction_window_days.setValue(14.0)
    dialog.pk_max_drift_days.setValue(45.0)
    dialog.pk_max_delta_sma_km.setValue(2.0)

    sc = dialog.to_dataclass()
    assert sc.phasing_keeping is not None
    assert sc.phasing_keeping.chief_spacecraft == "chief"
    assert sc.phasing_keeping.target_separation_km == [1000.0, 500.0, 100.0]
    assert sc.phasing_keeping.reconfiguration_interval_days == 60.0
    assert sc.phasing_keeping.tolerance_fraction == 0.2
    assert sc.phasing_keeping.restore_tolerance_fraction == 0.05
    assert sc.phasing_keeping.correction_window_days == 14.0
    assert sc.phasing_keeping.max_drift_days == 45.0
    assert sc.phasing_keeping.max_delta_semi_major_axis_km == 2.0


def test_dialog_phasing_keeping_rejects_malformed_separation_list(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog
    from missionstudio.schema.scenario import ScenarioValidationError

    dialog = SpacecraftEditorDialog(other_spacecraft_names=["chief"])
    qtbot.addWidget(dialog)
    dialog.station_keeping_group.setChecked(True)
    dialog.phasing_keeping_group.setChecked(True)
    dialog.pk_target_separation_edit.setText("not, a, number")
    with pytest.raises(ScenarioValidationError, match="comma-separated numbers"):
        dialog.to_dataclass()


def test_dialog_round_trips_phasing_keeping(qtbot):
    from missionstudio.gui.spacecraft_editor import SpacecraftEditorDialog
    from missionstudio.schema.scenario import (
        OrbitIC,
        PhasingKeepingConfig,
        SpacecraftConfig,
        StationKeepingConfig,
    )

    existing = SpacecraftConfig(
        name="sat-follower",
        orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]),
        station_keeping=StationKeepingConfig(target_altitude_km=550.0, deadband_km=1.5, thrust_n=0.015,
                                              isp_s=1550.0, propellant_kg=2.5),
        phasing_keeping=PhasingKeepingConfig(chief_spacecraft="chief", target_separation_km=[250.0, 100.0],
                                              reconfiguration_interval_days=45.0),
    )
    dialog = SpacecraftEditorDialog(config=existing, other_spacecraft_names=["chief"])
    qtbot.addWidget(dialog)

    assert dialog.phasing_keeping_group.isChecked()
    assert dialog.pk_chief_combo.currentData() == "chief"
    assert dialog.pk_target_separation_edit.text() == "250, 100"

    got = dialog.to_dataclass()
    assert got.phasing_keeping == existing.phasing_keeping


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


def test_list_widget_generate_constellation_appends_generated_spacecraft(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog
    from missionstudio.gui.spacecraft_editor import SpacecraftListWidget
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig

    lw = SpacecraftListWidget()
    qtbot.addWidget(lw)
    lw.from_list([SpacecraftConfig(
        name="template-sat", dry_mass_kg=42.0,
        orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]),
    )])

    def fake_exec(self):
        self.total_satellites.setValue(4)
        self.num_planes.setValue(2)
        self.phasing_factor.setValue(0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(WalkerConstellationDialog, "exec", fake_exec)
    changed_calls = []
    lw.changed.connect(lambda: changed_calls.append(1))

    lw._on_generate_constellation()

    configs = lw.to_list()
    assert len(configs) == 1 + 4  # original template + 4 generated
    generated = [c for c in configs if c.name != "template-sat"]
    assert len(generated) == 4
    assert all(c.dry_mass_kg == 42.0 for c in generated)  # cloned from the template
    assert len(changed_calls) == 1


def test_list_widget_generate_constellation_uses_default_template_when_list_empty(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog
    from missionstudio.gui.spacecraft_editor import SpacecraftListWidget

    lw = SpacecraftListWidget()
    qtbot.addWidget(lw)

    def fake_exec(self):
        self.total_satellites.setValue(2)
        self.num_planes.setValue(1)
        self.phasing_factor.setValue(0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(WalkerConstellationDialog, "exec", fake_exec)
    lw._on_generate_constellation()
    assert len(lw.to_list()) == 2


def test_list_widget_generate_constellation_reports_name_collision(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox

    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog
    from missionstudio.gui.spacecraft_editor import SpacecraftListWidget
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig

    lw = SpacecraftListWidget()
    qtbot.addWidget(lw)
    # This name collides with the first satellite generate_walker_constellation
    # would produce for a 1-satellite/1-plane request with the default prefix.
    lw.from_list([SpacecraftConfig(
        name="sat-01-01",
        orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0]),
    )])

    def fake_exec(self):
        self.total_satellites.setValue(1)
        self.num_planes.setValue(1)
        self.phasing_factor.setValue(0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(WalkerConstellationDialog, "exec", fake_exec)
    critical_calls = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: critical_calls.append(a)))

    lw._on_generate_constellation()
    assert len(lw.to_list()) == 1  # nothing added
    assert len(critical_calls) == 1


def test_list_widget_generate_constellation_cancel_does_nothing(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog
    from missionstudio.gui.spacecraft_editor import SpacecraftListWidget

    lw = SpacecraftListWidget()
    qtbot.addWidget(lw)
    monkeypatch.setattr(WalkerConstellationDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    lw._on_generate_constellation()
    assert lw.to_list() == []


def test_list_widget_uses_central_body_provider(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog
    from missionstudio.gui.spacecraft_editor import SpacecraftListWidget

    lw = SpacecraftListWidget()
    qtbot.addWidget(lw)
    lw.set_central_body_provider(lambda: "mars")

    captured = {}

    def fake_exec(self):
        captured["central_body"] = self.to_request().central_body
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(WalkerConstellationDialog, "exec", fake_exec)
    lw._on_generate_constellation()
    assert captured["central_body"] == "mars"
