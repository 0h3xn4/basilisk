#
#  ISC License
#
#  Copyright (c) 2026, Autonomous Vehicle Systems Lab, University of Colorado at Boulder
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
#  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
#  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
#  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
#  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
#  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
#  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#

"""Spacecraft list + per-spacecraft editor dialog.

Phase 1 scope note (superseded): editing used to only touch the fields
``engine.service.SimulationService`` consumed at the time (name, orbit,
dry mass, inertia, initial attitude/rate) and silently DROPPED
``sensors``/``actuators``/``fsw_mode``/``fsw_params``/``control_params``
on every edit -- ``to_dataclass()`` built a brand new ``SpacecraftConfig``
without passing them through. That was fine as long as nothing set them
(no Phase 1 editor did), but it was a latent bug the moment anything else
did (a hand-edited scenario file, or this Phase 2 editor itself re-editing
a spacecraft). Fixed now: ``to_dataclass()`` takes the ORIGINAL config (if
editing one) and carries those fields through unless this dialog's own
sensor/actuator/FSW editors changed them.

drag/SRP are still not editable here -- ``engine.service`` still doesn't
wire them up (see that module's docstring) -- so there is deliberately
still no UI for them, same reasoning as before.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..schema.scenario import (
    ActuatorConfig,
    OrbitIC,
    PowerConfig,
    RFLinkConfig,
    ScenarioValidationError,
    SensorConfig,
    SpacecraftConfig,
    StationKeepingConfig,
    SUPPORTED_ACTUATOR_KINDS,
    SUPPORTED_FSW_MODES,
    SUPPORTED_SENSOR_KINDS,
)
from .orbit_ic_widget import OrbitIcWidget
from .sensor_actuator_editor import SensorActuatorListWidget

_FSW_MODE_NONE_LABEL = "(none -- no attitude control)"


def _spin(minimum: float, maximum: float, decimals: int = 4, step: float = 1.0, value: float = 0.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    return box


class SpacecraftEditorDialog(QDialog):
    """Edits one :class:`SpacecraftConfig` in place. Construct with an
    existing config to edit it, or ``None`` for a fresh default.
    """

    def __init__(self, config: SpacecraftConfig | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Spacecraft" if config is None else f"Spacecraft: {config.name}")

        outer_layout = QVBoxLayout(self)
        tabs = QTabWidget()
        outer_layout.addWidget(tabs)

        orbit_tab = QWidget()
        layout = QVBoxLayout(orbit_tab)

        top_form = QFormLayout()
        self.name_edit = QLineEdit(config.name if config else "sat-1")
        top_form.addRow("Name", self.name_edit)
        self.dry_mass_kg = _spin(0.001, 1.0e6, decimals=3, step=10.0, value=config.dry_mass_kg if config else 100.0)
        top_form.addRow("Dry mass [kg]", self.dry_mass_kg)
        layout.addLayout(top_form)

        orbit_group = QGroupBox("Orbit initial condition")
        orbit_layout = QVBoxLayout(orbit_group)
        self.orbit_widget = OrbitIcWidget()
        orbit_layout.addWidget(self.orbit_widget)
        layout.addWidget(orbit_group)

        inertia_group = QGroupBox("Principal moments of inertia [kg*m^2] (off-diagonal terms fixed at 0)")
        inertia_form = QFormLayout(inertia_group)
        inertia0 = config.inertia_kg_m2 if config else [10.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0]
        self.ixx = _spin(0.001, 1.0e8, decimals=3, step=1.0, value=inertia0[0])
        self.iyy = _spin(0.001, 1.0e8, decimals=3, step=1.0, value=inertia0[4])
        self.izz = _spin(0.001, 1.0e8, decimals=3, step=1.0, value=inertia0[8])
        inertia_form.addRow("Ixx", self.ixx)
        inertia_form.addRow("Iyy", self.iyy)
        inertia_form.addRow("Izz", self.izz)
        layout.addWidget(inertia_group)

        attitude_group = QGroupBox("Initial attitude / body rate")
        attitude_form = QFormLayout(attitude_group)
        sigma0 = config.sigma_bn_init if config else [0.0, 0.0, 0.0]
        omega0 = config.omega_bn_b_init_rad_s if config else [0.0, 0.0, 0.0]
        self.sigma1 = _spin(-1.0, 1.0, decimals=6, step=0.01, value=sigma0[0])
        self.sigma2 = _spin(-1.0, 1.0, decimals=6, step=0.01, value=sigma0[1])
        self.sigma3 = _spin(-1.0, 1.0, decimals=6, step=0.01, value=sigma0[2])
        self.omega1 = _spin(-10.0, 10.0, decimals=6, step=0.001, value=omega0[0])
        self.omega2 = _spin(-10.0, 10.0, decimals=6, step=0.001, value=omega0[1])
        self.omega3 = _spin(-10.0, 10.0, decimals=6, step=0.001, value=omega0[2])
        attitude_form.addRow("sigma_BN [-] (3 components)",
                              _hbox(self.sigma1, self.sigma2, self.sigma3))
        attitude_form.addRow("omega_BN_B [rad/s] (3 components)",
                              _hbox(self.omega1, self.omega2, self.omega3))
        layout.addWidget(attitude_group)

        if config is not None:
            self.orbit_widget.from_dataclass(config.orbit)

        tabs.addTab(orbit_tab, "Orbit / mass")

        # -- Sensors / actuators tab (Phase 2) --------------------------------
        sensors_tab = QWidget()
        sensors_layout = QVBoxLayout(sensors_tab)
        sensors_layout.addWidget(QLabel("Sensors"))
        self.sensor_list = SensorActuatorListWidget(SensorConfig, SUPPORTED_SENSOR_KINDS)
        sensors_layout.addWidget(self.sensor_list)
        sensors_layout.addWidget(QLabel("Actuators"))
        self.actuator_list = SensorActuatorListWidget(ActuatorConfig, SUPPORTED_ACTUATOR_KINDS)
        sensors_layout.addWidget(self.actuator_list)
        if config is not None:
            self.sensor_list.from_list(config.sensors)
            self.actuator_list.from_list(config.actuators)
        tabs.addTab(sensors_tab, "Sensors / actuators")

        # -- Attitude control (FSW) tab (Phase 2) -----------------------------
        fsw_tab = QWidget()
        fsw_layout = QVBoxLayout(fsw_tab)
        fsw_form = QFormLayout()
        self.fsw_mode_combo = QComboBox()
        self.fsw_mode_combo.addItem(_FSW_MODE_NONE_LABEL, userData=None)
        for mode in SUPPORTED_FSW_MODES:
            self.fsw_mode_combo.addItem(mode, userData=mode)
        fsw_form.addRow("FSW mode", self.fsw_mode_combo)
        fsw_layout.addLayout(fsw_form)
        fsw_layout.addWidget(QLabel(
            "FSW params (JSON object) -- e.g. {\"sigma_R0N\": [0,0,0]} for inertial3D, "
            "{\"target_ground_station\": \"name\", \"pHat_B\": [0,0,1]} for locationPointing"
        ))
        self.fsw_params_edit = QPlainTextEdit(json.dumps(config.fsw_params if config else {}, indent=2))
        fsw_layout.addWidget(self.fsw_params_edit)
        fsw_layout.addWidget(QLabel("Control gains (JSON object) -- e.g. {\"K\": 3.5, \"P\": 30.0}"))
        self.control_params_edit = QPlainTextEdit(json.dumps(config.control_params if config else {}, indent=2))
        fsw_layout.addWidget(self.control_params_edit)
        if config is not None and config.fsw_mode is not None:
            index = self.fsw_mode_combo.findData(config.fsw_mode)
            if index >= 0:
                self.fsw_mode_combo.setCurrentIndex(index)
        tabs.addTab(fsw_tab, "Attitude control (FSW)")

        # -- Power budget / RF link budget tab (Phase 4) ----------------------
        # Both are OFF by default (unchecked group box) -- turning one on is
        # the only input needed beyond the numbers themselves; engine.service
        # (power) / engine.link_budget (RF) do the rest. See PowerConfig's
        # and RFLinkConfig's docstrings for exactly what each does and
        # doesn't affect.
        power_tab = QWidget()
        power_layout = QVBoxLayout(power_tab)

        power0 = config.power if config else None
        self.power_group = QGroupBox("Power budget (solar panel + battery)")
        self.power_group.setCheckable(True)
        self.power_group.setChecked(power0 is not None)
        power_form = QFormLayout(self.power_group)
        self.panel_area_m2 = _spin(0.001, 1.0e4, decimals=3, step=0.1,
                                    value=power0.panel_area_m2 if power0 else 1.2)
        self.panel_efficiency = _spin(0.001, 1.0, decimals=4, step=0.01,
                                       value=power0.panel_efficiency if power0 else 0.29)
        panel_normal0 = power0.panel_normal_b if power0 else [0.0, 0.0, 1.0]
        self.panel_normal_x = _spin(-1.0, 1.0, decimals=4, step=0.1, value=panel_normal0[0])
        self.panel_normal_y = _spin(-1.0, 1.0, decimals=4, step=0.1, value=panel_normal0[1])
        self.panel_normal_z = _spin(-1.0, 1.0, decimals=4, step=0.1, value=panel_normal0[2])
        self.bus_idle_power_w = _spin(0.0, 1.0e5, decimals=2, step=1.0,
                                       value=power0.bus_idle_power_w if power0 else 25.0)
        self.battery_capacity_wh = _spin(0.001, 1.0e6, decimals=2, step=10.0,
                                          value=power0.battery_capacity_wh if power0 else 120.0)
        self.battery_initial_soc = _spin(0.0, 1.0, decimals=4, step=0.05,
                                          value=power0.battery_initial_soc if power0 else 0.9)
        power_form.addRow("Panel area [m^2]", self.panel_area_m2)
        power_form.addRow("Panel efficiency [-]", self.panel_efficiency)
        power_form.addRow("Panel normal (body frame, 3 components)",
                           _hbox(self.panel_normal_x, self.panel_normal_y, self.panel_normal_z))
        power_form.addRow("Bus idle power [W]", self.bus_idle_power_w)
        power_form.addRow("Battery capacity [W*hr]", self.battery_capacity_wh)
        power_form.addRow("Battery initial state of charge [-]", self.battery_initial_soc)
        power_layout.addWidget(self.power_group)

        sk0 = config.station_keeping if config else None
        self.station_keeping_group = QGroupBox("Station keeping (altitude maintenance, delta-V + fuel tracking)")
        self.station_keeping_group.setCheckable(True)
        self.station_keeping_group.setChecked(sk0 is not None)
        sk_form = QFormLayout(self.station_keeping_group)
        self.sk_target_altitude_km = _spin(0.001, 1.0e6, decimals=3, step=10.0,
                                            value=sk0.target_altitude_km if sk0 else 500.0)
        self.sk_deadband_km = _spin(0.001, 1.0e5, decimals=3, step=0.5, value=sk0.deadband_km if sk0 else 1.0)
        self.sk_thrust_n = _spin(1.0e-6, 1.0e4, decimals=6, step=0.001, value=sk0.thrust_n if sk0 else 0.01)
        self.sk_isp_s = _spin(1.0, 1.0e5, decimals=1, step=10.0, value=sk0.isp_s if sk0 else 1500.0)
        self.sk_propellant_kg = _spin(0.0, 1.0e5, decimals=3, step=0.1, value=sk0.propellant_kg if sk0 else 2.0)
        self.sk_eclipse_sunlit_threshold = _spin(0.001, 1.0, decimals=4, step=0.01,
                                                   value=sk0.eclipse_sunlit_threshold if sk0 else 0.99)
        sk_form.addRow("Target altitude [km]", self.sk_target_altitude_km)
        sk_form.addRow("Deadband below target [km]", self.sk_deadband_km)
        sk_form.addRow("Reboost thrust [N]", self.sk_thrust_n)
        sk_form.addRow("Reboost thruster Isp [s]", self.sk_isp_s)
        sk_form.addRow("Propellant available [kg]", self.sk_propellant_kg)
        sk_form.addRow("Eclipse sunlit threshold [-]", self.sk_eclipse_sunlit_threshold)
        power_layout.addWidget(self.station_keeping_group)

        rf_link0 = config.rf_link if config else None
        self.rf_link_group = QGroupBox("Downlink RF link budget (margin ESTIMATE only)")
        self.rf_link_group.setCheckable(True)
        self.rf_link_group.setChecked(rf_link0 is not None)
        rf_form = QFormLayout(self.rf_link_group)
        self.tx_power_w = _spin(0.001, 1.0e4, decimals=3, step=1.0, value=rf_link0.tx_power_w if rf_link0 else 15.0)
        self.frequency_ghz = _spin(0.001, 1.0e3, decimals=6, step=0.1,
                                    value=(rf_link0.frequency_hz / 1.0e9) if rf_link0 else 8.2)
        self.data_rate_mbps = _spin(1.0e-6, 1.0e6, decimals=6, step=1.0,
                                     value=(rf_link0.data_rate_bps / 1.0e6) if rf_link0 else 1.0)
        self.tx_antenna_gain_dbi = _spin(-50.0, 100.0, decimals=2, step=1.0,
                                          value=rf_link0.tx_antenna_gain_dbi if rf_link0 else 6.0)
        self.rf_implementation_loss_db = _spin(0.0, 50.0, decimals=2, step=0.5,
                                                 value=rf_link0.implementation_loss_db if rf_link0 else 2.0)
        self.required_ebno_db = _spin(-50.0, 50.0, decimals=2, step=0.5,
                                       value=rf_link0.required_ebno_db if rf_link0 else 6.0)
        rf_form.addRow("TX power [W]", self.tx_power_w)
        rf_form.addRow("Carrier frequency [GHz]", self.frequency_ghz)
        rf_form.addRow("Data rate [Mbit/s]", self.data_rate_mbps)
        rf_form.addRow("TX antenna gain [dBi]", self.tx_antenna_gain_dbi)
        rf_form.addRow("Implementation/pointing loss [dB]", self.rf_implementation_loss_db)
        rf_form.addRow("Required Eb/N0 [dB]", self.required_ebno_db)
        power_layout.addWidget(self.rf_link_group)
        power_layout.addStretch(1)

        tabs.addTab(power_tab, "Power / propulsion / link budget")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer_layout.addWidget(buttons)

    def _on_accept(self) -> None:
        try:
            self.to_dataclass()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Invalid spacecraft", str(exc))
            return
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid JSON", str(exc))
            return
        self.accept()

    def _parse_json_object(self, edit: QPlainTextEdit, field_label: str) -> dict:
        text = edit.toPlainText().strip() or "{}"
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_label} is not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{field_label} must be a JSON object")
        return value

    def to_dataclass(self) -> SpacecraftConfig:
        name = self.name_edit.text().strip()
        config = SpacecraftConfig(
            name=name,
            orbit=self.orbit_widget.to_dataclass(),
            dry_mass_kg=self.dry_mass_kg.value(),
            inertia_kg_m2=[
                self.ixx.value(), 0.0, 0.0,
                0.0, self.iyy.value(), 0.0,
                0.0, 0.0, self.izz.value(),
            ],
            sigma_bn_init=[self.sigma1.value(), self.sigma2.value(), self.sigma3.value()],
            omega_bn_b_init_rad_s=[self.omega1.value(), self.omega2.value(), self.omega3.value()],
            sensors=self.sensor_list.to_list(),
            actuators=self.actuator_list.to_list(),
            fsw_mode=self.fsw_mode_combo.currentData(),
            fsw_params=self._parse_json_object(self.fsw_params_edit, "FSW params"),
            control_params=self._parse_json_object(self.control_params_edit, "Control gains"),
            power=self._power_to_dataclass(),
            rf_link=self._rf_link_to_dataclass(),
            station_keeping=self._station_keeping_to_dataclass(),
        )
        config.validate()  # raises ScenarioValidationError with a specific message on anything bad
        return config

    def _station_keeping_to_dataclass(self) -> StationKeepingConfig | None:
        if not self.station_keeping_group.isChecked():
            return None
        return StationKeepingConfig(
            target_altitude_km=self.sk_target_altitude_km.value(),
            deadband_km=self.sk_deadband_km.value(),
            thrust_n=self.sk_thrust_n.value(),
            isp_s=self.sk_isp_s.value(),
            propellant_kg=self.sk_propellant_kg.value(),
            eclipse_sunlit_threshold=self.sk_eclipse_sunlit_threshold.value(),
        )

    def _power_to_dataclass(self) -> PowerConfig | None:
        if not self.power_group.isChecked():
            return None
        return PowerConfig(
            panel_area_m2=self.panel_area_m2.value(),
            panel_efficiency=self.panel_efficiency.value(),
            panel_normal_b=[self.panel_normal_x.value(), self.panel_normal_y.value(), self.panel_normal_z.value()],
            bus_idle_power_w=self.bus_idle_power_w.value(),
            battery_capacity_wh=self.battery_capacity_wh.value(),
            battery_initial_soc=self.battery_initial_soc.value(),
        )

    def _rf_link_to_dataclass(self) -> RFLinkConfig | None:
        if not self.rf_link_group.isChecked():
            return None
        return RFLinkConfig(
            tx_power_w=self.tx_power_w.value(),
            frequency_hz=self.frequency_ghz.value() * 1.0e9,
            data_rate_bps=self.data_rate_mbps.value() * 1.0e6,
            tx_antenna_gain_dbi=self.tx_antenna_gain_dbi.value(),
            implementation_loss_db=self.rf_implementation_loss_db.value(),
            required_ebno_db=self.required_ebno_db.value(),
        )


def _hbox(*widgets: QWidget) -> QWidget:
    container = QWidget()
    box = QHBoxLayout(container)
    box.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        box.addWidget(w)
    return container


class SpacecraftListWidget(QWidget):
    """A list of spacecraft with Add/Edit/Remove, backed by a plain list
    of :class:`SpacecraftConfig`. Emits :attr:`changed` whenever that list
    changes (add, edit, remove, or reorder).
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._configs: list[SpacecraftConfig] = []
        # Set by the owning ScenarioEditorWidget (see set_central_body_provider)
        # so "Generate Walker constellation..." always uses this scenario's
        # ACTUAL current central body, never an independently-selectable one
        # that could silently drift out of sync with it. Falls back to
        # "earth" when unset (e.g. this widget used standalone in a test).
        self._central_body_provider = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add...")
        self.edit_button = QPushButton("Edit...")
        self.remove_button = QPushButton("Remove")
        self.generate_constellation_button = QPushButton("Generate Walker constellation...")
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.remove_button)
        button_row.addWidget(self.generate_constellation_button)
        layout.addLayout(button_row)

        self.add_button.clicked.connect(self._on_add)
        self.edit_button.clicked.connect(self._on_edit)
        self.remove_button.clicked.connect(self._on_remove)
        self.generate_constellation_button.clicked.connect(self._on_generate_constellation)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_edit())

    def set_central_body_provider(self, provider) -> None:
        """``provider`` is a zero-argument callable returning the
        scenario's current central-body name, e.g.
        ``lambda: self.central_body_combo.currentText()`` from
        ``ScenarioEditorWidget``.
        """
        self._central_body_provider = provider

    def _refresh_list(self) -> None:
        self.list_widget.clear()
        for config in self._configs:
            self.list_widget.addItem(QListWidgetItem(config.name))

    def _on_add(self) -> None:
        existing_names = {c.name for c in self._configs}
        dialog = SpacecraftEditorDialog(parent=self)
        # default name must be unique so QListWidget entries stay distinguishable
        base_name = dialog.name_edit.text()
        candidate, n = base_name, 1
        while candidate in existing_names:
            n += 1
            candidate = f"{base_name}-{n}"
        dialog.name_edit.setText(candidate)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = dialog.to_dataclass()
            if config.name in existing_names:
                QMessageBox.critical(self, "Duplicate name",
                                      f"A spacecraft named {config.name!r} already exists.")
                return
            self._configs.append(config)
            self._refresh_list()
            self.changed.emit()

    def _on_edit(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        dialog = SpacecraftEditorDialog(config=self._configs[row], parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_config = dialog.to_dataclass()
            other_names = {c.name for i, c in enumerate(self._configs) if i != row}
            if new_config.name in other_names:
                QMessageBox.critical(self, "Duplicate name",
                                      f"A spacecraft named {new_config.name!r} already exists.")
                return
            self._configs[row] = new_config
            self._refresh_list()
            self.changed.emit()

    def _on_remove(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        del self._configs[row]
        self._refresh_list()
        self.changed.emit()

    def _on_generate_constellation(self) -> None:
        from ..engine.constellation import generate_walker_constellation
        from ..schema.scenario import OrbitIC
        from .constellation_dialog import WalkerConstellationDialog

        central_body = self._central_body_provider() if self._central_body_provider else "earth"
        dialog = WalkerConstellationDialog([c.name for c in self._configs], central_body=central_body, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        request = dialog.to_request()
        template_name = dialog.selected_template_name()
        if template_name is not None:
            template = next(c for c in self._configs if c.name == template_name)
        else:
            template = SpacecraftConfig(name="template", orbit=OrbitIC(
                type="classical_elements", semi_major_axis_km=7000.0, eccentricity=0.0,
                inclination_deg=0.0, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0,
            ))

        try:
            generated = generate_walker_constellation(request, template)
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Cannot generate constellation", str(exc))
            return

        existing_names = {c.name for c in self._configs}
        colliding = [s.name for s in generated if s.name in existing_names]
        if colliding:
            QMessageBox.critical(self, "Name collision",
                                  f"Generated spacecraft name(s) already exist in this scenario: {colliding}. "
                                  "Change the name prefix and try again.")
            return

        self._configs.extend(generated)
        self._refresh_list()
        self.changed.emit()

    def to_list(self) -> list[SpacecraftConfig]:
        return list(self._configs)

    def from_list(self, configs: list[SpacecraftConfig]) -> None:
        self._configs = list(configs)
        self._refresh_list()
