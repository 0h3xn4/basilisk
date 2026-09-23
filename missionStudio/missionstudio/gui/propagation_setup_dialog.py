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

"""PropagationSetupDialog: one dedicated window for everything that governs
HOW a scenario's orbits propagate -- central body, gravity model (point
-mass vs. spherical harmonics, third-body point-mass perturbers), the
integrator/step/duration, and the space-weather source that drives
atmospheric drag. Previously these lived as three separate, always-visible
group boxes inline in the main scenario form; user feedback specifically
asked for "a full and comprehensive propagate setup window" plus the
ability to switch each perturbation on/off individually.

Every perturbation this app actually wires up in ``engine.service`` gets
its own explicit enable control here:

* spherical-harmonics gravity -- ``enable_harmonics_check`` (new; see its
  own comment below for why it's a GUI-only concept, not a new schema
  field)
* third-body point-mass gravity -- one checkbox per body in
  ``third_body_list`` (existing, moved here unchanged)
* atmospheric drag / solar radiation pressure -- these are PER
  -SPACECRAFT, not scenario-wide (a spacecraft's own cross-section/
  coefficient are needed either way), so they stay on
  ``gui.spacecraft_editor.SpacecraftEditorDialog``'s "Orbit / mass" tab
  (``enable_drag``/``enable_srp``) -- already present, and already
  reachable in "orbit_only" (cannonball) mode since that tab is never
  hidden for that mode.

Construct with the scenario's current ``GravityConfig``/``SimSettings``/
``SpaceWeatherConfig``, then read back the (possibly unchanged) values via
:meth:`to_gravity`/:meth:`to_sim_settings`/:meth:`to_space_weather` after
``exec()`` returns ``Accepted``. Never mutates the dataclasses it was
constructed with -- ``gui.scenario_editor.ScenarioEditorWidget`` only
replaces its own stored copies once the user actually clicks OK.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..schema.scenario import (
    SUPPORTED_CENTRAL_BODIES,
    SUPPORTED_INTEGRATORS,
    GravityConfig,
    ScenarioValidationError,
    SimSettings,
    SpaceWeatherConfig,
)

# The minimum spherical-harmonics degree/order that's actually meaningful
# ("spherical harmonics" starting below this is just point-mass again) --
# used only as a friendly default when the user checks the enable box
# while the degree spinner is still at 0, never enforced as a hard floor
# (GravityConfig.validate() only requires >= 0).
_DEFAULT_HARMONICS_DEGREE = 2


class PropagationSetupDialog(QDialog):
    def __init__(self, gravity: GravityConfig, sim_settings: SimSettings, space_weather: SpaceWeatherConfig,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Propagation setup")

        layout = QVBoxLayout(self)
        intro_label = QLabel(
            "Everything that governs how this scenario's orbits propagate: the gravity model, "
            "which perturbations are active, the numerical integrator, and the space-weather data "
            "atmospheric drag uses."
        )
        intro_label.setWordWrap(True)
        # A word-wrapped QLabel's sizeHint() reports the width needed to
        # lay the text out on ONE line unless something else constrains
        # it -- without this cap, this label alone stretched the whole
        # dialog (everything else here just fills whatever width the
        # layout ends up with) to ~1360px wide. Caught by actually
        # rendering the dialog and looking at it, not from reading the
        # layout code -- same class of bug as SpacecraftEditorDialog's
        # tab-sizing issue elsewhere in this app.
        intro_label.setMaximumWidth(560)
        layout.addWidget(intro_label)

        layout.addWidget(self._build_gravity_group(gravity))
        layout.addWidget(self._build_sim_settings_group(sim_settings))
        layout.addWidget(self._build_space_weather_group(space_weather))
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- construction ---------------------------------------------------------
    def _build_gravity_group(self, gravity: GravityConfig) -> QGroupBox:
        group = QGroupBox("Gravity")
        form = QFormLayout(group)

        self.central_body_combo = QComboBox()
        self.central_body_combo.addItems(SUPPORTED_CENTRAL_BODIES)
        self.central_body_combo.setCurrentText(gravity.central_body)
        self.central_body_combo.currentTextChanged.connect(self._on_central_body_changed)
        form.addRow("Central body", self.central_body_combo)

        # Spherical-harmonics gravity: an explicit enable checkbox, SEPARATE
        # from the degree/order value itself -- schema.scenario.GravityConfig
        # still only has ONE field for this (central_body_degree == 0 means
        # point-mass, exactly as before; no schema/migration change), but a
        # bare spin box with no enable control meant unchecking it required
        # zeroing out (and losing) whatever degree/order the user had typed.
        # to_gravity() below folds this checkbox back into that one field.
        self.enable_harmonics_check = QCheckBox("Enable spherical-harmonics gravity (Earth only)")
        self.enable_harmonics_check.setChecked(gravity.central_body_degree > 0)
        self.enable_harmonics_check.toggled.connect(self._on_harmonics_toggled)
        form.addRow(self.enable_harmonics_check)

        self.central_body_degree_spin = QSpinBox()
        self.central_body_degree_spin.setRange(0, 360)
        self.central_body_degree_spin.setValue(
            gravity.central_body_degree if gravity.central_body_degree > 0 else _DEFAULT_HARMONICS_DEGREE
        )
        form.addRow("Degree/order", self.central_body_degree_spin)

        self.third_body_list = QListWidget()
        self.third_body_list.setFixedHeight(130)
        form.addRow("Third-body perturbers", self.third_body_list)
        self._refresh_third_body_choices(gravity.third_body_perturbers)

        self._on_central_body_changed(gravity.central_body)  # applies the Earth-only harmonics gate immediately
        return group

    def _on_central_body_changed(self, text: str) -> None:
        self._refresh_third_body_choices()
        is_earth = text == "earth"
        # Spherical harmonics here is Earth-only (engine.service.build()
        # only has a gravity-field data file for Earth -- GGM03S -- and
        # raises a clear SimulationServiceError for any other central body
        # with central_body_degree > 0). Disabling it here means the GUI
        # can never construct that invalid combination in the first place,
        # rather than letting the user discover it only when a run fails.
        self.enable_harmonics_check.setEnabled(is_earth)
        if not is_earth:
            self.enable_harmonics_check.setChecked(False)
        self.central_body_degree_spin.setEnabled(is_earth and self.enable_harmonics_check.isChecked())
        tooltip = "" if is_earth else "Spherical-harmonics gravity is only wired up for Earth (GGM03S data)."
        self.enable_harmonics_check.setToolTip(tooltip)

    def _on_harmonics_toggled(self, checked: bool) -> None:
        self.central_body_degree_spin.setEnabled(checked)
        if checked and self.central_body_degree_spin.value() == 0:
            self.central_body_degree_spin.setValue(_DEFAULT_HARMONICS_DEGREE)

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

    def _build_sim_settings_group(self, sim_settings: SimSettings) -> QGroupBox:
        group = QGroupBox("Simulation settings")
        form = QFormLayout(group)

        self.duration_days_spin = QDoubleSpinBox()
        self.duration_days_spin.setRange(0.0001, 100000.0)
        self.duration_days_spin.setDecimals(4)
        self.duration_days_spin.setValue(sim_settings.duration_days)
        form.addRow("Duration [days]", self.duration_days_spin)

        self.task_rate_spin = QDoubleSpinBox()
        self.task_rate_spin.setRange(0.001, 1.0e6)
        self.task_rate_spin.setDecimals(3)
        self.task_rate_spin.setValue(sim_settings.dynamics_task_rate_s)
        form.addRow("Dynamics task rate [s]", self.task_rate_spin)

        self.integrator_combo = QComboBox()
        self.integrator_combo.addItems(SUPPORTED_INTEGRATORS)
        self.integrator_combo.setCurrentText(sim_settings.integrator)
        form.addRow("Integrator", self.integrator_combo)

        return group

    def _build_space_weather_group(self, space_weather: SpaceWeatherConfig) -> QGroupBox:
        group = QGroupBox("Space weather (drives atmospheric drag)")
        form = QFormLayout(group)

        self.space_weather_source_combo = QComboBox()
        self.space_weather_source_combo.addItems(["celestrak", "local_file", "synthetic"])
        self.space_weather_source_combo.setCurrentText(space_weather.source)
        self.space_weather_source_combo.currentTextChanged.connect(self._on_space_weather_source_changed)
        form.addRow("Source", self.space_weather_source_combo)

        local_file_row = QHBoxLayout()
        self.local_file_edit = QLineEdit(space_weather.local_file_path or "")
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

    # -- (dis)assembly -------------------------------------------------------
    def to_gravity(self) -> GravityConfig:
        return GravityConfig(
            central_body=self.central_body_combo.currentText(),
            central_body_degree=(
                self.central_body_degree_spin.value() if self.enable_harmonics_check.isChecked() else 0
            ),
            third_body_perturbers=self._checked_third_bodies(),
        )

    def to_sim_settings(self) -> SimSettings:
        return SimSettings(
            duration_days=self.duration_days_spin.value(),
            dynamics_task_rate_s=self.task_rate_spin.value(),
            integrator=self.integrator_combo.currentText(),
        )

    def to_space_weather(self) -> SpaceWeatherConfig:
        return SpaceWeatherConfig(
            source=self.space_weather_source_combo.currentText(),
            local_file_path=self.local_file_edit.text().strip() or None,
        )

    def _on_accept(self) -> None:
        try:
            self.to_gravity().validate()
            self.to_sim_settings().validate()
            self.to_space_weather().validate()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Invalid propagation setup", str(exc))
            return
        self.accept()
