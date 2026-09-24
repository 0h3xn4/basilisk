"""Tests for gui.mission_sequence_editor.MissionSequenceEditorWidget/_CommandEditorDialog."""

import pytest

pytestmark = pytest.mark.requires_gui


def _dialog(command=None, spacecraft_names=None):
    from missionstudio.gui.mission_sequence_editor import _CommandEditorDialog

    return _CommandEditorDialog(command=command, spacecraft_names=spacecraft_names)


def test_propagate_duration_round_trips(qtbot):
    dialog = _dialog(spacecraft_names=["sat-1"])
    qtbot.addWidget(dialog)
    dialog.label_edit.setText("Coast")
    dialog.duration_days_spin.setValue(2.5)

    command = dialog.to_dataclass()
    assert command.kind == "propagate"
    assert command.label == "Coast"
    assert command.params == {"stop_condition": "duration", "duration_days": 2.5}


def test_propagate_event_round_trips(qtbot):
    dialog = _dialog(spacecraft_names=["sat-1", "sat-2"])
    qtbot.addWidget(dialog)
    index = dialog.stop_condition_combo.findText("event")
    dialog.stop_condition_combo.setCurrentIndex(index)
    event_index = dialog.event_kind_combo.findText("apoapsis")
    dialog.event_kind_combo.setCurrentIndex(event_index)
    sc_index = dialog.propagate_event_spacecraft_combo.findText("sat-2")
    dialog.propagate_event_spacecraft_combo.setCurrentIndex(sc_index)

    command = dialog.to_dataclass()
    assert command.params == {"stop_condition": "event", "event_kind": "apoapsis", "spacecraft": "sat-2"}


def test_propagate_epoch_rejects_bad_iso8601(qtbot):
    dialog = _dialog()
    qtbot.addWidget(dialog)
    index = dialog.stop_condition_combo.findText("epoch")
    dialog.stop_condition_combo.setCurrentIndex(index)
    dialog.stop_epoch_edit.setText("not a date")

    with pytest.raises(ValueError, match="not a valid ISO 8601"):
        dialog.to_dataclass()


def test_maneuver_round_trips(qtbot):
    dialog = _dialog(spacecraft_names=["sat-1"])
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("maneuver")
    dialog.kind_combo.setCurrentIndex(index)
    sc_index = dialog.maneuver_spacecraft_combo.findText("sat-1")
    dialog.maneuver_spacecraft_combo.setCurrentIndex(sc_index)
    dialog.delta_v_x_spin.setValue(1.0)
    dialog.delta_v_y_spin.setValue(2.0)
    dialog.delta_v_z_spin.setValue(3.0)
    frame_index = dialog.maneuver_frame_combo.findText("vnb")
    dialog.maneuver_frame_combo.setCurrentIndex(frame_index)

    command = dialog.to_dataclass()
    assert command.kind == "maneuver"
    assert command.params == {"spacecraft": "sat-1", "delta_v_m_s": [1.0, 2.0, 3.0], "frame": "vnb"}


def test_maneuver_rejects_missing_spacecraft(qtbot):
    dialog = _dialog(spacecraft_names=[])  # no spacecraft defined yet -- combo stays empty
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("maneuver")
    dialog.kind_combo.setCurrentIndex(index)

    with pytest.raises(ValueError, match="spacecraft"):
        dialog.to_dataclass()


def test_assignment_round_trips(qtbot):
    dialog = _dialog(spacecraft_names=["sat-1"])
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("assignment")
    dialog.kind_combo.setCurrentIndex(index)
    sc_index = dialog.assignment_spacecraft_combo.findText("sat-1")
    dialog.assignment_spacecraft_combo.setCurrentIndex(sc_index)
    controller_index = dialog.assignment_controller_combo.findText("station_keeping")
    dialog.assignment_controller_combo.setCurrentIndex(controller_index)
    parameter_index = dialog.assignment_parameter_combo.findText("thrust_n")
    dialog.assignment_parameter_combo.setCurrentIndex(parameter_index)
    dialog.assignment_value_spin.setValue(0.5)

    command = dialog.to_dataclass()
    assert command.kind == "assignment"
    assert command.params == {"target": "sat-1.station_keeping.thrust_n", "value": 0.5}


