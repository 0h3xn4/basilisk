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

Scope note: only edits the :class:`schema.scenario.SpacecraftConfig`
fields ``engine.service.SimulationService`` actually consumes (name,
orbit, dry mass, inertia, initial attitude/rate) -- deliberately no
editor for ``sensors``/``actuators``/``fsw_mode``/drag/SRP, which the
service doesn't wire up yet (see ``service.py``'s module docstring). Those
fields still round-trip through save/load (the schema keeps their
defaults), so a scenario file with them set by a later tool/phase won't
be clobbered by editing it here -- there is just no Phase 1 UI for them.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..schema.scenario import OrbitIC, ScenarioValidationError, SpacecraftConfig
from .orbit_ic_widget import OrbitIcWidget


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

        layout = QVBoxLayout(self)

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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        try:
            self.to_dataclass()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Invalid spacecraft", str(exc))
            return
        self.accept()

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
        )
        config.validate()  # raises ScenarioValidationError with a specific message on anything bad
        return config


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

    def to_list(self) -> list[SpacecraftConfig]:
        return list(self._configs)

    def from_list(self, configs: list[SpacecraftConfig]) -> None:
        self._configs = list(configs)
        self._refresh_list()
