"""Tests for missionstudio.engine.results -- no Basilisk import, runs anywhere."""

import csv

import numpy as np
import pytest

from missionstudio.engine.results import CommandSummary, ReportEntry, ResultSet, ResultsError, TimeSeries


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


def test_command_summary_export_csv_long_format(tmp_path):
    summary = CommandSummary(reports=[
        ReportEntry(label="checkpoint", t_s=100.0, values={
            "sat-1.position_N": np.array([1.0, 2.0, 3.0]),
            "sat-1.mass_kg": np.array([500.0]),
        }),
        ReportEntry(label=None, t_s=200.0, values={"sat-1.position_N": np.array([4.0, 5.0, 6.0])}),
    ], commands_executed=5)

    path = summary.export_csv(tmp_path / "command_summary.csv")
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == ["report_index", "t_s", "label", "series", "component", "value"]
    # 3 components (position) + 1 (mass) for report 0, 3 components for report 1.
    assert len(rows) == 1 + 4 + 3

    position_rows = [r for r in rows[1:] if r[0] == "0" and r[3] == "sat-1.position_N"]
    assert len(position_rows) == 3
    assert [r[4] for r in position_rows] == ["0", "1", "2"]
    assert [float(r[5]) for r in position_rows] == pytest.approx([1.0, 2.0, 3.0])
    assert position_rows[0][2] == "checkpoint"

    unlabeled_rows = [r for r in rows[1:] if r[0] == "1"]
    assert all(r[2] == "" for r in unlabeled_rows)


def test_command_summary_export_csv_creates_parent_dir(tmp_path):
    summary = CommandSummary(reports=[
        ReportEntry(label="x", t_s=0.0, values={"s": np.array([1.0])}),
    ])
    path = summary.export_csv(tmp_path / "nested" / "dir" / "out.csv")
    assert path.exists()


def test_command_summary_export_csv_with_no_reports_writes_header_only(tmp_path):
    path = CommandSummary().export_csv(tmp_path / "out.csv")
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [["report_index", "t_s", "label", "series", "component", "value"]]
