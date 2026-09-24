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

"""Tree editor for a scenario's ``mission_sequence`` -- the GUI counterpart
of ``schema.command.Command``/``engine.mission_engine.MissionEngine``. The
first :class:`QTreeWidget` user in ``gui/`` (every other list here --
spacecraft, sensors/actuators, ground stations -- is flat), because
``Command`` is the first schema type that nests (``if``/``while`` carry
``children``).

``_CommandEditorDialog`` is modeled directly on
``gui.sensor_actuator_editor._ItemEditorDialog``: a Kind combo picks the
command shape, the rest of the dialog is kind-conditional fields, and
``to_dataclass()``/``_on_accept()`` validate before accepting. Unlike that
dialog, validation here doesn't hand-check each field -- it builds a real
``schema.command.Command`` and calls its own ``validate()``, since that's
already the single source of truth for what each kind requires.

``MissionSequenceEditorWidget.set_spacecraft_names_provider()`` mirrors
``gui.spacecraft_editor.SpacecraftListWidget.set_central_body_provider()``'s
zero-argument-callable convention; the snapshot list it returns is then
passed into ``_CommandEditorDialog`` the same way
``gui.spacecraft_editor.SpacecraftEditorDialog`` takes
``other_spacecraft_names`` -- a fixed list captured when the dialog opens,
not a live provider itself.

A tree node's ``children`` are never read off the ``Command`` stored on a
``QTreeWidgetItem`` (see ``_new_item``, which always stores a ``Command``
with ``children`` cleared) -- the tree's own nesting is the single source
of truth for structure, so editing a child through this dialog can never
leave a parent's stored (and otherwise-unused) ``children`` list stale.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..schema.command import (
    SUPPORTED_COMMAND_KINDS,
    SUPPORTED_EVENT_KINDS,
    SUPPORTED_MANEUVER_FRAMES,
    SUPPORTED_STOP_CONDITIONS,
    Command,
)

# Mirrors engine.mission_engine._ASSIGNMENT_CONTROLLERS/_ASSIGNMENT_ATTRIBUTES
# -- duplicated here (not imported) because engine.mission_engine imports
# engine.service -> Basilisk at module level (see engine/results.py's own
# docstring on why Basilisk-free/GUI-safe modules stay separate from it),
# and this dialog must be usable with no Basilisk installed. Keep these in
# sync if either changes.
_ASSIGNMENT_CONTROLLER_CHOICES = ("station_keeping", "phasing_keeping", "constant_thrust")
_ASSIGNMENT_PARAMETER_CHOICES = ("thrust_n", "isp_s")

# self.stack page order -- "if"/"while" share one page (same params shape:
# just "condition"), so this has one fewer entries than
# SUPPORTED_COMMAND_KINDS.
_KIND_PAGE_INDEX = {"propagate": 0, "maneuver": 1, "assignment": 2, "report": 3, "if": 4, "while": 4,
                     "script_block": 5}


def _spin_component(value: float = 0.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(-1.0e9, 1.0e9)
    box.setDecimals(6)
    box.setSingleStep(0.1)
    box.setValue(value)
    return box


class _CommandEditorDialog(QDialog):
    def __init__(self, command: Command | None = None, parent: QWidget | None = None,
                 spacecraft_names: list[str] | None = None):
        super().__init__(parent)
        self._spacecraft_names = spacecraft_names or []
        self.setWindowTitle("Edit command" if command is not None else "New command")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(list(SUPPORTED_COMMAND_KINDS))
        # Changing kind on an existing command would orphan whatever
        # children it has in the tree (only "if"/"while" carry children,
        # and MissionSequenceEditorWidget derives them from tree structure,
        # not from this dialog) -- so kind is fixed once a command exists;
        # only choosable while adding a brand new one.
        self.kind_combo.setEnabled(command is None)
        if command is not None:
            index = self.kind_combo.findText(command.kind)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)
        form.addRow("Kind", self.kind_combo)

        self.label_edit = QLineEdit(command.label if command is not None and command.label else "")
        self.label_edit.setPlaceholderText("optional, e.g. 'Prop to periapsis'")
        form.addRow("Label", self.label_edit)
        layout.addLayout(form)

        self.stack = QStackedWidget()
        params = command.params if command is not None else {}
        self._build_propagate_page(params)
        self._build_maneuver_page(params)
        self._build_assignment_page(params)
        self._build_report_page(params)
        self._build_conditional_page(params)
        self._build_script_block_page(params)
        layout.addWidget(self.stack)

        self.kind_combo.currentTextChanged.connect(self._on_kind_changed)
        self._on_kind_changed(self.kind_combo.currentText())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_kind_changed(self, kind: str) -> None:
        self.stack.setCurrentIndex(_KIND_PAGE_INDEX[kind])

    # -- page construction ---------------------------------------------------
    def _build_propagate_page(self, params: dict) -> None:
        page = QWidget()
        form = QFormLayout(page)

        self.stop_condition_combo = QComboBox()
        self.stop_condition_combo.addItems(list(SUPPORTED_STOP_CONDITIONS))
        index = self.stop_condition_combo.findText(params.get("stop_condition", "duration"))
        if index >= 0:
            self.stop_condition_combo.setCurrentIndex(index)
        form.addRow("Stop condition", self.stop_condition_combo)

        self.propagate_stop_stack = QStackedWidget()
        form.addRow(self.propagate_stop_stack)

        duration_page = QWidget()
        duration_form = QFormLayout(duration_page)
        duration_form.setContentsMargins(0, 0, 0, 0)
        self.duration_days_spin = QDoubleSpinBox()
        self.duration_days_spin.setRange(1e-6, 1e6)
        self.duration_days_spin.setDecimals(6)
        self.duration_days_spin.setValue(float(params.get("duration_days", 1.0)))
        duration_form.addRow("Duration [days]", self.duration_days_spin)
        self.propagate_stop_stack.addWidget(duration_page)

        epoch_page = QWidget()
        epoch_form = QFormLayout(epoch_page)
        epoch_form.setContentsMargins(0, 0, 0, 0)
        self.stop_epoch_edit = QLineEdit(str(params.get("stop_epoch_utc", "")))
        self.stop_epoch_edit.setPlaceholderText("ISO 8601 UTC, e.g. 2030-01-05T00:00:00")
        epoch_form.addRow("Stop epoch (UTC)", self.stop_epoch_edit)
        self.propagate_stop_stack.addWidget(epoch_page)

        event_page = QWidget()
        event_form = QFormLayout(event_page)
        event_form.setContentsMargins(0, 0, 0, 0)
        self.event_kind_combo = QComboBox()
        self.event_kind_combo.addItems(list(SUPPORTED_EVENT_KINDS))
        event_index = self.event_kind_combo.findText(params.get("event_kind", SUPPORTED_EVENT_KINDS[0]))
        if event_index >= 0:
            self.event_kind_combo.setCurrentIndex(event_index)
        event_form.addRow("Event", self.event_kind_combo)
        self.propagate_event_spacecraft_combo = QComboBox()
        self.propagate_event_spacecraft_combo.addItems(self._spacecraft_names)
        sc_index = self.propagate_event_spacecraft_combo.findText(params.get("spacecraft", ""))
        if sc_index >= 0:
            self.propagate_event_spacecraft_combo.setCurrentIndex(sc_index)
        event_form.addRow("Spacecraft", self.propagate_event_spacecraft_combo)
        self.propagate_stop_stack.addWidget(event_page)

        self.stop_condition_combo.currentTextChanged.connect(
            lambda text: self.propagate_stop_stack.setCurrentIndex(SUPPORTED_STOP_CONDITIONS.index(text))
        )
        self.propagate_stop_stack.setCurrentIndex(
            SUPPORTED_STOP_CONDITIONS.index(self.stop_condition_combo.currentText())
        )

        self.stack.addWidget(page)

    def _build_maneuver_page(self, params: dict) -> None:
        page = QWidget()
        form = QFormLayout(page)

        self.maneuver_spacecraft_combo = QComboBox()
        self.maneuver_spacecraft_combo.addItems(self._spacecraft_names)
        index = self.maneuver_spacecraft_combo.findText(params.get("spacecraft", ""))
        if index >= 0:
            self.maneuver_spacecraft_combo.setCurrentIndex(index)
        form.addRow("Spacecraft", self.maneuver_spacecraft_combo)

        delta_v = params.get("delta_v_m_s", [0.0, 0.0, 0.0])
        row = QHBoxLayout()
        self.delta_v_x_spin = _spin_component(delta_v[0] if len(delta_v) > 0 else 0.0)
        self.delta_v_y_spin = _spin_component(delta_v[1] if len(delta_v) > 1 else 0.0)
        self.delta_v_z_spin = _spin_component(delta_v[2] if len(delta_v) > 2 else 0.0)
        row.addWidget(self.delta_v_x_spin)
        row.addWidget(self.delta_v_y_spin)
        row.addWidget(self.delta_v_z_spin)
        row_widget = QWidget()
        row_widget.setLayout(row)
        form.addRow("Delta-V [m/s]", row_widget)

        self.maneuver_frame_combo = QComboBox()
        self.maneuver_frame_combo.addItems(list(SUPPORTED_MANEUVER_FRAMES))
        frame_index = self.maneuver_frame_combo.findText(params.get("frame", "inertial"))
        if frame_index >= 0:
            self.maneuver_frame_combo.setCurrentIndex(frame_index)
        self.maneuver_frame_combo.setToolTip(
            "inertial: delta-V applied directly in the N frame.\n"
            "vnb: velocity/normal/binormal orbit frame.\n"
            "rtn: radial/transverse/normal orbit frame."
        )
        form.addRow("Frame", self.maneuver_frame_combo)

        self.stack.addWidget(page)

    def _build_assignment_page(self, params: dict) -> None:
        page = QWidget()
        form = QFormLayout(page)

        self.assignment_spacecraft_combo = QComboBox()
        self.assignment_spacecraft_combo.addItems(self._spacecraft_names)
        self.assignment_controller_combo = QComboBox()
        self.assignment_controller_combo.addItems(list(_ASSIGNMENT_CONTROLLER_CHOICES))
        self.assignment_parameter_combo = QComboBox()
        self.assignment_parameter_combo.addItems(list(_ASSIGNMENT_PARAMETER_CHOICES))

        target = params.get("target", "")
        target_parts = target.split(".") if isinstance(target, str) else []
        if len(target_parts) == 3:
            sc_index = self.assignment_spacecraft_combo.findText(target_parts[0])
            if sc_index >= 0:
                self.assignment_spacecraft_combo.setCurrentIndex(sc_index)
            controller_index = self.assignment_controller_combo.findText(target_parts[1])
            if controller_index >= 0:
                self.assignment_controller_combo.setCurrentIndex(controller_index)
            parameter_index = self.assignment_parameter_combo.findText(target_parts[2])
            if parameter_index >= 0:
                self.assignment_parameter_combo.setCurrentIndex(parameter_index)

        form.addRow("Spacecraft", self.assignment_spacecraft_combo)
        form.addRow("Controller", self.assignment_controller_combo)
        form.addRow("Parameter", self.assignment_parameter_combo)

        self.assignment_value_spin = QDoubleSpinBox()
        self.assignment_value_spin.setRange(-1.0e9, 1.0e9)
        self.assignment_value_spin.setDecimals(6)
        value = params.get("value", 0.0)
        self.assignment_value_spin.setValue(float(value) if isinstance(value, (int, float)) else 0.0)
        form.addRow("New value", self.assignment_value_spin)

        hint = QLabel(
            "Sets a live controller parameter mid-mission, e.g. reducing station-keeping thrust for a later "
            "mission phase. thrust_n [N] applies to any controller kind above; isp_s [s] only affects propellant "
            "bookkeeping, not the applied force."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        form.addRow(hint)

        self.stack.addWidget(page)

    def _build_report_page(self, params: dict) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "Series names to snapshot (one per line), e.g. 'sat-1.position_N' -- leave empty to snapshot "
            "every series produced by the run so far."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.report_series_edit = QPlainTextEdit("\n".join(params.get("series", [])))
        self.report_series_edit.setTabChangesFocus(True)
        layout.addWidget(self.report_series_edit)
        self.stack.addWidget(page)

    def _build_conditional_page(self, params: dict) -> None:
        """Shared by ``if``/``while`` -- both take just a ``condition``
        expression string (see ``Command._validate_conditional``); which
        one this dialog is building for is chosen by the Kind combo, not
        this method.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "Condition expression, evaluated against t_s (elapsed mission time [s]) and "
            "spacecraft['<name>']['r_BN_N'|'v_BN_N'|'altitude_m'|'mass_kg'] -- "
            "e.g. \"spacecraft['sat-1']['altitude_m'] < 400000\"."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.condition_edit = QLineEdit(str(params.get("condition", "")))
        layout.addWidget(self.condition_edit)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def _build_script_block_page(self, params: dict) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "Arbitrary Python, run with no sandboxing (a plain exec()) -- see "
            "engine.mission_engine.MissionEngine._run_script_block's docstring for the exact trust boundary."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.script_code_edit = QPlainTextEdit(str(params.get("code", "")))
        self.script_code_edit.setTabChangesFocus(True)
        font = self.script_code_edit.font()
        font.setFamily("monospace")
        self.script_code_edit.setFont(font)
        layout.addWidget(self.script_code_edit)
        self.stack.addWidget(page)

    # -- (dis)assembly --------------------------------------------------------
    def _collect_params(self, kind: str) -> dict:
        if kind == "propagate":
            stop_condition = self.stop_condition_combo.currentText()
            params: dict = {"stop_condition": stop_condition}
            if stop_condition == "duration":
                params["duration_days"] = self.duration_days_spin.value()
            elif stop_condition == "epoch":
                params["stop_epoch_utc"] = self.stop_epoch_edit.text().strip()
            else:  # "event"
                params["event_kind"] = self.event_kind_combo.currentText()
                params["spacecraft"] = self.propagate_event_spacecraft_combo.currentText()
            return params
        if kind == "maneuver":
            return {
                "spacecraft": self.maneuver_spacecraft_combo.currentText(),
                "delta_v_m_s": [self.delta_v_x_spin.value(), self.delta_v_y_spin.value(),
                                self.delta_v_z_spin.value()],
                "frame": self.maneuver_frame_combo.currentText(),
            }
        if kind == "assignment":
            target = ".".join((
                self.assignment_spacecraft_combo.currentText(),
                self.assignment_controller_combo.currentText(),
                self.assignment_parameter_combo.currentText(),
            ))
            return {"target": target, "value": self.assignment_value_spin.value()}
        if kind == "report":
            series = [line.strip() for line in self.report_series_edit.toPlainText().splitlines() if line.strip()]
            return {"series": series}
        if kind in ("if", "while"):
            return {"condition": self.condition_edit.text().strip()}
        if kind == "script_block":
            return {"code": self.script_code_edit.toPlainText()}
        raise AssertionError(f"unhandled kind {kind!r} -- _KIND_PAGE_INDEX/SUPPORTED_COMMAND_KINDS out of sync")

    def _on_accept(self) -> None:
        try:
            self.to_dataclass()
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid command", str(exc))
            return
        self.accept()

    def to_dataclass(self) -> Command:
        kind = self.kind_combo.currentText()
        label = self.label_edit.text().strip() or None
        # Command.validate()'s "assignment" check only requires a dotted
        # string (see schema.command.Command._validate_assignment) -- it
        # doesn't require the spacecraft segment itself to be non-empty,
        # unlike "maneuver"/propagate "event", which do reject a blank
        # spacecraft. With no spacecraft defined yet, assignment_spacecraft_
        # combo has no items and currentText() is "", which would otherwise
        # build a target like ".station_keeping.thrust_n" that silently
        # passes both Command.validate() and the scenario-level reference
        # check (schema.references._command_references skips an empty
        # name) -- caught only much later, deep into a mission_sequence
        # run. Reject it here instead, immediately, like the other two
        # spacecraft-name fields already are.
        if kind == "assignment" and not self.assignment_spacecraft_combo.currentText():
            raise ValueError("command: assignment.target must name a spacecraft -- add a spacecraft under "
                              "Resources first")
        command = Command(kind=kind, label=label, params=self._collect_params(kind))
        errors = command.validate("command")
        if errors:
            raise ValueError("\n".join(errors))
        return command


