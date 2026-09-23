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

"""One reusable list-editor widget for :class:`schema.scenario.SensorConfig`
and :class:`schema.scenario.ActuatorConfig` -- their shape is identical
(``kind``, ``name``, ``params``), so one generic widget covers both,
parameterized by which item class and which kind whitelist to use.

``params`` is edited as raw JSON text rather than a custom form per
sensor/actuator kind: the schema deliberately keeps ``params`` an open
dict (see ``schema.scenario.SensorConfig``'s docstring) so new kinds don't
need a schema migration, and a JSON text box is the one editor that never
falls behind that dict's actual shape.

User feedback (this app's own beginner testing): a blank ``{}`` JSON box
with zero in-dialog guidance meant a user had to already know -- from
reading ``engine/fsw.py``'s source -- which keys a given kind needs, their
units, and which ones are required vs. optional; a missing required key
(e.g. ``coarse_sun_sensor``'s ``nHat_B``) wasn't caught here either, only
much later when the OUTER spacecraft-editor dialog's
``SpacecraftConfig.validate()`` ran, decontextualized from the params box
that actually needs fixing. Fixed by _KIND_PARAM_SPECS below, which drives:
a per-kind help label, a "Reset to template" button that fills the params
box with a working example for the selected kind, and an immediate
required-key check right in this dialog. Keep _KIND_PARAM_SPECS in sync
with ``engine.fsw.attach_sensors()``/``build_reaction_wheels()``'s actual
``params.get()``/``params[...]`` usage when either changes.

Further user feedback specifically on "placement" of sensors/actuators:
every kind's body-frame direction (``nHat_B``, ``gsHat_B``, ``noise_std_
tesla``'s per-axis triple) used to be a bare 3-element JSON array typed
inside the params box, the one thing about "placement" that actually
affects the simulated physics here (Basilisk's coarseSunSensor/
reactionWheel models care about boresight/spin-axis DIRECTION -- there is
no position/mounting-offset or self-shadowing physics in the specific
Basilisk modules this app wires up, so a position field for these would be
cosmetic, not physical; :class:`schema.scenario.PowerConfig`'s
``panel_normal_b`` already got its own X/Y/Z spin boxes in
``gui.spacecraft_editor`` since Phase 1 -- see that dialog -- sensors/
actuators just hadn't caught up). Fixed: any 3-element-list-valued spec in
_KIND_PARAM_SPECS now gets its own X/Y/Z spin-box row (with a Normalize
button, since these are meant to be unit vectors and Basilisk does not
renormalize them), separate from the JSON box, which now only holds the
kind's non-vector keys.
"""

from __future__ import annotations

import json
import math
from typing import NamedTuple

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _ParamSpec(NamedTuple):
    key: str
    required: bool
    example: object
    help_text: str  # includes units, where the quantity has physical meaning

    @property
    def is_vector(self) -> bool:
        return isinstance(self.example, list) and len(self.example) == 3


# One entry per SUPPORTED_SENSOR_KINDS/SUPPORTED_ACTUATOR_KINDS value that
# engine.fsw actually builds -- deliberately omits "thruster"/
# "magnetic_torque_rod" (schema-valid but not wired up; see
# _UNIMPLEMENTED_ACTUATOR_KINDS below and SUPPORTED_ACTUATOR_KINDS's own
# module-level docstring note in schema.scenario).
_KIND_PARAM_SPECS: dict[str, list[_ParamSpec]] = {
    "star_tracker": [
        _ParamSpec("noise_arcsec", False, 0.0, "1-sigma attitude noise [arcsec]"),
    ],
    "imu": [
        _ParamSpec("gyro_noise_rad_s", False, 0.0, "1-sigma gyro noise [rad/s]"),
        _ParamSpec("accel_noise_m_s2", False, 0.0, "1-sigma accelerometer noise [m/s^2]"),
    ],
    "coarse_sun_sensor": [
        _ParamSpec("nHat_B", True, [1.0, 0.0, 0.0], "sensor boresight direction, body frame, unit vector [-]"),
        _ParamSpec("fov_deg", False, 90.0, "full field of view [deg]"),
        _ParamSpec("noise_std", False, 0.0, "1-sigma output noise (cosine-law output units) [-]"),
    ],
    "magnetometer": [
        _ParamSpec("noise_std_tesla", False, [0.0, 0.0, 0.0], "1-sigma noise per body axis [T]"),
    ],
    "reaction_wheel": [
        _ParamSpec("gsHat_B", True, [0.0, 0.0, 1.0], "spin-axis direction, body frame, unit vector [-]"),
        _ParamSpec("rw_type", False, "custom",
                    "wheel model name known to Basilisk's simIncludeRW.rwFactory(), e.g. 'Honeywell_HR16'"),
        _ParamSpec("Omega_max", False, 6000.0, "max wheel speed [RPM]"),
        _ParamSpec("u_max", False, 0.2, "max motor torque [N*m]"),
        _ParamSpec("maxMomentum", False, 50.0, "max wheel angular momentum [N*m*s]"),
        _ParamSpec("Js", False, 0.028, "wheel inertia about the spin axis [kg*m^2]"),
    ],
}