def test_assignment_dialog_prefills_target_from_existing_command(qtbot):
    from missionstudio.schema.command import Command

    existing = Command(kind="assignment", params={"target": "sat-1.phasing_keeping.isp_s", "value": 220.0})
    dialog = _dialog(command=existing, spacecraft_names=["sat-1"])
    qtbot.addWidget(dialog)

    assert dialog.assignment_spacecraft_combo.currentText() == "sat-1"
    assert dialog.assignment_controller_combo.currentText() == "phasing_keeping"
    assert dialog.assignment_parameter_combo.currentText() == "isp_s"
    assert dialog.assignment_value_spin.value() == pytest.approx(220.0)


def test_assignment_rejects_missing_spacecraft(qtbot):
    """Regression guard: Command.validate() alone doesn't reject a blank
    spacecraft segment in assignment.target (only that the string contains
    a '.'), unlike maneuver/propagate's explicit spacecraft checks -- so
    to_dataclass() must reject it itself before it ever reaches
    Command.validate().
    """
    dialog = _dialog(spacecraft_names=[])  # no spacecraft defined yet -- combo stays empty
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("assignment")
    dialog.kind_combo.setCurrentIndex(index)

    with pytest.raises(ValueError, match="spacecraft"):
        dialog.to_dataclass()


def test_report_series_round_trips_as_line_list(qtbot):
    dialog = _dialog()
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("report")
    dialog.kind_combo.setCurrentIndex(index)
    dialog.report_series_edit.setPlainText("sat-1.position_N\nsat-1.mass_kg\n")

    command = dialog.to_dataclass()
    assert command.params == {"series": ["sat-1.position_N", "sat-1.mass_kg"]}


def test_report_empty_series_means_snapshot_everything(qtbot):
    dialog = _dialog()
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("report")
    dialog.kind_combo.setCurrentIndex(index)

    command = dialog.to_dataclass()
    assert command.params == {"series": []}


def test_if_condition_round_trips(qtbot):
    dialog = _dialog()
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("if")
    dialog.kind_combo.setCurrentIndex(index)
    dialog.condition_edit.setText("t_s > 3600")

    command = dialog.to_dataclass()
    assert command.kind == "if"
    assert command.params == {"condition": "t_s > 3600"}


def test_if_rejects_empty_condition(qtbot):
    dialog = _dialog()
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("while")
    dialog.kind_combo.setCurrentIndex(index)

    with pytest.raises(ValueError, match="condition"):
        dialog.to_dataclass()


def test_script_block_round_trips(qtbot):
    dialog = _dialog()
    qtbot.addWidget(dialog)
    index = dialog.kind_combo.findText("script_block")
    dialog.kind_combo.setCurrentIndex(index)
    dialog.script_code_edit.setPlainText("summary.commands_executed += 1")

    command = dialog.to_dataclass()
    assert command.kind == "script_block"
    assert command.params == {"code": "summary.commands_executed += 1"}


def test_kind_combo_disabled_when_editing_existing_command(qtbot):
    from missionstudio.schema.command import Command

    dialog = _dialog(command=Command(kind="propagate", params={"duration_days": 1.0}))
    qtbot.addWidget(dialog)
    assert not dialog.kind_combo.isEnabled()


def test_widget_add_edit_remove_top_level(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.mission_sequence_editor import MissionSequenceEditorWidget, _CommandEditorDialog

    widget = MissionSequenceEditorWidget()
    qtbot.addWidget(widget)
    widget.set_spacecraft_names_provider(lambda: ["sat-1"])

    def fake_exec(self):
        self.duration_days_spin.setValue(1.5)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_CommandEditorDialog, "exec", fake_exec)
    changed_count = []
    widget.changed.connect(lambda: changed_count.append(1))

    widget._on_add()
    assert widget.tree.topLevelItemCount() == 1
    commands = widget.to_command_list()
    assert len(commands) == 1
    assert commands[0].kind == "propagate"
    assert commands[0].params["duration_days"] == 1.5
    assert changed_count == [1]

    def fake_edit_exec(self):
        self.label_edit.setText("renamed")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_CommandEditorDialog, "exec", fake_edit_exec)
    widget.tree.setCurrentItem(widget.tree.topLevelItem(0))
    widget._on_edit()
    assert widget.to_command_list()[0].label == "renamed"

    widget.tree.setCurrentItem(widget.tree.topLevelItem(0))
    widget._on_remove()
    assert widget.to_command_list() == []


