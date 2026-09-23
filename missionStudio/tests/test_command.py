"""Tests for missionstudio.schema.command.Command -- no Basilisk import,
runs anywhere.
"""

from dataclasses import asdict

from missionstudio.schema.command import Command


def test_default_command_has_no_children():
    assert Command(kind="script_block", params={"code": "x = 1"}).children == []


def test_unknown_kind_is_rejected():
    errors = Command(kind="nonsense").validate("mission_sequence[0]")
    assert len(errors) == 1
    assert "nonsense" in errors[0]
    assert "mission_sequence[0]" in errors[0]


def test_label_appears_in_error_paths():
    errors = Command(kind="nonsense", label="My Command").validate("mission_sequence[0]")
    assert "'My Command'" in errors[0]


# -- propagate -----------------------------------------------------------

def test_propagate_duration_valid():
    assert Command(kind="propagate", params={"stop_condition": "duration", "duration_days": 1.0}).validate("p") == []


def test_propagate_duration_missing_is_rejected():
    errors = Command(kind="propagate", params={"stop_condition": "duration"}).validate("p")
    assert any("duration_days" in e for e in errors)


def test_propagate_duration_zero_is_rejected():
    errors = Command(kind="propagate", params={"stop_condition": "duration", "duration_days": 0}).validate("p")
    assert any("duration_days" in e for e in errors)


def test_propagate_epoch_valid():
    cmd = Command(kind="propagate", params={"stop_condition": "epoch", "stop_epoch_utc": "2030-01-02T00:00:00"})
    assert cmd.validate("p") == []


def test_propagate_epoch_malformed_is_rejected():
    errors = Command(kind="propagate", params={"stop_condition": "epoch", "stop_epoch_utc": "not-a-date"}).validate("p")
    assert any("stop_epoch_utc" in e for e in errors)


def test_propagate_event_valid():
    cmd = Command(kind="propagate",
                  params={"stop_condition": "event", "event_kind": "periapsis", "spacecraft": "sat-1"})
    assert cmd.validate("p") == []


def test_propagate_event_missing_spacecraft_is_rejected():
    errors = Command(kind="propagate", params={"stop_condition": "event", "event_kind": "periapsis"}).validate("p")
    assert any("spacecraft" in e for e in errors)


def test_propagate_event_bad_kind_is_rejected():
    errors = Command(kind="propagate",
                      params={"stop_condition": "event", "event_kind": "sunrise", "spacecraft": "sat-1"}).validate("p")
    assert any("event_kind" in e for e in errors)


def test_propagate_bad_stop_condition_is_rejected():
    errors = Command(kind="propagate", params={"stop_condition": "bogus"}).validate("p")
    assert any("stop_condition" in e for e in errors)


# -- maneuver --------------------------------------------------------------

def test_maneuver_valid():
    cmd = Command(kind="maneuver", params={"spacecraft": "sat-1", "delta_v_m_s": [1.0, 0.0, 0.0]})
    assert cmd.validate("m") == []


def test_maneuver_defaults_to_inertial_frame():
    cmd = Command(kind="maneuver", params={"spacecraft": "sat-1", "delta_v_m_s": [1.0, 0.0, 0.0]})
    assert cmd.validate("m") == []  # frame omitted -> "inertial" default is valid


def test_maneuver_missing_spacecraft_is_rejected():
    errors = Command(kind="maneuver", params={"delta_v_m_s": [1.0, 0.0, 0.0]}).validate("m")
    assert any("spacecraft" in e for e in errors)


def test_maneuver_bad_delta_v_shape_is_rejected():
    errors = Command(kind="maneuver", params={"spacecraft": "sat-1", "delta_v_m_s": [1.0, 0.0]}).validate("m")
    assert any("delta_v_m_s" in e for e in errors)


def test_maneuver_bad_frame_is_rejected():
    errors = Command(kind="maneuver",
                      params={"spacecraft": "sat-1", "delta_v_m_s": [1.0, 0.0, 0.0], "frame": "lvlh"}).validate("m")
    assert any("frame" in e for e in errors)


def test_maneuver_reports_every_problem_at_once():
    """The key requirement: a collecting validate(), not raise-fast."""
    errors = Command(kind="maneuver", params={}).validate("m")
    assert len(errors) >= 2  # missing spacecraft AND missing delta_v_m_s, both reported -- not just the first
    assert any("spacecraft" in e for e in errors)
    assert any("delta_v_m_s" in e for e in errors)


# -- assignment / report ----------------------------------------------------

def test_assignment_valid():
    cmd = Command(kind="assignment", params={"target": "sat-1.station_keeping.thrust_n", "value": 0.5})
    assert cmd.validate("a") == []


def test_assignment_missing_value_is_rejected():
    errors = Command(kind="assignment", params={"target": "sat-1.x"}).validate("a")
    assert any("value" in e for e in errors)


def test_assignment_target_without_dot_is_rejected():
    errors = Command(kind="assignment", params={"target": "sat-1", "value": 1}).validate("a")
    assert any("target" in e for e in errors)


def test_report_empty_series_is_valid():
    assert Command(kind="report", params={}).validate("r") == []


def test_report_bad_series_type_is_rejected():
    errors = Command(kind="report", params={"series": "sat-1.position_N"}).validate("r")
    assert any("series" in e for e in errors)


# -- if/while + children ----------------------------------------------------

def test_conditional_requires_condition():
    errors = Command(kind="if", params={}).validate("i")
    assert any("condition" in e for e in errors)


def test_non_conditional_kind_rejects_children():
    child = Command(kind="script_block", params={"code": "pass"})
    errors = Command(kind="maneuver", params={"spacecraft": "s", "delta_v_m_s": [0, 0, 0]},
                      children=[child]).validate("m")
    assert any("does not accept children" in e for e in errors)


def test_if_validates_children_recursively():
    bad_child = Command(kind="maneuver", params={})  # missing everything
    cmd = Command(kind="if", params={"condition": "True"}, children=[bad_child])
    errors = cmd.validate("mission_sequence[0]")
    assert any("mission_sequence[0].children[0]" in e for e in errors)


def test_nested_if_validates_grandchildren():
    grandchild = Command(kind="script_block", params={})  # missing code
    child = Command(kind="while", params={"condition": "True"}, children=[grandchild])
    root = Command(kind="if", params={"condition": "True"}, children=[child])
    errors = root.validate("mission_sequence[0]")
    assert any("children[0].children[0]" in e for e in errors)


def test_script_block_valid():
    assert Command(kind="script_block", params={"code": "x = 1"}).validate("s") == []


def test_script_block_missing_code_is_rejected():
    errors = Command(kind="script_block", params={}).validate("s")
    assert any("code" in e for e in errors)


# -- (de)serialization -------------------------------------------------------

def test_to_dict_via_asdict_and_from_dict_round_trip():
    original = Command(
        kind="if", label="Check altitude", params={"condition": "alt < 500"},
        children=[Command(kind="maneuver", label="Trim burn",
                            params={"spacecraft": "sat-1", "delta_v_m_s": [0.1, 0.0, 0.0], "frame": "vnb"})],
    )
    data = asdict(original)
    rebuilt = Command.from_dict(data)
    assert rebuilt == original


def test_from_dict_defaults_missing_optional_fields():
    rebuilt = Command.from_dict({"kind": "propagate"})
    assert rebuilt.label is None
    assert rebuilt.params == {}
    assert rebuilt.children == []
