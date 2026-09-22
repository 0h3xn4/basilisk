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

"""OrbitIcWidget: one orbit initial-condition editor covering all three
forms :class:`schema.scenario.OrbitIC` supports (classical elements,
Cartesian, TLE), switched via a combo box + stacked widget. Every field
maps 1:1 onto an ``OrbitIC`` field -- no separate GUI-only representation.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from ..schema.scenario import ORBIT_IC_TYPES, OrbitIC

_TYPE_LABELS = {
    "classical_elements": "Classical elements",
    "cartesian": "Cartesian state",
    "tle": "Two-Line Element (TLE)",
}


def _spin(minimum: float, maximum: float, decimals: int = 6, step: float = 1.0, value: float = 0.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    return box


class OrbitIcWidget(QWidget):
    """Emits :attr:`changed` on any edit (type switch or field value), so
    a containing form can re-validate live.
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.type_combo = QComboBox()
        for orbit_type in ORBIT_IC_TYPES:
            self.type_combo.addItem(_TYPE_LABELS[orbit_type], userData=orbit_type)
        layout.addWidget(self.type_combo)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self._build_classical_elements_page()
        self._build_cartesian_page()
        self._build_tle_page()

        self.type_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.type_combo.currentIndexChanged.connect(self.changed)

    def _build_classical_elements_page(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.sma_km = _spin(1.0, 1.0e7, decimals=3, step=10.0, value=7000.0)
        self.ecc = _spin(0.0, 0.999999, decimals=6, step=0.001)
        self.inc_deg = _spin(0.0, 180.0, decimals=4, step=1.0)
        self.raan_deg = _spin(0.0, 360.0, decimals=4, step=1.0)
        self.aop_deg = _spin(0.0, 360.0, decimals=4, step=1.0)
        self.ta_deg = _spin(0.0, 360.0, decimals=4, step=1.0)
        form.addRow("Semi-major axis [km]", self.sma_km)
        form.addRow("Eccentricity [-]", self.ecc)
        form.addRow("Inclination [deg]", self.inc_deg)
        form.addRow("RAAN [deg]", self.raan_deg)
        form.addRow("Argument of periapsis [deg]", self.aop_deg)
        form.addRow("True anomaly [deg]", self.ta_deg)
        for box in (self.sma_km, self.ecc, self.inc_deg, self.raan_deg, self.aop_deg, self.ta_deg):
            box.valueChanged.connect(self.changed)
        self.stack.addWidget(page)

    def _build_cartesian_page(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.pos_x_km = _spin(-1.0e9, 1.0e9, decimals=3, step=100.0, value=7000.0)
        self.pos_y_km = _spin(-1.0e9, 1.0e9, decimals=3, step=100.0)
        self.pos_z_km = _spin(-1.0e9, 1.0e9, decimals=3, step=100.0)
        self.vel_x_km_s = _spin(-100.0, 100.0, decimals=6, step=0.1)
        self.vel_y_km_s = _spin(-100.0, 100.0, decimals=6, step=0.1, value=7.5)
        self.vel_z_km_s = _spin(-100.0, 100.0, decimals=6, step=0.1)
        form.addRow("Position X [km]", self.pos_x_km)
        form.addRow("Position Y [km]", self.pos_y_km)
        form.addRow("Position Z [km]", self.pos_z_km)
        form.addRow("Velocity X [km/s]", self.vel_x_km_s)
        form.addRow("Velocity Y [km/s]", self.vel_y_km_s)
        form.addRow("Velocity Z [km/s]", self.vel_z_km_s)
        for box in (self.pos_x_km, self.pos_y_km, self.pos_z_km, self.vel_x_km_s, self.vel_y_km_s, self.vel_z_km_s):
            box.valueChanged.connect(self.changed)
        self.stack.addWidget(page)

    def _build_tle_page(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.tle_line1 = QLineEdit()
        self.tle_line1.setPlaceholderText("1 25544U 98067A   24001.00000000  .00000000  00000-0  00000-0 0  9990")
        self.tle_line2 = QLineEdit()
        self.tle_line2.setPlaceholderText("2 25544  51.6400   0.0000 0000000   0.0000   0.0000 15.50000000000000")
        form.addRow("TLE line 1", self.tle_line1)
        form.addRow("TLE line 2", self.tle_line2)
        self.tle_line1.textChanged.connect(self.changed)
        self.tle_line2.textChanged.connect(self.changed)
        self.stack.addWidget(page)

    def to_dataclass(self) -> OrbitIC:
        orbit_type = self.type_combo.currentData()
        if orbit_type == "classical_elements":
            return OrbitIC(
                type=orbit_type,
                semi_major_axis_km=self.sma_km.value(),
                eccentricity=self.ecc.value(),
                inclination_deg=self.inc_deg.value(),
                raan_deg=self.raan_deg.value(),
                arg_periapsis_deg=self.aop_deg.value(),
                true_anomaly_deg=self.ta_deg.value(),
            )
        if orbit_type == "cartesian":
            return OrbitIC(
                type=orbit_type,
                position_km=[self.pos_x_km.value(), self.pos_y_km.value(), self.pos_z_km.value()],
                velocity_km_s=[self.vel_x_km_s.value(), self.vel_y_km_s.value(), self.vel_z_km_s.value()],
            )
        return OrbitIC(type=orbit_type, tle_line1=self.tle_line1.text(), tle_line2=self.tle_line2.text())

    def from_dataclass(self, orbit: OrbitIC) -> None:
        index = self.type_combo.findData(orbit.type)
        if index < 0:
            raise ValueError(f"OrbitIcWidget doesn't know orbit type {orbit.type!r}")
        self.type_combo.setCurrentIndex(index)
        self.stack.setCurrentIndex(index)

        if orbit.type == "classical_elements":
            self.sma_km.setValue(orbit.semi_major_axis_km or 0.0)
            self.ecc.setValue(orbit.eccentricity or 0.0)
            self.inc_deg.setValue(orbit.inclination_deg or 0.0)
            self.raan_deg.setValue(orbit.raan_deg or 0.0)
            self.aop_deg.setValue(orbit.arg_periapsis_deg or 0.0)
            self.ta_deg.setValue(orbit.true_anomaly_deg or 0.0)
        elif orbit.type == "cartesian":
            pos = orbit.position_km or [0.0, 0.0, 0.0]
            vel = orbit.velocity_km_s or [0.0, 0.0, 0.0]
            self.pos_x_km.setValue(pos[0])
            self.pos_y_km.setValue(pos[1])
            self.pos_z_km.setValue(pos[2])
            self.vel_x_km_s.setValue(vel[0])
            self.vel_y_km_s.setValue(vel[1])
            self.vel_z_km_s.setValue(vel[2])
        elif orbit.type == "tle":
            self.tle_line1.setText(orbit.tle_line1 or "")
            self.tle_line2.setText(orbit.tle_line2 or "")