def test_add_child_only_enabled_for_if_while(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.mission_sequence_editor import MissionSequenceEditorWidget, _CommandEditorDialog

    widget = MissionSequenceEditorWidget()
    qtbot.addWidget(widget)

    def fake_exec_propagate(self):
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_CommandEditorDialog, "exec", fake_exec_propagate)
    widget._on_add()  # default kind is "propagate"
    widget.tree.setCurrentItem(widget.tree.topLevelItem(0))
    assert not widget.add_child_button.isEnabled()

    def fake_exec_while(self):
        index = self.kind_combo.findText("while")
        self.kind_combo.setCurrentIndex(index)
        self.condition_edit.setText("t_s < 10")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_CommandEditorDialog, "exec", fake_exec_while)
    widget._on_add()
    widget.tree.setCurrentItem(widget.tree.topLevelItem(1))
    assert widget.add_child_button.isEnabled()


def test_add_child_nests_command_and_round_trips(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.mission_sequence_editor import MissionSequenceEditorWidget, _CommandEditorDialog

    widget = MissionSequenceEditorWidget()
    qtbot.addWidget(widget)

    def fake_exec_while(self):
        index = self.kind_combo.findText("while")
        self.kind_combo.setCurrentIndex(index)
        self.condition_edit.setText("t_s < 10")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_CommandEditorDialog, "exec", fake_exec_while)
    widget._on_add()
    parent_item = widget.tree.topLevelItem(0)
    widget.tree.setCurrentItem(parent_item)

    def fake_exec_report(self):
        index = self.kind_combo.findText("report")
        self.kind_combo.setCurrentIndex(index)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_CommandEditorDialog, "exec", fake_exec_report)
    widget._on_add_child()

    assert parent_item.childCount() == 1
    commands = widget.to_command_list()
    assert len(commands) == 1
    assert commands[0].kind == "while"
    assert len(commands[0].children) == 1
    assert commands[0].children[0].kind == "report"


def test_move_up_down_reorders_siblings(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.mission_sequence_editor import MissionSequenceEditorWidget, _CommandEditorDialog

    widget = MissionSequenceEditorWidget()
    qtbot.addWidget(widget)

    for label in ("first", "second"):
        def fake_exec(self, label=label):
            self.label_edit.setText(label)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(_CommandEditorDialog, "exec", fake_exec)
        widget._on_add()

    assert [c.label for c in widget.to_command_list()] == ["first", "second"]

    widget.tree.setCurrentItem(widget.tree.topLevelItem(1))  # "second"
    widget._on_move(-1)
    assert [c.label for c in widget.to_command_list()] == ["second", "first"]

    widget._on_move(1)
    assert [c.label for c in widget.to_command_list()] == ["first", "second"]


def test_from_command_list_to_command_list_round_trip(qtbot):
    from missionstudio.gui.mission_sequence_editor import MissionSequenceEditorWidget
    from missionstudio.schema.command import Command

    widget = MissionSequenceEditorWidget()
    qtbot.addWidget(widget)

    commands = [
        Command(kind="propagate", label="coast", params={"stop_condition": "duration", "duration_days": 1.0}),
        Command(kind="while", params={"condition": "t_s < 100"}, children=[
            Command(kind="report", params={"series": []}),
        ]),
    ]
    widget.from_command_list(commands)

    assert widget.tree.topLevelItemCount() == 2
    assert widget.tree.topLevelItem(1).childCount() == 1

    got = widget.to_command_list()
    assert len(got) == 2
    assert got[0].label == "coast"
    assert got[1].kind == "while"
    assert len(got[1].children) == 1
    assert got[1].children[0].kind == "report"


def test_editing_child_does_not_stale_parent_children_field(qtbot, monkeypatch):
    """Regression guard for this module's own documented invariant: a
    parent's stored Command.children is always cleared (see _new_item),
    so to_command_list() must reflect an edited child via tree structure,
    never a stale copy captured when the parent was built.
    """
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.mission_sequence_editor import MissionSequenceEditorWidget, _CommandEditorDialog
    from missionstudio.schema.command import Command

    widget = MissionSequenceEditorWidget()
    qtbot.addWidget(widget)
    widget.from_command_list([
        Command(kind="if", params={"condition": "t_s > 0"}, children=[
            Command(kind="report", label="before", params={"series": []}),
        ]),
    ])

    child_item = widget.tree.topLevelItem(0).child(0)
    widget.tree.setCurrentItem(child_item)

    def fake_exec(self):
        self.label_edit.setText("after")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_CommandEditorDialog, "exec", fake_exec)
    widget._on_edit()

    got = widget.to_command_list()
    assert got[0].children[0].label == "after"
