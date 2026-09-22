"""Tests for missionstudio.engine.results -- no Basilisk import, runs anywhere."""

import csv

import numpy as np
import pytest

from missionstudio.engine.results import ResultSet, ResultsError, TimeSeries


def _sample_series(name="s", n=10):
    t = np.linspace(0.0, 90.0, n)
    data = np.column_stack([np.sin(t), np.cos(t), t * 0.01])
    return TimeSeries(name=name, time_s=t, columns=("x", "y", "z"), data=data, units="m")


def test_time_series_shape_mismatch_rejected():
    t = np.linspace(0, 10, 5)
    data = np.zeros((4, 3))  # one row short
    with pytest.raises(ResultsError, match="must match"):
        TimeSeries(name="bad", time_s=t, columns=("x", "y", "z"), data=data)


def test_time_series_column_count_mismatch_rejected():
    t = np.linspace(0, 10, 5)
    data = np.zeros((5, 3))
    with pytest.raises(ResultsError, match="columns"):
        TimeSeries(name="bad", time_s=t, columns=("x", "y"), data=data)  # 2 names for 3 columns


def test_time_series_accepts_1d_data_as_single_column():
    t = np.linspace(0, 10, 5)
    ts = TimeSeries(name="scalar", time_s=t, columns=("value",), data=np.arange(5.0))
    assert ts.data.shape == (5, 1)


def test_to_csv_round_trips_values(tmp_path):
    ts = _sample_series()
    path = ts.to_csv(tmp_path / "out.csv")
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["time_s", "x_m", "y_m", "z_m"]
    assert len(rows) == 1 + len(ts.time_s)
    # spot-check the first data row round-trips numerically
    assert float(rows[1][0]) == pytest.approx(ts.time_s[0])
    assert float(rows[1][1]) == pytest.approx(ts.data[0, 0])


def test_result_set_add_and_export(tmp_path):
    rs = ResultSet(scenario_name="test")
    rs.add(_sample_series("sat-1.position_N"))
    rs.add(_sample_series("sat-1.velocity_N"))
    paths = rs.export_csv(tmp_path / "out")
    assert set(paths) == {"sat-1.position_N", "sat-1.velocity_N"}
    for p in paths.values():
        assert p.exists()


def test_result_set_rejects_duplicate_series_name():
    rs = ResultSet(scenario_name="test")
    rs.add(_sample_series("dup"))
    with pytest.raises(ResultsError, match="already added"):
        rs.add(_sample_series("dup"))
