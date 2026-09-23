"""Tests for missionstudio.engine.spaceweather -- no Basilisk import, runs
anywhere. The CelesTrak network fetch itself is exercised against whatever
network this test runs on (it will genuinely fail in an offline/blocked
sandbox, which is itself the thing test_resolve_celestrak_unreachable_falls_back_to_synthetic
below checks: the fallback chain has to work when the network call fails,
not just when it's mocked to fail).
"""

from datetime import datetime

import pytest

from missionstudio.engine import spaceweather as sw


def test_generate_synthetic_passes_its_own_validation(tmp_path):
    start, end = datetime(2030, 1, 1), datetime(2030, 1, 10)
    path = sw.generate_synthetic(start, end, tmp_path / "synth.csv")
    result = sw.validate_file(path, start, end)
    assert result.ok, result.message


def test_generate_synthetic_is_deterministic(tmp_path):
    start, end = datetime(2030, 1, 1), datetime(2030, 1, 5)
    path_a = sw.generate_synthetic(start, end, tmp_path / "a.csv", seed=7)
    path_b = sw.generate_synthetic(start, end, tmp_path / "b.csv", seed=7)
    assert path_a.read_text() == path_b.read_text()


def test_validate_file_rejects_missing_file(tmp_path):
    result = sw.validate_file(tmp_path / "nope.csv", datetime(2030, 1, 1), datetime(2030, 1, 2))
    assert not result.ok
    assert "does not exist" in result.message


def test_validate_file_rejects_missing_required_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("DATE,AP1\n2030-01-01,5\n")
    result = sw.validate_file(path, datetime(2030, 1, 1), datetime(2030, 1, 2))
    assert not result.ok
    assert "AP_AVG" in result.message


def test_validate_file_rejects_insufficient_date_range(tmp_path):
    path = tmp_path / "short.csv"
    header = ",".join(sw.REQUIRED_COLUMNS)
    row = "2030-01-01," + ",".join(["5"] * 8) + ",5,100,100"
    path.write_text(header + "\n" + row + "\n")
    result = sw.validate_file(path, datetime(2030, 1, 1), datetime(2030, 1, 10))
    assert not result.ok
    assert not result.covers_range


def test_validate_file_covers_range_ignores_time_of_day(tmp_path):
    """Regression test for an audit finding: covers_range used to compare
    a date-only (midnight) timestamp parsed from the CSV's last row
    against a full end_utc datetime, so a file whose last row IS the
    scenario's own end date was wrongly rejected whenever end_utc carried
    a non-zero time-of-day (daily-resolution data covers its whole day,
    not just its midnight instant). service.py builds end_utc as
    datetime.fromisoformat(scenario.epoch_utc) + a timedelta, and
    Scenario.validate() does not require epoch_utc to be midnight, so this
    is a real, reachable scenario shape.
    """
    path = tmp_path / "covers.csv"
    header = ",".join(sw.REQUIRED_COLUMNS)
    row_tail = "," + ",".join(["5"] * 8) + ",5,100,100"
    path.write_text(header + "\n" + "2030-01-01" + row_tail + "\n" + "2030-01-05" + row_tail + "\n")

    start_utc = datetime(2030, 1, 1, 14, 0, 0)
    end_utc = datetime(2030, 1, 5, 14, 0, 0)  # same calendar date as the file's last row, but later in the day
    result = sw.validate_file(path, start_utc, end_utc)

    assert result.covers_range, result.message


def test_validate_file_detects_unsorted_dates(tmp_path):
    path = tmp_path / "unsorted.csv"
    header = ",".join(sw.REQUIRED_COLUMNS)
    row_tail = "," + ",".join(["5"] * 8) + ",5,100,100"
    path.write_text(header + "\n" + "2030-01-05" + row_tail + "\n" + "2030-01-01" + row_tail + "\n")
    result = sw.validate_file(path, datetime(2030, 1, 1), datetime(2030, 1, 5))
    assert not result.ok
    assert result.unsorted


def test_validate_file_detects_duplicate_dates(tmp_path):
    path = tmp_path / "dupe.csv"
    header = ",".join(sw.REQUIRED_COLUMNS)
    row_tail = "," + ",".join(["5"] * 8) + ",5,100,100"
    path.write_text(header + "\n" + "2030-01-01" + row_tail + "\n" + "2030-01-01" + row_tail + "\n")
    result = sw.validate_file(path, datetime(2030, 1, 1), datetime(2030, 1, 1))
    assert not result.ok
    assert result.duplicate_dates == ["2030-01-01"]


def test_resolve_synthetic_source_returns_flagged_synthetic(tmp_path):
    resolved = sw.resolve("synthetic", datetime(2030, 1, 1), datetime(2030, 1, 5), cache_dir=tmp_path)
    assert resolved.is_synthetic
    assert any("SYNTHETIC" in w for w in resolved.warnings)


def test_resolve_local_file_source_uses_exact_file(tmp_path):
    start, end = datetime(2030, 1, 1), datetime(2030, 1, 5)
    local_path = sw.generate_synthetic(start, end, tmp_path / "mine.csv")
    resolved = sw.resolve("local_file", start, end, local_file_path=str(local_path))
    assert resolved.path == local_path
    assert not resolved.is_synthetic


def test_resolve_local_file_source_raises_if_missing():
    with pytest.raises(sw.SpaceWeatherError, match="does not exist"):
        sw.resolve("local_file", datetime(2030, 1, 1), datetime(2030, 1, 5), local_file_path="/nonexistent.csv")


def test_resolve_local_file_source_raises_without_path():
    with pytest.raises(sw.SpaceWeatherError, match="local_file_path was not set"):
        sw.resolve("local_file", datetime(2030, 1, 1), datetime(2030, 1, 5))


def test_resolve_unknown_source_raises():
    with pytest.raises(sw.SpaceWeatherError, match="unknown space_weather.source"):
        sw.resolve("magic", datetime(2030, 1, 1), datetime(2030, 1, 5))


def test_resolve_celestrak_falls_back_when_unreachable_or_insufficient(tmp_path):
    """This is the fallback chain the user explicitly asked for: fetch from
    CelesTrak; if that isn't possible, fall back (here: no local_file_path
    was given, so all the way to synthetic), never raising and never
    silently returning an unusable/empty result. Genuinely exercises the
    real network call (no mocking) -- in this project's own development
    sandbox that call is blocked by network policy, which is exactly the
    "not possible" case this test proves is handled gracefully; on a
    machine where CelesTrak IS reachable, this either succeeds via the
    real fetch (is_synthetic False) or still falls back correctly if the
    fetched data doesn't cover the (deliberately far-future) requested
    range -- either outcome is a pass.
    """
    start, end = datetime(2030, 1, 1), datetime(2030, 1, 5)
    resolved = sw.resolve("celestrak", start, end, cache_dir=tmp_path)
    assert resolved.path.exists()
    assert resolved.warnings, "expected at least one warning explaining what happened"
    # Whatever happened, the file it points to must itself be valid.
    result = sw.validate_file(resolved.path, start, end)
    assert result.ok, f"resolve() returned an unusable file: {result.message}"
