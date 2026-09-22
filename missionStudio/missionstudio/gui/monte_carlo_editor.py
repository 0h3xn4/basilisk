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

"""Monte Carlo editor: :class:`DispersionListWidget` (one
:class:`schema.scenario.DispersionConfig` per row, referencing a
spacecraft by name) and :class:`MonteCarloGroupWidget` (the enable/
num_runs/thread_count/verbose settings plus that list) -- composed into
``scenario_editor.py`` the same way the space-weather/ground-station
groups are.

The dispersion editor dialog needs to know which spacecraft NAMES exist in
the scenario being edited right now (a dispersion references one by name),
so :class:`DispersionListWidget`/:class:`MonteCarloGroupWidget` expose
``set_spacecraft_names()``; ``ScenarioEditorWidget`` calls it whenever the
spacecraft list changes, same live-refresh pattern as the third-body
-perturber checklist reacting to the central-body combo.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..schema.scenario import DISPERSION_KINDS_BY_QUANTITY, DISPERSION_QUANTITIES, DispersionConfig, MonteCarloConfig


def _spin(minimum: float, maximum: float, decimals: int = 4, step: float = 1.0, value: float = 0.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    return box


class _DispersionEditorDialog(QDialog):
    def __init__(self, spacecraft_names: list, item: DispersionConfig | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit dispersion" if item is not None else "New dispersion")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.spacecraft_combo = QComboBox()
        self.spacecraft_combo.addItems(spacecraft_names)
        if item is not None:
            index = self.spacecraft_combo.findText(item.spacecraft)
            if index >= 0:
                self.spacecraft_combo.setCurrentIndex(index)
        form.addRow("Spacecraft", self.spacecraft_combo)

        self.quantity_combo = QComboBox()
        self.quantity_combo.addItems(DISPERSION_QUANTITIES)
        self.quantity_combo.currentTextChanged.connect(self._refresh_kind_choices)
        form.addRow("Quantity", self.quantity_combo)

        self.kind_combo = QComboBox()
        form.addRow("Kind", self.kind_combo)

        self.bounds_lo_spin = _spin(-1.0e9, 1.0e9, decimals=6, value=0.0)
        self.bounds_hi_spin = _spin(-1.0e9, 1.0e9, decimals=6, value=1.0)
        bounds_row = QHBoxLayout()
        bounds_row.addWidget(self.bounds_lo_spin)
        bounds_row.addWidget(self.bounds_hi_spin)
        form.addRow("Bounds [lo, hi]", bounds_row)

        self.mean_spin = _spin(-1.0e9, 1.0e9, decimals=6, value=0.0)
        form.addRow("Mean", self.mean_spin)
        self.std_spin = _spin(0.0, 1.0e9, decimals=6, value=1.0)
        form.addRow("Std deviation", self.std_spin)

        layout.addLayout(form)

        if item is not None:
            index = self.quantity_combo.findText(item.quantity)
            if index >= 0:
                self.quantity_combo.setCurrentIndex(index)
        self._refresh_kind_choices(self.quantity_combo.currentText())
        if item is not None:
            index = self.kind_combo.findText(item.kind)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)
            if item.bounds:
                self.bounds_lo_spin.setValue(item.bounds[0])
                self.bounds_hi_spin.setValue(item.bounds[1])
            if item.mean is not None:
                self.mean_spin.setValue(item.mean)
            if item.std_deviation is not None:
                self.std_spin.setValue(item.std_deviation)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_kind_choices(self, quantity: str) -> None:
        current = self.kind_combo.currentText()
        self.kind_combo.clear()
        kinds = DISPERSION_KINDS_BY_QUANTITY.get(quantity, ())
        self.kind_combo.addItems(kinds)
        index = self.kind_combo.findText(current)
        if index >= 0:
            self.kind_combo.setCurrentIndex(index)

    def _on_accept(self) -> None:
        try:
            self.to_dataclass()
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid dispersion", str(exc))
            return
        self.accept()

    def to_dataclass(self) -> DispersionConfig:
        if not self.spacecraft_combo.count():
            raise ValueError("this scenario has no spacecraft to disperse yet -- add one first")
        kind = self.kind_combo.currentText()
        config = DispersionConfig(
            spacecraft=self.spacecraft_combo.currentText(),
            quantity=self.quantity_combo.currentText(),
            kind=kind,
            bounds=[self.bounds_lo_spin.value(), self.bounds_hi_spin.value()]
            if kind in ("uniform", "uniform_euler_mrp") else None,
            mean=self.mean_spin.value() if kind == "normal" else None,
            std_deviation=self.std_spin.value() if kind == "normal" else None,
        )
        config.validate()
        return config


class DispersionListWidget(QWidget):
    """A list of :class:`DispersionConfig`, with Add/Edit/Remove -- mirrors
    :class:`gui.sensor_actuator_editor.SensorActuatorListWidget`'s shape.
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._items: list = []
        self._spacecraft_names: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add...")
        self.edit_button = QPushButton("Edit...")
        self.remove_button = QPushButton("Remove")
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.remove_button)
        layout.addLayout(button_row)

        self.add_button.clicked.connect(self._on_add)
        self.edit_button.clicked.connect(self._on_edit)
        self.remove_button.clicked.connect(self._on_remove)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_edit())

    def set_spacecraft_names(self, names: list) -> None:
        self._spacecraft_names = list(names)

    def _refresh_list(self) -> None:
        self.list_widget.clear()
        for item in self._items:
            self.list_widget.addItem(QListWidgetItem(f"{item.spacecraft}: {item.quantity} ({item.kind})"))

    def _on_add(self) -> None:
        dialog = _DispersionEditorDialog(self._spacecraft_names, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._items.append(dialog.to_dataclass())
            self._refresh_list()
            self.changed.emit()

    def _on_edit(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        dialog = _DispersionEditorDialog(self._spacecraft_names, item=self._items[row], parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._items[row] = dialog.to_dataclass()
            self._refresh_list()
            self.changed.emit()

    def _on_remove(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        del self._items[row]
        self._refresh_list()
        self.changed.emit()

    def to_list(self) -> list:
        return list(self._items)

    def from_list(self, items: list) -> None:
        self._items = list(items)
        self._refresh_list()


class MonteCarloGroupWidget(QGroupBox):
    """Composed directly into ``scenario_editor.py``, same pattern as its
    other ``_build_*_group()`` sections.
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Monte Carlo (Phase 3)", parent)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.toggled.connect(self.changed)
        form.addRow(self.enabled_check)

        self.num_runs_spin = QSpinBox()
        self.num_runs_spin.setRange(1, 1_000_000)
        self.num_runs_spin.setValue(10)
        self.num_runs_spin.valueChanged.connect(self.changed)
        form.addRow("Number of runs", self.num_runs_spin)

        self.thread_count_spin = QSpinBox()
        self.thread_count_spin.setRange(1, 256)
        self.thread_count_spin.setValue(1)
        self.thread_count_spin.setToolTip(
            "Unverified above 1 in this project's development sandbox (no Basilisk build there) -- see "
            "engine/monte_carlo.py's module docstring."
        )
        self.thread_count_spin.valueChanged.connect(self.changed)
        form.addRow("Thread count", self.thread_count_spin)

        self.verbose_check = QCheckBox("Verbose")
        self.verbose_check.toggled.connect(self.changed)
        form.addRow(self.verbose_check)
        layout.addLayout(form)

        layout.addWidget(QLabel("Dispersions"))
        self.dispersion_list = DispersionListWidget()
        self.dispersion_list.changed.connect(self.changed)
        layout.addWidget(self.dispersion_list)

    def set_spacecraft_names(self, names: list) -> None:
        self.dispersion_list.set_spacecraft_names(names)

    def to_dataclass(self) -> MonteCarloConfig:
        config = MonteCarloConfig(
            enabled=self.enabled_check.isChecked(),
            num_runs=self.num_runs_spin.value(),
            thread_count=self.thread_count_spin.value(),
            verbose=self.verbose_check.isChecked(),
            dispersions=self.dispersion_list.to_list(),
        )
        config.validate()
        return config

    def from_dataclass(self, config: MonteCarloConfig) -> None:
        self.enabled_check.setChecked(config.enabled)
        self.num_runs_spin.setValue(config.num_runs)
        self.thread_count_spin.setValue(config.thread_count)
        self.verbose_check.setChecked(config.verbose)
        self.dispersion_list.from_list(config.dispersions)
