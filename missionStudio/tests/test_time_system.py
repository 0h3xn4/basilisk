"""Tests for missionstudio.engine.time_system.utc_iso_to_spice_string().

engine.time_system imports Basilisk.utilities.supportDataTools.dataFetcher
at module level, so even this pure-Python string-formatting logic needs a
Basilisk build to import in this development sandbox (marked
requires_basilisk; see tests/conftest.py for the auto-skip behavior).
"""

import pytest

pytestmark = pytest.mark.requires_basilisk


def test_utc_iso_to_spice_string_whole_second():
    from missionstudio.engine.time_system import utc_iso_to_spice_string

    assert utc_iso_to_spice_string("2030-01-01T00:00:00") == "2030 JAN 01 00:00:00.000 (UTC)"


def test_utc_iso_to_spice_string_preserves_sub_second_precision():
    """Regression test for an audit finding: the function used to hardcode
    a literal ".000" in its strftime format string, silently discarding
    any sub-second precision in epoch_utc instead of deriving it from the
    actual value -- schema.scenario.Scenario.validate() only requires
    epoch_utc to parse as ISO 8601, not to be a whole second, so this is a
    real, reachable input shape.
    """
    from missionstudio.engine.time_system import utc_iso_to_spice_string

    assert utc_iso_to_spice_string("2030-01-01T00:00:00.750000") == "2030 JAN 01 00:00:00.750 (UTC)"
    assert utc_iso_to_spice_string("2030-01-01T00:00:00.001000") == "2030 JAN 01 00:00:00.001 (UTC)"