class MissionSequenceEditorWidget(QWidget):
    """Edits a scenario's ``mission_sequence`` as an ordered tree of
    :class:`Command`. Mirrors :class:`gui.sensor_actuator_editor.
    SensorActuatorListWidget`'s Add/Edit/Remove shape, plus Add Child/Move
    Up/Move Down for tree structure and ordering that a flat list doesn't
    need.
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._spacecraft_names_provider = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add...")
        self.add_child_button = QPushButton("Add Child...")
        self.add_child_button.setToolTip("Adds a nested command inside the selected 'if'/'while' command.")
        self.edit_button = QPushButton("Edit...")
        self.remove_button = QPushButton("Remove")
        self.move_up_button = QPushButton("Move Up")
        self.move_down_button = QPushButton("Move Down")
        for button in (self.add_button, self.add_child_button, self.edit_button, self.remove_button,
                       self.move_up_button, self.move_down_button):
            button_row.addWidget(button)
        layout.addLayout(button_row)

        self.add_button.clicked.connect(self._on_add)
        self.add_child_button.clicked.connect(self._on_add_child)
        self.edit_button.clicked.connect(self._on_edit)
        self.remove_button.clicked.connect(self._on_remove)
        self.move_up_button.clicked.connect(lambda: self._on_move(-1))
        self.move_down_button.clicked.connect(lambda: self._on_move(1))
        self.tree.itemDoubleClicked.connect(lambda _item, _column: self._on_edit())
        self.tree.itemSelectionChanged.connect(self._update_button_states)
        self._update_button_states()

    def set_spacecraft_names_provider(self, provider) -> None:
        """``provider`` is a zero-argument callable returning the
        scenario's current spacecraft-name list, e.g.
        ``lambda: [sc.name for sc in self.spacecraft_list.to_list()]`` from
        ``ScenarioEditorWidget`` -- mirrors ``gui.spacecraft_editor.
        SpacecraftListWidget.set_central_body_provider``'s zero-argument
        -callable convention.
        """
        self._spacecraft_names_provider = provider

    def _spacecraft_names(self) -> list[str]:
        return sorted(self._spacecraft_names_provider()) if self._spacecraft_names_provider else []

    def _update_button_states(self) -> None:
        item = self.tree.currentItem()
        has_selection = item is not None
        self.edit_button.setEnabled(has_selection)
        self.remove_button.setEnabled(has_selection)
        self.move_up_button.setEnabled(has_selection)
        self.move_down_button.setEnabled(has_selection)
        command = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        self.add_child_button.setEnabled(command is not None and command.kind in ("if", "while"))

    @staticmethod
    def _item_text(command: Command) -> str:
        return f"{command.kind}: {command.label}" if command.label else command.kind

    def _new_item(self, command: Command) -> QTreeWidgetItem:
        # children always cleared -- see this module's docstring on why the
        # tree's own nesting, not this field, is the source of truth.
        node_command = Command(kind=command.kind, label=command.label, params=dict(command.params))
        item = QTreeWidgetItem([self._item_text(node_command)])
        item.setData(0, Qt.ItemDataRole.UserRole, node_command)
        return item

    def _on_add(self) -> None:
        dialog = _CommandEditorDialog(parent=self, spacecraft_names=self._spacecraft_names())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item = self._new_item(dialog.to_dataclass())
            self.tree.addTopLevelItem(item)
            self.tree.setCurrentItem(item)
            self.changed.emit()

    def _on_add_child(self) -> None:
        parent_item = self.tree.currentItem()
        if parent_item is None:
            return
        parent_command = parent_item.data(0, Qt.ItemDataRole.UserRole)
        if parent_command.kind not in ("if", "while"):
            return
        dialog = _CommandEditorDialog(parent=self, spacecraft_names=self._spacecraft_names())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item = self._new_item(dialog.to_dataclass())
            parent_item.addChild(item)
            parent_item.setExpanded(True)
            self.tree.setCurrentItem(item)
            self.changed.emit()

    def _on_edit(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        command = item.data(0, Qt.ItemDataRole.UserRole)
        dialog = _CommandEditorDialog(command=command, parent=self, spacecraft_names=self._spacecraft_names())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_command = dialog.to_dataclass()
            item.setData(0, Qt.ItemDataRole.UserRole, new_command)
            item.setText(0, self._item_text(new_command))
            self.changed.emit()

    def _on_remove(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        parent_item = item.parent()
        if parent_item is None:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        else:
            parent_item.removeChild(item)
        self.changed.emit()

    def _on_move(self, delta: int) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        parent_item = item.parent()
        siblings = parent_item if parent_item is not None else self.tree.invisibleRootItem()
        index = siblings.indexOfChild(item)
        new_index = index + delta
        if not (0 <= new_index < siblings.childCount()):
            return
        siblings.takeChild(index)
        siblings.insertChild(new_index, item)
        self.tree.setCurrentItem(item)
        self.changed.emit()

    def _item_to_command(self, item: QTreeWidgetItem) -> Command:
        command = item.data(0, Qt.ItemDataRole.UserRole)
        children = [self._item_to_command(item.child(i)) for i in range(item.childCount())]
        return Command(kind=command.kind, label=command.label, params=dict(command.params), children=children)

    def _build_tree_item(self, command: Command) -> QTreeWidgetItem:
        item = self._new_item(command)
        for child in command.children:
            item.addChild(self._build_tree_item(child))
        return item

    def to_command_list(self) -> list[Command]:
        return [self._item_to_command(self.tree.topLevelItem(i)) for i in range(self.tree.topLevelItemCount())]

    def from_command_list(self, commands: list[Command]) -> None:
        self.tree.clear()
        for command in commands:
            self.tree.addTopLevelItem(self._build_tree_item(command))
        self.tree.expandAll()
        self._update_button_states()
