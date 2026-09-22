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

"""Ground station list + per-station editor dialog.

Unlike sensors/actuators/FSW modes (see ``spacecraft_editor.py``'s scope
note), ground stations are pure scenario DATA with no implication of an
immediate simulated effect -- access-window computation is Phase 3, but
defining where the stations are is core mission setup (this project's own
spec draws exactly this distinction), so this editor exists now even
though nothing reads ``scenario.ground_stations`` yet.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..schema.scenario import GroundStationConfig, ScenarioValidationError


def _spin(minimum: float, maximum: float, decimals: int = 4, step: float = 1.0, value: float = 0.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    return box


class GroundStationEditorDialog(QDialog):
    def __init__(self, config: GroundStationConfig | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Ground station" if config is None else f"Ground station: {config.name}")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(config.name if config else "gs-1")
        form.addRow("Name", self.name_edit)
        self.lat_deg = _spin(-90.0, 90.0, decimals=6, step=1.0, value=config.latitude_deg if config else 0.0)
        form.addRow("Latitude [deg]", self.lat_deg)
        self.lon_deg = _spin(-180.0, 180.0, decimals=6, step=1.0, value=config.longitude_deg if config else 0.0)
        form.addRow("Longitude [deg]", self.lon_deg)
        self.alt_m = _spin(-500.0, 9000.0, decimals=1, step=10.0, value=config.altitude_m if config else 0.0)
        form.addRow("Altitude [m]", self.alt_m)
        self.min_elev_deg = _spin(0.0, 89.9, decimals=2, step=1.0,
                                   value=config.min_elevation_deg if config else 10.0)
        form.addRow("Minimum elevation mask [deg]", self.min_elev_deg)
        # Only meaningful for a spacecraft that also has an RF link budget
        # configured (see spacecraft_editor.py's "Power / link budget" tab
        # and schema.scenario.RFLinkConfig) -- harmless, unused otherwise.
        self.rx_antenna_gain_dbi = _spin(-50.0, 100.0, decimals=2, step=1.0,
                                          value=config.rx_antenna_gain_dbi if config else 45.0)
        form.addRow("RX antenna gain [dBi] (for a link budget)", self.rx_antenna_gain_dbi)
        self.system_noise_temp_k = _spin(0.1, 1.0e5, decimals=2, step=10.0,
                                          value=config.system_noise_temp_k if config else 290.0)
        form.addRow("System noise temperature [K] (for a link budget)", self.system_noise_temp_k)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        try:
            self.to_dataclass()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Invalid ground station", str(exc))
            return
        self.accept()

    def to_dataclass(self) -> GroundStationConfig:
        config = GroundStationConfig(
            name=self.name_edit.text().strip(),
            latitude_deg=self.lat_deg.value(),
            longitude_deg=self.lon_deg.value(),
            altitude_m=self.alt_m.value(),
            min_elevation_deg=self.min_elev_deg.value(),
            rx_antenna_gain_dbi=self.rx_antenna_gain_dbi.value(),
            system_noise_temp_k=self.system_noise_temp_k.value(),
        )
        config.validate()
        return config


class GroundStationListWidget(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._configs: list[GroundStationConfig] = []

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
            self.list_widget.addItem(QListWidgetItem(f"{config.name} ({config.latitude_deg:.2f}, {config.longitude_deg:.2f})"))

    def _on_add(self) -> None:
        existing_names = {c.name for c in self._configs}
        dialog = GroundStationEditorDialog(parent=self)
        base_name = dialog.name_edit.text()
        candidate, n = base_name, 1
        while candidate in existing_names:
            n += 1
            candidate = f"{base_name}-{n}"
        dialog.name_edit.setText(candidate)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = dialog.to_dataclass()
            if config.name in existing_names:
                QMessageBox.critical(self, "Duplicate name", f"A ground station named {config.name!r} already exists.")
                return
            self._configs.append(config)
            self._refresh_list()
            self.changed.emit()

    def _on_edit(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        dialog = GroundStationEditorDialog(config=self._configs[row], parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_config = dialog.to_dataclass()
            other_names = {c.name for i, c in enumerate(self._configs) if i != row}
            if new_config.name in other_names:
                QMessageBox.critical(self, "Duplicate name",
                                      f"A ground station named {new_config.name!r} already exists.")
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

    def to_list(self) -> list[GroundStationConfig]:
        return list(self._configs)

    def from_list(self, configs: list[GroundStationConfig]) -> None:
        self._configs = list(configs)
        self._refresh_list()
