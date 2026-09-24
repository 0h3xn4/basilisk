"""Tests for missionstudio/scenarios/templates/*.json -- the education/
starter-template scenarios (see that directory's own README). Basilisk
-free: these only exercise schema.scenario.load_scenario()/validate(),
the same path the GUI's File > Open and the CLI's `validate`/`run`
subcommands go through, never an actual Basilisk propagation.
"""

from pathlib import Path

import pytest

from missionstudio.schema import load_scenario

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "missionstudio" / "scenarios" / "templates"
_TEMPLATE_PATHS = sorted(_TEMPLATES_DIR.glob("*.json"))


def test_at_least_one_template_exists():
    # A guard against the glob above silently matching nothing (e.g. the
    # directory got renamed/moved) and every parametrized test below
    # collecting zero cases, which would pass "successfully" while
    # testing nothing at all.
    assert len(_TEMPLATE_PATHS) >= 9


@pytest.mark.parametrize("path", _TEMPLATE_PATHS, ids=lambda p: p.name)
def test_template_loads_and_validates(path):
    scenario = load_scenario(path)
    scenario.validate()  # must not raise


@pytest.mark.parametrize("path", _TEMPLATE_PATHS, ids=lambda p: p.name)
def test_template_has_at_least_one_spacecraft(path):
    scenario = load_scenario(path)
    assert len(scenario.spacecraft) >= 1


@pytest.mark.parametrize("path", _TEMPLATE_PATHS, ids=lambda p: p.name)
def test_template_has_a_substantial_description(path):
    """Every template's whole point is to explain a concept -- a blank or
    one-line description would defeat that, so this is checked directly
    rather than just trusting the generator script forever gets it right.
    """
    scenario = load_scenario(path)
    assert len(scenario.description) > 200


@pytest.mark.parametrize("path", _TEMPLATE_PATHS, ids=lambda p: p.name)
def test_template_round_trips_through_save_load(path, tmp_path):
    scenario = load_scenario(path)
    out_path = tmp_path / path.name
    scenario.save(out_path)
    round_tripped = load_scenario(out_path)
    round_tripped.validate()
    assert round_tripped.to_dict() == scenario.to_dict()


def test_walker_constellation_template_has_six_uniquely_named_satellites():
    scenario = load_scenario(_TEMPLATES_DIR / "04_walker_constellation.json")
    names = [sc.name for sc in scenario.spacecraft]
    assert len(names) == 6
    assert len(set(names)) == 6


def test_mission_sequence_template_has_a_maneuver_command():
    scenario = load_scenario(_TEMPLATES_DIR / "08_mission_sequence_orbit_raise.json")
    kinds = [c.kind for c in scenario.mission_sequence]
    assert "maneuver" in kinds


def test_monte_carlo_template_has_monte_carlo_enabled():
    scenario = load_scenario(_TEMPLATES_DIR / "09_monte_carlo_dispersion_analysis.json")
    assert scenario.monte_carlo.enabled
    assert len(scenario.monte_carlo.dispersions) >= 1


def test_phasing_template_pairs_phasing_keeping_with_station_keeping():
    """Regression guard for PhasingKeepingConfig's own documented
    requirement (also enforced by Scenario.validate() itself) -- if a
    future edit to this template ever drops the paired station_keeping,
    this fails clearly instead of only failing deep inside validate()'s
    generic error message.
    """
    scenario = load_scenario(_TEMPLATES_DIR / "05_formation_flying_phasing.json")
    follower = next(sc for sc in scenario.spacecraft if sc.phasing_keeping is not None)
    assert follower.station_keeping is not None
