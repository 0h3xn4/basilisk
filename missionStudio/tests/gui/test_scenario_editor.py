"""Tests for gui.scenario_editor.ScenarioEditorWidget."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_gui

_SCENARIO_PATH = Path(__file__).resolve().parent.parent.parent / "missionstudio" / "scenarios" / "two_body_validation.json"


@pytest.fixture
def widget(qtbot):
    from missionstudio.gui.scenario_editor import ScenarioEditorWidget

    w = ScenarioEditorWidget()
    qtbot.addWidget(w)
    return w


def test_default_state_is_invalid_with_no_spacecraft(widget):
    assert "⚠" in widget.validation_label.text()
    assert "spacecraft" in widget.validation_label.text().lower()


def test_full_round_trip_matches_loaded_scenario(widget):
    from missionstudio.schema import load_scenario

    scenario = load_scenario(_SCENARIO_PATH)
    widget.from_scenario(scenario)
    assert "✓" in widget.validation_label.text()

    got = widget.to_scenario()
    assert got.name == scenario.name
    assert got.epoch_utc == scenario.epoch_utc
    assert got.gravity.central_body == scenario.gravity.central_body
    assert got.gravity.central_body_degree == scenario.gravity.central_body_degree
    assert got.sim_settings.duration_days == scenario.sim_settings.duration_days
    assert got.sim_settings.integrator == scenario.sim_settings.integrator
    assert len(got.spacecraft) == 1
    assert got.spacecraft[0].name == scenario.spacecraft[0].name
    assert got.spacecraft[0].orbit == scenario.spacecraft[0].orbit


def test_third_body_perturbers_round_trip(widget):
    from missionstudio.schema.scenario import GravityConfig, Scenario, SpacecraftConfig, OrbitIC

    scenario = Scenario(
        name="t", epoch_utc="2030-01-01T00:00:00",
        gravity=GravityConfig(central_body="earth", central_body_degree=0, third_body_perturbers=["sun", "moon"]),
        spacecraft=[SpacecraftConfig(name="s", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0],
                                                               velocity_km_s=[0, 7.5, 0]))],
    )
    widget.from_scenario(scenario)
    got = widget.to_scenario()
    assert sorted(got.gravity.third_body_perturbers) == ["moon", "sun"]


def test_central_body_removed_from_third_body_choices(widget):
    widget.central_body_combo.setCurrentText("sun")
    choices = [widget.third_body_list.item(i).text() for i in range(widget.third_body_list.count())]
    assert "sun" not in choices
    assert "earth" in choices


def test_live_validation_reacts_to_bad_edit(widget, qtbot):
    from missionstudio.schema import load_scenario

    widget.from_scenario(load_scenario(_SCENARIO_PATH))
    assert "✓" in widget.validation_label.text()

    with qtbot.waitSignal(widget.changed, timeout=1000):
        widget.name_edit.setText("")
    assert "⚠" in widget.validation_label.text()
    assert "name must not be empty" in widget.validation_label.text()


def test_to_scenario_raises_on_invalid_state(widget):
    from missionstudio.schema.scenario import ScenarioValidationError

    with pytest.raises(ScenarioValidationError):
        widget.to_scenario()  # no spacecraft yet


def test_space_weather_local_file_field_enabled_only_for_local_file_source(widget):
    assert not widget.local_file_edit.isEnabled()
    widget.space_weather_source_combo.setCurrentText("local_file")
    assert widget.local_file_edit.isEnabled()
    widget.space_weather_source_combo.setCurrentText("synthetic")
    assert not widget.local_file_edit.isEnabled()


def test_reset_to_default_clears_spacecraft(widget):
    from missionstudio.schema import load_scenario

    widget.from_scenario(load_scenario(_SCENARIO_PATH))
    assert len(widget.spacecraft_list.to_list()) == 1
    widget.reset_to_default()
    assert widget.spacecraft_list.to_list() == []