# Schema-valid (SUPPORTED_ACTUATOR_KINDS) but engine.fsw/engine.service
# raise a specific error if actually configured -- see
# schema.scenario.SUPPORTED_ACTUATOR_KINDS's module-level docstring note.
# Selectable here (so a saved scenario file using one can still be
# opened/edited), but flagged with an in-dialog warning rather than
# letting a beginner discover this only when Run Simulation fails.
_UNIMPLEMENTED_ACTUATOR_KINDS = ("thruster", "magnetic_torque_rod")


def _spin_component(value: float = 0.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(-1.0e6, 1.0e6)
    box.setDecimals(6)
    box.setSingleStep(0.1)
    box.setValue(value)
    return box


def _vector_specs(kind: str) -> list[_ParamSpec]:
    return [spec for spec in _KIND_PARAM_SPECS.get(kind, []) if spec.is_vector]


def _non_vector_specs(kind: str) -> list[_ParamSpec]:
    return [spec for spec in _KIND_PARAM_SPECS.get(kind, []) if not spec.is_vector]


def _template_params(kind: str) -> dict:
    return {spec.key: spec.example for spec in _KIND_PARAM_SPECS.get(kind, [])}


def _non_vector_template_params(kind: str) -> dict:
    return {spec.key: spec.example for spec in _non_vector_specs(kind)}


def _missing_required_keys(kind: str, params: dict) -> list[str]:
    return [spec.key for spec in _KIND_PARAM_SPECS.get(kind, []) if spec.required and spec.key not in params]


def _hint_text(kind: str) -> str:
    if kind in _UNIMPLEMENTED_ACTUATOR_KINDS:
        return (
            f"⚠ {kind!r} is schema-valid but not simulated yet -- engine.service will raise an error at "
            "Run Simulation if this actuator is actually configured on a spacecraft with fsw_mode set. "
            "Pick 'reaction_wheel' for a working actuator."
        )
    specs = _KIND_PARAM_SPECS.get(kind)
    if not specs:
        return "No params needed for this kind."
    lines = []
    for spec in specs:
        tag = "required" if spec.required else "optional"
        where = " -- see X/Y/Z fields below" if spec.is_vector else ""
        lines.append(f"• {spec.key} ({tag}): {spec.help_text}{where}")
    return "\n".join(lines)


class _ItemEditorDialog(QDialog):
    def __init__(self, item_cls, kind_choices, item=None, parent: QWidget | None = None):
        super().__init__(parent)
        self._item_cls = item_cls
        self._item_params = item.params if item is not None else {}
        self._original_kind = item.kind if item is not None else None
        label = "sensor" if item_cls.__name__ == "SensorConfig" else "actuator"
        self.setWindowTitle(f"Edit {label}" if item is not None else f"New {label}")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(list(kind_choices))
        if item is not None:
            index = self.kind_combo.findText(item.kind)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)
        form.addRow("Kind", self.kind_combo)

        self.name_edit = QLineEdit(item.name if item is not None else "")
        form.addRow("Name", self.name_edit)
        layout.addLayout(form)

        self.hint_label = QLabel(_hint_text(self.kind_combo.currentText()))
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.hint_label)

        # Vector-shaped params (nHat_B, gsHat_B, ...) get their own X/Y/Z
        # spin-box row instead of living inside the JSON params box -- see
        # this module's docstring. Rebuilt whenever Kind changes, since
        # different kinds have different vector keys.
        self._vector_form_container = QWidget()
        self._vector_form = QFormLayout(self._vector_form_container)
        self._vector_form.setContentsMargins(0, 0, 0, 0)
        self._vector_boxes: dict[str, tuple[QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox]] = {}
        layout.addWidget(self._vector_form_container)
        self._rebuild_vector_rows(self.kind_combo.currentText())

        self.kind_combo.currentTextChanged.connect(self._on_kind_changed)

        params_row = QHBoxLayout()
        params_row.addWidget(QLabel("Other params (JSON object)"))
        params_row.addStretch(1)
        self.reset_template_button = QPushButton("Reset to template")
        self.reset_template_button.setToolTip(
            "Fill the fields above and the params box below with a working example for the "
            "selected Kind -- overwrites whatever is currently typed/set there."
        )
        self.reset_template_button.clicked.connect(self._on_reset_template)
        params_row.addWidget(self.reset_template_button)
        layout.addLayout(params_row)

        if item is not None:
            initial_non_vector = {k: v for k, v in item.params.items()
                                   if k not in {spec.key for spec in _vector_specs(item.kind)}}
        else:
            initial_non_vector = _non_vector_template_params(self.kind_combo.currentText())
        self.params_edit = QPlainTextEdit(json.dumps(initial_non_vector, indent=2))
        self.params_edit.setTabChangesFocus(True)
        layout.addWidget(self.params_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _rebuild_vector_rows(self, kind: str) -> None:
        while self._vector_form.rowCount():
            self._vector_form.removeRow(0)
        self._vector_boxes.clear()
        use_item_params = kind == self._original_kind
        for spec in _vector_specs(kind):
            value = self._item_params.get(spec.key, spec.example) if use_item_params else spec.example
            x, y, z = (_spin_component(v) for v in value)
            row = QHBoxLayout()
            row.addWidget(x)
            row.addWidget(y)
            row.addWidget(z)
            normalize_button = QPushButton("Normalize")
            normalize_button.setToolTip("Rescale to a unit vector (preserves direction).")
            normalize_button.clicked.connect(lambda _checked, k=spec.key: self._on_normalize(k))
            row.addWidget(normalize_button)
            row_widget = QWidget()
            row_widget.setLayout(row)
            required_tag = "" if spec.required else " (optional)"
            self._vector_form.addRow(f"{spec.key}{required_tag}", row_widget)
            self._vector_boxes[spec.key] = (x, y, z)

    def _on_kind_changed(self, kind: str) -> None:
        self.hint_label.setText(_hint_text(kind))
        self._rebuild_vector_rows(kind)

    def _on_normalize(self, key: str) -> None:
        x, y, z = self._vector_boxes[key]
        magnitude = math.sqrt(x.value() ** 2 + y.value() ** 2 + z.value() ** 2)
        if magnitude > 0.0:
            x.setValue(x.value() / magnitude)
            y.setValue(y.value() / magnitude)
            z.setValue(z.value() / magnitude)

    def _on_reset_template(self) -> None:
        kind = self.kind_combo.currentText()
        for spec in _vector_specs(kind):
            x, y, z = self._vector_boxes[spec.key]
            x.setValue(spec.example[0])
            y.setValue(spec.example[1])
            z.setValue(spec.example[2])
        self.params_edit.setPlainText(json.dumps(_non_vector_template_params(kind), indent=2))

    def _on_accept(self) -> None:
        try:
            self.to_dataclass()
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid params", str(exc))
            return
        self.accept()

    def to_dataclass(self):
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("name must not be empty")
        kind = self.kind_combo.currentText()
        text = self.params_edit.toPlainText().strip() or "{}"
        try:
            params = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"params is not valid JSON: {exc}") from exc
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object (e.g. {\"noise_std\": 0.01})")
        vector_keys = {spec.key for spec in _vector_specs(kind)}
        params = {k: v for k, v in params.items() if k not in vector_keys}  # vector rows are authoritative
        for key, (x, y, z) in self._vector_boxes.items():
            params[key] = [x.value(), y.value(), z.value()]
        missing = _missing_required_keys(kind, params)
        if missing:
            raise ValueError(
                f"{kind!r} is missing required params key(s): {', '.join(missing)} -- "
                "use 'Reset to template' for a working example"
            )
        return self._item_cls(kind=kind, name=name, params=params)


class SensorActuatorListWidget(QWidget):
    """A list of :class:`SensorConfig` or :class:`ActuatorConfig` (pass the
    class and its kind whitelist), with Add/Edit/Remove -- mirrors
    :class:`gui.spacecraft_editor.SpacecraftListWidget`'s shape.
    """

    changed = Signal()

    def __init__(self, item_cls, kind_choices, parent: QWidget | None = None):
        super().__init__(parent)
        self._item_cls = item_cls
        self._kind_choices = kind_choices
        self._items: list = []

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
        for item in self._items:
            self.list_widget.addItem(QListWidgetItem(f"{item.kind}: {item.name}"))

    def _existing_names(self, exclude_row: int | None = None) -> set:
        return {item.name for i, item in enumerate(self._items) if i != exclude_row}

    def _on_add(self) -> None:
        dialog = _ItemEditorDialog(self._item_cls, self._kind_choices, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_item = dialog.to_dataclass()
            if new_item.name in self._existing_names():
                QMessageBox.critical(self, "Duplicate name", f"{new_item.name!r} already exists.")
                return
            self._items.append(new_item)
            self._refresh_list()
            self.changed.emit()

    def _on_edit(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        dialog = _ItemEditorDialog(self._item_cls, self._kind_choices, item=self._items[row], parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_item = dialog.to_dataclass()
            if new_item.name in self._existing_names(exclude_row=row):
                QMessageBox.critical(self, "Duplicate name", f"{new_item.name!r} already exists.")
                return
            self._items[row] = new_item
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
