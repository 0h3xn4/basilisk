"""Tests for missionstudio.engine.spacecraft_templates -- no Basilisk
import, runs anywhere.
"""

from missionstudio.engine.spacecraft_templates import SPACECRAFT_TEMPLATES


def test_every_template_builds_a_valid_spacecraft_config():
    for template in SPACECRAFT_TEMPLATES:
        config = template.build()
        config.validate()  # raises ScenarioValidationError with a specific message on anything bad


def test_every_template_has_a_name_and_description():
    for template in SPACECRAFT_TEMPLATES:
        assert template.name.strip()
        assert template.description.strip()


def test_template_names_are_unique():
    names = [t.name for t in SPACECRAFT_TEMPLATES]
    assert len(names) == len(set(names))


def test_build_returns_a_fresh_instance_each_call():
    """Regression-guard: two calls to the same template's build() must not
    share mutable state (e.g. the same sensors/actuators list object) --
    mutating one build()'s result must not affect the next one's.
    """
    for template in SPACECRAFT_TEMPLATES:
        first = template.build()
        second = template.build()
        assert first is not second
        first.name = "mutated"
        assert second.name != "mutated"
        if first.sensors:
            first.sensors.append("not a real sensor")
            assert len(second.sensors) != len(first.sensors)


def test_passive_cubesat_has_no_adcs_but_enables_drag_and_srp():
    template = next(t for t in SPACECRAFT_TEMPLATES if "passive" in t.name.lower())
    config = template.build()
    assert config.sensors == []
    assert config.actuators == []
    assert config.fsw_mode is None
    assert config.enable_drag is True
    assert config.enable_srp is True


def test_stabilized_cubesat_has_reaction_wheels_and_fsw_mode():
    template = next(t for t in SPACECRAFT_TEMPLATES if "stabilized" in t.name.lower() and "3u" in t.name.lower())
    config = template.build()
    assert len(config.actuators) == 3
    assert all(a.kind == "reaction_wheel" for a in config.actuators)
    assert config.fsw_mode is not None
    assert config.power is not None
