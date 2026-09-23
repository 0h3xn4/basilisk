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


def test_simulation_mode_defaults_to_full_attitude(widget):
    assert widget.simulation_mode_combo.currentData() == "full_attitude"
    assert widget.spacecraft_list._simulation_mode() == "full_attitude"


def test_simulation_mode_round_trips(widget):
    from missionstudio.schema import load_scenario

    scenario = load_scenario(_SCENARIO_PATH)
    scenario.simulation_mode = "orbit_only"
    scenario.spacecraft[0].sensors = []
    scenario.spacecraft[0].actuators = []
    scenario.spacecraft[0].fsw_mode = None
    scenario.spacecraft[0].power = None
    widget.from_scenario(scenario)

    assert widget.simulation_mode_combo.currentData() == "orbit_only"
    got = widget.to_scenario()
    assert got.simulation_mode == "orbit_only"


def test_simulation_mode_combo_drives_spacecraft_list_provider(widget):
    widget.simulation_mode_combo.setCurrentIndex(widget.simulation_mode_combo.findData("orbit_only"))
    assert widget.spacecraft_list._simulation_mode() == "orbit_only"

    widget.simulation_mode_combo.setCurrentIndex(widget.simulation_mode_combo.findData("full_attitude"))
    assert widget.spacecraft_list._simulation_mode() == "full_attitude"


def test_propagation_summary_reflects_defaults(widget):
    assert "earth" in widget.propagation_summary_label.text()
    assert "point-mass" in widget.propagation_summary_label.text()


def test_edit_propagation_setup_updates_state_and_emits_changed(widget, qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.propagation_setup_dialog import PropagationSetupDialog
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig

    widget.spacecraft_list.from_list([
        SpacecraftConfig(name="sat-1", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0],
                                                       velocity_km_s=[0, 7.5, 0]))
    ])

    def fake_exec(self):
        self.central_body_degree_spin.setValue(4)
        self.enable_harmonics_check.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(PropagationSetupDialog, "exec", fake_exec)

    with qtbot.waitSignal(widget.changed, timeout=1000):
        widget._on_edit_propagation_setup()

    assert widget._gravity.central_body_degree == 4
    assert "harmonics" in widget.propagation_summary_label.text()

    got = widget.to_scenario()
    assert got.gravity.central_body_degree == 4


def test_edit_propagation_setup_cancel_leaves_state_unchanged(widget, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.propagation_setup_dialog import PropagationSetupDialog

    monkeypatch.setattr(PropagationSetupDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

    before = widget._gravity
    widget._on_edit_propagation_setup()
    assert widget._gravity is before


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


def test_monte_carlo_round_trips(widget):
    from missionstudio.schema.scenario import DispersionConfig, MonteCarloConfig, OrbitIC, SpacecraftConfig

    widget.spacecraft_list.from_list([
        SpacecraftConfig(name="sat-1", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0],
                                                       velocity_km_s=[0, 7.5, 0]))
    ])
    widget._refresh_monte_carlo_spacecraft_names()
    mc = MonteCarloConfig(
        enabled=True, num_runs=15, thread_count=2, verbose=True,
        dispersions=[DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="uniform", bounds=[95, 105])],
    )
    widget.monte_carlo_group.from_dataclass(mc)

    got = widget.to_scenario()
    assert got.monte_carlo.enabled is True
    assert got.monte_carlo.num_runs == 15
    assert got.monte_carlo.thread_count == 2
    assert got.monte_carlo.dispersions[0].spacecraft == "sat-1"


def test_monte_carlo_spacecraft_names_track_spacecraft_list(widget):
    from missionstudio.schema.scenario import OrbitIC, SpacecraftConfig

    assert widget.monte_carlo_group.dispersion_list._spacecraft_names == []
    widget.spacecraft_list.from_list([
        SpacecraftConfig(name="a", orbit=OrbitIC(type="cartesian", position_km=[7000, 0, 0], velocity_km_s=[0, 7.5, 0])),
    ])
    widget.spacecraft_list.changed.emit()
    assert widget.monte_carlo_group.dispersion_list._spacecraft_names == ["a"]


def test_reset_to_default_clears_spacecraft(widget):
    from missionstudio.schema import load_scenario

    widget.from_scenario(load_scenario(_SCENARIO_PATH))
    assert len(widget.spacecraft_list.to_list()) == 1
    widget.reset_to_default()
    assert widget.spacecraft_list.to_list() == []
