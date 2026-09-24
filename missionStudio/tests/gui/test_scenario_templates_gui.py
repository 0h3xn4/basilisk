"""Confirms every template in missionstudio/scenarios/templates/ actually
round-trips through the GUI's own ScenarioEditorWidget -- the primary way
a user is expected to open one (File > Open) -- not just through
schema.scenario.load_scenario()/validate() directly (see
tests/test_scenario_templates.py for that Basilisk-free layer).
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_gui

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "missionstudio" / "scenarios" / "templates"
_TEMPLATE_PATHS = sorted(_TEMPLATES_DIR.glob("*.json"))


@pytest.mark.parametrize("path", _TEMPLATE_PATHS, ids=lambda p: p.name)
def test_template_round_trips_through_scenario_editor_widget(qtbot, path):
    from missionstudio.gui.scenario_editor import ScenarioEditorWidget
    from missionstudio.schema import load_scenario

    widget = ScenarioEditorWidget()
    qtbot.addWidget(widget)

    scenario = load_scenario(path)
    widget.from_scenario(scenario)
    assert "✓" in widget.validation_label.text(), widget.validation_label.text()

    got = widget.to_scenario()
    assert got.to_dict() == scenario.to_dict()
