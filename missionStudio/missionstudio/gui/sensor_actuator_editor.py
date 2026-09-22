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
falls behind that dict's actual shape. See each kind's ``params`` keys in
``engine/fsw.py``'s builder functions (e.g. ``coarse_sun_sensor`` needs
``nHat_B``, ``reaction_wheel`` needs ``gsHat_B``).
"""

from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
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


class _ItemEditorDialog(QDialog):
    def __init__(self, item_cls, kind_choices, item=None, parent: QWidget | None = None):
        super().__init__(parent)
        self._item_cls = item_cls
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

        layout.addWidget(QLabel("Params (JSON object)"))
        self.params_edit = QPlainTextEdit(json.dumps(item.params if item is not None else {}, indent=2))
        self.params_edit.setTabChangesFocus(True)
        layout.addWidget(self.params_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        text = self.params_edit.toPlainText().strip() or "{}"
        try:
            params = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"params is not valid JSON: {exc}") from exc
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object (e.g. {\"gsHat_B\": [1, 0, 0]})")
        return self._item_cls(kind=self.kind_combo.currentText(), name=name, params=params)


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
