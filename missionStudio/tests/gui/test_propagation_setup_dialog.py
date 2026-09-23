"""Tests for gui.propagation_setup_dialog.PropagationSetupDialog."""

import pytest

pytestmark = pytest.mark.requires_gui


def _dialog(gravity=None, sim_settings=None, space_weather=None):
    from missionstudio.gui.propagation_setup_dialog import PropagationSetupDialog
    from missionstudio.schema.scenario import GravityConfig, SimSettings, SpaceWeatherConfig

    return PropagationSetupDialog(
        gravity or GravityConfig(), sim_settings or SimSettings(), space_weather or SpaceWeatherConfig(),
    )


@pytest.fixture
def dialog(qtbot):
    d = _dialog()
    qtbot.addWidget(d)
    return d


def test_defaults_round_trip(dialog):
    got_gravity = dialog.to_gravity()
    got_sim = dialog.to_sim_settings()
    got_sw = dialog.to_space_weather()
    from missionstudio.schema.scenario import GravityConfig, SimSettings, SpaceWeatherConfig

    assert got_gravity == GravityConfig()
    assert got_sim == SimSettings()
    assert got_sw == SpaceWeatherConfig()


def test_central_body_removed_from_third_body_choices(dialog):
    dialog.central_body_combo.setCurrentText("sun")
    choices = [dialog.third_body_list.item(i).text() for i in range(dialog.third_body_list.count())]
    assert "sun" not in choices
    assert "earth" in choices


def test_third_body_perturbers_round_trip(qtbot):
    from missionstudio.schema.scenario import GravityConfig

    d = _dialog(gravity=GravityConfig(central_body="earth", third_body_perturbers=["sun", "moon"]))
    qtbot.addWidget(d)
    assert sorted(d.to_gravity().third_body_perturbers) == ["moon", "sun"]


def test_space_weather_local_file_field_enabled_only_for_local_file_source(dialog):
    assert not dialog.local_file_edit.isEnabled()
    dialog.space_weather_source_combo.setCurrentText("local_file")
    assert dialog.local_file_edit.isEnabled()
    dialog.space_weather_source_combo.setCurrentText("synthetic")
    assert not dialog.local_file_edit.isEnabled()


def test_harmonics_checkbox_off_by_default_forces_point_mass(dialog):
    assert not dialog.enable_harmonics_check.isChecked()
    assert dialog.to_gravity().central_body_degree == 0


def test_harmonics_checkbox_preserves_spinner_value_when_toggled_off(dialog):
    """Regression guard for the actual UX fix this dialog makes: unchecking
    "enable spherical harmonics" must not reset/lose the degree the user
    typed -- only fold it to 0 in the OUTPUT (to_gravity()), leaving the
    spinner itself untouched so re-checking the box brings it right back.
    """
    dialog.enable_harmonics_check.setChecked(True)
    dialog.central_body_degree_spin.setValue(20)
    assert dialog.to_gravity().central_body_degree == 20

    dialog.enable_harmonics_check.setChecked(False)
    assert dialog.to_gravity().central_body_degree == 0
    assert dialog.central_body_degree_spin.value() == 20  # not reset

    dialog.enable_harmonics_check.setChecked(True)
    assert dialog.to_gravity().central_body_degree == 20  # comes right back


def test_checking_harmonics_with_zero_degree_bumps_to_a_sane_default(dialog):
    dialog.central_body_degree_spin.setValue(0)
    dialog.enable_harmonics_check.setChecked(True)
    assert dialog.central_body_degree_spin.value() > 0
    assert dialog.to_gravity().central_body_degree > 0


def test_non_earth_central_body_disables_and_clears_harmonics(dialog):
    dialog.enable_harmonics_check.setChecked(True)
    dialog.central_body_degree_spin.setValue(20)

    dialog.central_body_combo.setCurrentText("mars")

    assert not dialog.enable_harmonics_check.isEnabled()
    assert not dialog.enable_harmonics_check.isChecked()
    assert dialog.to_gravity().central_body_degree == 0


def test_loading_existing_harmonics_degree_checks_the_box(qtbot):
    from missionstudio.schema.scenario import GravityConfig

    d = _dialog(gravity=GravityConfig(central_body="earth", central_body_degree=8))
    qtbot.addWidget(d)
    assert d.enable_harmonics_check.isChecked()
    assert d.central_body_degree_spin.value() == 8
    assert d.to_gravity().central_body_degree == 8


def test_accept_with_valid_state_closes_dialog(dialog, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialogButtonBox

    ok_button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
    qtbot.mouseClick(ok_button, Qt.MouseButton.LeftButton)
    assert dialog.result() == dialog.DialogCode.Accepted
