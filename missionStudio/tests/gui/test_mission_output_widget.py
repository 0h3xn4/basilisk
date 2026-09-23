"""Tests for gui.mission_output_widget.MissionOutputWidget."""

import numpy as np
import pytest

pytestmark = pytest.mark.requires_gui


def test_none_summary_clears_text(qtbot):
    from missionstudio.gui.mission_output_widget import MissionOutputWidget

    widget = MissionOutputWidget()
    qtbot.addWidget(widget)
    widget.text_edit.setPlainText("stale content")

    widget.set_command_summary(None)
    assert widget.text_edit.toPlainText() == ""


def test_summary_lists_reports_in_order_with_values(qtbot):
    from missionstudio.engine.results import CommandSummary, ReportEntry
    from missionstudio.gui.mission_output_widget import MissionOutputWidget

    widget = MissionOutputWidget()
    qtbot.addWidget(widget)

    summary = CommandSummary(reports=[
        ReportEntry(label="checkpoint", t_s=100.0, values={"sat-1.position_N": np.array([1.0, 2.0, 3.0])}),
        ReportEntry(label=None, t_s=200.0, values={"sat-1.mass_kg": np.array([500.0])}),
    ], commands_executed=7)

    widget.set_command_summary(summary)
    text = widget.text_edit.toPlainText()

    assert "7 command(s) executed, 2 report(s)" in text
    assert "t = 100.000 s (checkpoint)" in text
    assert "sat-1.position_N = [1.0, 2.0, 3.0]" in text
    assert "t = 200.000 s" in text
    assert "sat-1.mass_kg = [500.0]" in text


def test_clear_empties_text(qtbot):
    from missionstudio.gui.mission_output_widget import MissionOutputWidget

    widget = MissionOutputWidget()
    qtbot.addWidget(widget)
    widget.text_edit.setPlainText("something")
    widget.clear()
    assert widget.text_edit.toPlainText() == ""
