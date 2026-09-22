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

"""ScenarioEditorWidget: the full scenario form, composing every
sub-editor into one :class:`schema.scenario.Scenario`. This is the single
place that assembles/disassembles a ``Scenario`` from widget state --
``MainWindow`` never touches individual fields itself.

Only edits what ``engine.service.SimulationService`` actually consumes
PLUS ground stations (pure scenario data, see
``ground_station_editor.py``'s docstring for why that's different from
sensors/actuators/FSW modes, which this editor deliberately omits).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..schema.scenario import (
    SUPPORTED_CENTRAL_BODIES,
    SUPPORTED_INTEGRATORS,
    GravityConfig,
    MonteCarloConfig,
    Scenario,
    ScenarioValidationError,
    SimSettings,
    SpaceWeatherConfig,
)
from .ground_station_editor import GroundStationListWidget
from .monte_carlo_editor import MonteCarloGroupWidget
from .spacecraft_editor import SpacecraftListWidget


class ScenarioEditorWidget(QWidget):
    """Emits :attr:`changed` on any edit anywhere in the form (including
    inside the spacecraft/ground-station dialogs), so :class:`MainWindow`
    can track an unsaved-changes flag and re-run live validation.
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)

        layout.addWidget(self._build_identity_group())
        layout.addWidget(self._build_gravity_group())
        layout.addWidget(self._build_sim_settings_group())
        layout.addWidget(self._build_space_weather_group())
        layout.addWidget(self._build_spacecraft_group())
        layout.addWidget(self._build_ground_station_group())
        layout.addWidget(self._build_monte_carlo_group())
        layout.addStretch(1)

        self.validation_label = QLabel()
        self.validation_label.setWordWrap(True)
        outer_layout.addWidget(self.validation_label)

        self.changed.connect(self.revalidate)
        self.revalidate()

    # -- construction ------------------------------------------------------
    def _build_identity_group(self) -> QGroupBox:
        group = QGroupBox("Scenario")
        form = QFormLayout(group)
        self.name_edit = QLineEdit("new scenario")
        self.name_edit.textChanged.connect(self.changed)
        form.addRow("Name", self.name_edit)

        self.epoch_edit = QLineEdit("2030-01-01T00:00:00")
        self.epoch_edit.setPlaceholderText("ISO 8601 UTC, e.g. 2030-01-01T00:00:00")
        self.epoch_edit.textChanged.connect(self.changed)
        form.addRow("Epoch (UTC)", self.epoch_edit)

        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(60)
        self.description_edit.textChanged.connect(self.changed)
        form.addRow("Description", self.description_edit)
        return group

    def _build_gravity_group(self) -> QGroupBox:
        group = QGroupBox("Gravity")
        form = QFormLayout(group)

        self.central_body_combo = QComboBox()
        self.central_body_combo.addItems(SUPPORTED_CENTRAL_BODIES)
        self.central_body_combo.setCurrentText("earth")
        self.central_body_combo.currentTextChanged.connect(self._on_central_body_changed)
        self.central_body_combo.currentTextChanged.connect(self.changed)
        form.addRow("Central body", self.central_body_combo)

        self.central_body_degree_spin = QSpinBox()
        self.central_body_degree_spin.setRange(0, 360)
        self.central_body_degree_spin.setToolTip("0 = point-mass gravity. >0 = spherical harmonics (Earth only).")
        self.central_body_degree_spin.valueChanged.connect(self.changed)
        form.addRow("Spherical-harmonics degree/order (0 = point-mass)", self.central_body_degree_spin)

        self.third_body_list = QListWidget()
        self.third_body_list.setFixedHeight(90)
        self.third_body_list.itemChanged.connect(self.changed)
        form.addRow("Third-body perturbers", self.third_body_list)
        self._refresh_third_body_choices()

        return group

    def _on_central_body_changed(self, _text: str) -> None:
        self._refresh_third_body_choices()

    def _refresh_third_body_choices(self, checked: list | None = None) -> None:
        checked = set(checked) if checked is not None else self._checked_third_bodies()
        central = self.central_body_combo.currentText()
        self.third_body_list.blockSignals(True)
        self.third_body_list.clear()
        for body in SUPPORTED_CENTRAL_BODIES:
            if body == central:
                continue
            item = QListWidgetItem(body)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if body in checked else Qt.CheckState.Unchecked)
            self.third_body_list.addItem(item)
        self.third_body_list.blockSignals(False)

    def _checked_third_bodies(self) -> list:
        result = []
        for i in range(self.third_body_list.count()):
            item = self.third_body_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result

    def _build_sim_settings_group(self) -> QGroupBox:
        group = QGroupBox("Simulation settings")
        form = QFormLayout(group)

        self.duration_days_spin = QDoubleSpinBox()
        self.duration_days_spin.setRange(0.0001, 100000.0)
        self.duration_days_spin.setDecimals(4)
        self.duration_days_spin.setValue(1.0)
        self.duration_days_spin.valueChanged.connect(self.changed)
        form.addRow("Duration [days]", self.duration_days_spin)

        self.task_rate_spin = QDoubleSpinBox()
        self.task_rate_spin.setRange(0.001, 1.0e6)
        self.task_rate_spin.setDecimals(3)
        self.task_rate_spin.setValue(10.0)
        self.task_rate_spin.valueChanged.connect(self.changed)
        form.addRow("Dynamics task rate [s]", self.task_rate_spin)

        self.integrator_combo = QComboBox()
        self.integrator_combo.addItems(SUPPORTED_INTEGRATORS)
        self.integrator_combo.setCurrentText("rkf78")
        self.integrator_combo.currentTextChanged.connect(self.changed)
        form.addRow("Integrator", self.integrator_combo)

        return group

    def _build_space_weather_group(self) -> QGroupBox:
        group = QGroupBox("Space weather (drives atmospheric drag when enabled -- see README.md)")
        form = QFormLayout(group)

        self.space_weather_source_combo = QComboBox()
        self.space_weather_source_combo.addItems(["celestrak", "local_file", "synthetic"])
        self.space_weather_source_combo.currentTextChanged.connect(self._on_space_weather_source_changed)
        self.space_weather_source_combo.currentTextChanged.connect(self.changed)
        form.addRow("Source", self.space_weather_source_combo)

        local_file_row = QHBoxLayout()
        self.local_file_edit = QLineEdit()
        self.local_file_edit.textChanged.connect(self.changed)
        self.local_file_browse_button = QPushButton("Browse...")
        self.local_file_browse_button.clicked.connect(self._on_browse_local_file)
        local_file_row.addWidget(self.local_file_edit)
        local_file_row.addWidget(self.local_file_browse_button)
        form.addRow("Local file (used as fallback, or directly if source=local_file)", local_file_row)

        self._on_space_weather_source_changed(self.space_weather_source_combo.currentText())
        return group

    def _on_space_weather_source_changed(self, source: str) -> None:
        self.local_file_edit.setEnabled(source == "local_file")
        self.local_file_browse_button.setEnabled(source == "local_file")

    def _on_browse_local_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Select space-weather CSV", "", "CSV files (*.csv)")
        if path:
            self.local_file_edit.setText(path)

    def _build_spacecraft_group(self) -> QGroupBox:
        group = QGroupBox("Spacecraft")
        layout = QVBoxLayout(group)
        self.spacecraft_list = SpacecraftListWidget()
        self.spacecraft_list.set_central_body_provider(lambda: self.central_body_combo.currentText())
        self.spacecraft_list.changed.connect(self.changed)
        self.spacecraft_list.changed.connect(self._refresh_monte_carlo_spacecraft_names)
        layout.addWidget(self.spacecraft_list)
        return group

    def _build_ground_station_group(self) -> QGroupBox:
        group = QGroupBox("Ground stations")
        layout = QVBoxLayout(group)
        self.ground_station_list = GroundStationListWidget()
        self.ground_station_list.changed.connect(self.changed)
        layout.addWidget(self.ground_station_list)
        return group

    def _build_monte_carlo_group(self) -> MonteCarloGroupWidget:
        self.monte_carlo_group = MonteCarloGroupWidget()
        self.monte_carlo_group.changed.connect(self.changed)
        self._refresh_monte_carlo_spacecraft_names()
        return self.monte_carlo_group

    def _refresh_monte_carlo_spacecraft_names(self) -> None:
        self.monte_carlo_group.set_spacecraft_names([sc.name for sc in self.spacecraft_list.to_list()])

    # -- (dis)assembly -------------------------------------------------------
    def to_scenario(self) -> Scenario:
        """Raises :class:`ScenarioValidationError` with a specific message
        on anything invalid -- callers (Save, Run, the live-validation
        label) all go through this one method.
        """
        scenario = Scenario(
            name=self.name_edit.text().strip(),
            epoch_utc=self.epoch_edit.text().strip(),
            description=self.description_edit.toPlainText(),
            gravity=GravityConfig(
                central_body=self.central_body_combo.currentText(),
                central_body_degree=self.central_body_degree_spin.value(),
                third_body_perturbers=self._checked_third_bodies(),
            ),
            sim_settings=SimSettings(
                duration_days=self.duration_days_spin.value(),
                dynamics_task_rate_s=self.task_rate_spin.value(),
                integrator=self.integrator_combo.currentText(),
            ),
            space_weather=SpaceWeatherConfig(
                source=self.space_weather_source_combo.currentText(),
                local_file_path=self.local_file_edit.text().strip() or None,
            ),
            spacecraft=self.spacecraft_list.to_list(),
            ground_stations=self.ground_station_list.to_list(),
            monte_carlo=self.monte_carlo_group.to_dataclass(),
        )
        scenario.validate()
        return scenario

    def from_scenario(self, scenario: Scenario) -> None:
        self.name_edit.setText(scenario.name)
        self.epoch_edit.setText(scenario.epoch_utc)
        self.description_edit.setPlainText(scenario.description)

        self.central_body_combo.setCurrentText(scenario.gravity.central_body)
        self.central_body_degree_spin.setValue(scenario.gravity.central_body_degree)
        self._refresh_third_body_choices(scenario.gravity.third_body_perturbers)

        self.duration_days_spin.setValue(scenario.sim_settings.duration_days)
        self.task_rate_spin.setValue(scenario.sim_settings.dynamics_task_rate_s)
        self.integrator_combo.setCurrentText(scenario.sim_settings.integrator)

        self.space_weather_source_combo.setCurrentText(scenario.space_weather.source)
        self.local_file_edit.setText(scenario.space_weather.local_file_path or "")

        self.spacecraft_list.from_list(scenario.spacecraft)
        self.ground_station_list.from_list(scenario.ground_stations)
        self._refresh_monte_carlo_spacecraft_names()
        self.monte_carlo_group.from_dataclass(scenario.monte_carlo)

        self.revalidate()

    def reset_to_default(self) -> None:
        self.from_scenario(Scenario(
            name="new scenario",
            epoch_utc="2030-01-01T00:00:00",
            spacecraft=[],
        ))

    def revalidate(self) -> None:
        try:
            self.to_scenario()
        except ScenarioValidationError as exc:
            self.validation_label.setText(f"⚠ {exc}")
            self.validation_label.setStyleSheet("color: #b00020;")
        else:
            self.validation_label.setText("✓ valid")
            self.validation_label.setStyleSheet("color: #1a7a1a;")
