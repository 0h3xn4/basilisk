"""Tests for missionstudio.schema.validation.validate_all -- no Basilisk
import, runs anywhere.
"""

from missionstudio.schema.command import Command
from missionstudio.schema.scenario import OrbitIC, Scenario, SpacecraftConfig
from missionstudio.schema.validation import validate_all


def _orbit():
    return OrbitIC(type="cartesian", position_km=[7000.0, 0.0, 0.0], velocity_km_s=[0.0, 7.5, 0.0])


def _scenario(**overrides):
    defaults = dict(
        name="validate_all test", epoch_utc="2030-01-01T00:00:00",
        spacecraft=[SpacecraftConfig(name="sat-1", orbit=_orbit())],
    )
    defaults.update(overrides)
    return Scenario(**defaults)


def test_valid_scenario_has_no_errors():
    assert validate_all(_scenario()) == []


def test_invalid_resource_reports_one_error():
    scenario = _scenario(spacecraft=[])  # Scenario.validate() raises on this first
    errors = validate_all(scenario)
    assert len(errors) == 1
    assert "at least one spacecraft" in errors[0]


def test_collects_every_bad_command_not_just_the_first():
    """The key requirement Scenario.validate() itself deliberately does
    NOT provide (it stays raise-fast, see schema.validation's module
    docstring for why) -- validate_all() must report every command's
    problems, not stop at the first bad command.
    """
    scenario = _scenario(mission_sequence=[
        Command(kind="maneuver", params={}),  # missing spacecraft + delta_v_m_s
        Command(kind="script_block", params={}),  # missing code
        Command(kind="propagate", params={"stop_condition": "bogus"}),  # bad stop_condition
    ])

    errors = validate_all(scenario)

    assert any("mission_sequence[0]" in e for e in errors)
    assert any("mission_sequence[1]" in e for e in errors)
    assert any("mission_sequence[2]" in e for e in errors)
    assert len(errors) >= 4  # at least: 2 from command 0, 1 from command 1, 1 from command 2


def test_collects_dangling_spacecraft_reference():
    scenario = _scenario(mission_sequence=[
        Command(kind="maneuver", params={"spacecraft": "does-not-exist", "delta_v_m_s": [1.0, 0.0, 0.0]}),
    ])

    errors = validate_all(scenario)

    assert any("does-not-exist" in e and "not one of this scenario's spacecraft" in e for e in errors)


def test_collects_multiple_dangling_references_across_commands():
    scenario = _scenario(mission_sequence=[
        Command(kind="maneuver", params={"spacecraft": "ghost-1", "delta_v_m_s": [1.0, 0.0, 0.0]}),
        Command(kind="maneuver", params={"spacecraft": "ghost-2", "delta_v_m_s": [1.0, 0.0, 0.0]}),
    ])

    errors = validate_all(scenario)

    assert any("ghost-1" in e for e in errors)
    assert any("ghost-2" in e for e in errors)


def test_dangling_reference_nested_in_if_is_collected():
    scenario = _scenario(mission_sequence=[
        Command(kind="if", params={"condition": "True"}, children=[
            Command(kind="maneuver", params={"spacecraft": "ghost", "delta_v_m_s": [1.0, 0.0, 0.0]}),
        ]),
    ])

    errors = validate_all(scenario)

    assert any("ghost" in e for e in errors)


def test_valid_mission_sequence_referencing_real_spacecraft_has_no_errors():
    scenario = _scenario(mission_sequence=[
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": 1.0}),
        Command(kind="maneuver", params={"spacecraft": "sat-1", "delta_v_m_s": [1.0, 0.0, 0.0]}),
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": 1.0}),
    ])
    assert validate_all(scenario) == []
