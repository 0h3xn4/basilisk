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

"""WalkerConstellationDialog: collects a
:class:`engine.constellation.WalkerConstellationRequest` plus which
existing spacecraft (if any) to use as the template -- see that module's
docstring for the Walker-pattern math and why only orbit/name vary.

Does not import ``engine.constellation`` at module scope beyond the
request dataclass itself (no Basilisk anywhere in that chain, so this is
safe -- but kept consistent with this project's "gui/ doesn't need to
know engine/ imports Basilisk" split used elsewhere, e.g. vizard_dialog.py).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ..engine.constellation import WALKER_PATTERNS, WalkerConstellationRequest
from ..schema.scenario import ScenarioValidationError

_PATTERN_LABELS = {
    "delta": "Walker-Delta (planes spread over 360°, e.g. GPS)",
    "star": "Walker-Star (planes spread over 180°, e.g. Iridium -- near-polar)",
}


def _int_spin(minimum: int, maximum: int, value: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setValue(value)
    return box


def _double_spin(minimum: float, maximum: float, decimals: int, step: float, value: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    return box


class WalkerConstellationDialog(QDialog):
    """Modal "Generate Walker constellation" dialog. ``template_names``
    lists the scenario's current spacecraft (by name) to choose as the
    template for every generated satellite's non-orbit fields; empty means
    generate against a bare default spacecraft instead. ``central_body``
    is the scenario's ACTUAL current central body (read-only here, not a
    combo) -- deliberately not independently selectable, since a mismatch
    between this dialog's body and the scenario's real
    ``gravity.central_body`` would silently produce satellites at the
    wrong altitude relative to whatever body actually gets simulated.
    """

    def __init__(self, template_names: list[str], central_body: str = "earth", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Walker constellation")
        self._central_body = central_body

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Generates a full Walker-pattern constellation from a few high-level requirements -- "
            "every satellite's mass/sensors/actuators/power/etc. are cloned from the template you pick below; "
            "only orbit and name differ. Added to (not replacing) this scenario's spacecraft list."
        ))

        form = QFormLayout()
        form.addRow("Central body (from this scenario)", QLabel(central_body))

        self.template_combo = QComboBox()
        if template_names:
            for name in template_names:
                self.template_combo.addItem(name, userData=name)
        else:
            self.template_combo.addItem("(none -- use a bare default spacecraft)", userData=None)
            self.template_combo.setEnabled(False)
        form.addRow("Template spacecraft", self.template_combo)

        self.total_satellites = _int_spin(1, 10000, 12)
        self.num_planes = _int_spin(1, 1000, 3)
        self.phasing_factor = _int_spin(0, 999, 1)
        self.altitude_km = _double_spin(0.001, 1.0e7, 3, 10.0, 780.0)
        self.inclination_deg = _double_spin(0.0, 180.0, 4, 1.0, 86.4)
        self.eccentricity = _double_spin(0.0, 0.999999, 6, 0.001, 0.0)
        self.arg_periapsis_deg = _double_spin(0.0, 360.0, 4, 1.0, 0.0)
        self.pattern_combo = QComboBox()
        for pattern in WALKER_PATTERNS:
            self.pattern_combo.addItem(_PATTERN_LABELS[pattern], userData=pattern)
        self.raan_offset_deg = _double_spin(0.0, 360.0, 4, 1.0, 0.0)
        self.name_prefix_edit = QLineEdit("sat")

        form.addRow("Total satellites (T)", self.total_satellites)
        form.addRow("Number of planes (P)", self.num_planes)
        form.addRow("Phasing factor (F)", self.phasing_factor)
        form.addRow("Altitude [km]", self.altitude_km)
        form.addRow("Inclination [deg]", self.inclination_deg)
        form.addRow("Eccentricity [-]", self.eccentricity)
        form.addRow("Argument of periapsis [deg]", self.arg_periapsis_deg)
        form.addRow("Pattern", self.pattern_combo)
        form.addRow("RAAN offset [deg]", self.raan_offset_deg)
        form.addRow("Generated name prefix", self.name_prefix_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        try:
            self.to_request()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Invalid constellation request", str(exc))
            return
        self.accept()

    def to_request(self) -> WalkerConstellationRequest:
        request = WalkerConstellationRequest(
            total_satellites=self.total_satellites.value(),
            num_planes=self.num_planes.value(),
            phasing_factor=self.phasing_factor.value(),
            altitude_km=self.altitude_km.value(),
            inclination_deg=self.inclination_deg.value(),
            central_body=self._central_body,
            eccentricity=self.eccentricity.value(),
            arg_periapsis_deg=self.arg_periapsis_deg.value(),
            pattern=self.pattern_combo.currentData(),
            raan_offset_deg=self.raan_offset_deg.value(),
            name_prefix=self.name_prefix_edit.text().strip(),
        )
        request.validate()  # raises ScenarioValidationError with a specific message on anything bad
        return request

    def selected_template_name(self) -> str | None:
        return self.template_combo.currentData()
