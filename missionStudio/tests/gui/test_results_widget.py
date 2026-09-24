"""Tests for gui.results_widget.ResultsWidget -- uses synthetic
ResultSet data, no Basilisk needed.
"""

from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.requires_gui


def _sample_result_set(n=50):
    from missionstudio.engine.results import ResultSet, TimeSeries

    t = np.linspace(0, 3600 * 3, n)
    pos = np.column_stack([np.sin(t / 500), np.cos(t / 500), t * 0.001]) * 7.0e6
    vel = np.column_stack([np.cos(t / 500), -np.sin(t / 500), np.zeros_like(t)])

    rs = ResultSet(scenario_name="demo")
    rs.add(TimeSeries("sat-1.position_N", t, ("x", "y", "z"), pos, units="m"))
    rs.add(TimeSeries("sat-1.velocity_N", t, ("x", "y", "z"), vel, units="m/s"))
    return rs


@pytest.fixture
def widget(qtbot):
    from missionstudio.gui.results_widget import ResultsWidget

    w = ResultsWidget()
    qtbot.addWidget(w)
    return w


def test_set_result_populates_series_combo_and_plots(widget):
    widget.set_result(_sample_result_set())
    assert widget.series_combo.count() == 2
    assert widget.export_button.isEnabled()
    assert len(widget.axes.get_lines()) == 3  # x, y, z


def test_switching_series_redraws(widget):
    widget.set_result(_sample_result_set())
    widget.series_combo.setCurrentIndex(1)
    assert len(widget.axes.get_lines()) == 3


def test_set_result_none_clears_everything(widget):
    widget.set_result(_sample_result_set())
    widget.set_result(None)
    assert widget.series_combo.count() == 0
    assert not widget.export_button.isEnabled()
    assert len(widget.axes.get_lines()) == 0


def test_export_writes_csv_files(widget, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    widget.set_result(_sample_result_set())
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    info_calls = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: info_calls.append(a)))

    widget._on_export()

    written = sorted(p.name for p in Path(tmp_path).glob("*.csv"))
    assert written == ["sat-1.position_N.csv", "sat-1.velocity_N.csv"]
    assert len(info_calls) == 1


def test_export_with_no_result_is_a_no_op(widget, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    calls = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: calls.append(1) or ""))
    widget._on_export()  # self._result is None
    assert calls == []


def test_set_live_result_populates_combo_on_first_update(widget):
    widget.set_live_result(_sample_result_set(n=5))
    assert widget.series_combo.count() == 2
    assert widget.export_button.isEnabled()
    assert len(widget.axes.get_lines()) == 3  # x, y, z


def test_set_live_result_does_not_reset_users_series_selection(widget):
    """Regression guard: a live run's series names are fixed from its
    first chunk (see set_live_result's docstring) -- later chunks with
    MORE data but the SAME series names must not rebuild series_combo,
    which would silently snap the user's current selection back to index
    0 every time a new chunk arrives while they're watching a different
    series.
    """
    widget.set_live_result(_sample_result_set(n=5))
    widget.series_combo.setCurrentIndex(1)  # "sat-1.velocity_N"

    widget.set_live_result(_sample_result_set(n=25))  # later chunk, more samples, same series names

    assert widget.series_combo.currentIndex() == 1
    assert widget.series_combo.count() == 2


def test_set_live_result_grows_the_plotted_data(widget):
    widget.set_live_result(_sample_result_set(n=5))
    first_line_length = len(widget.axes.get_lines()[0].get_xdata())

    widget.set_live_result(_sample_result_set(n=25))

    assert len(widget.axes.get_lines()[0].get_xdata()) > first_line_length


def test_position_series_plots_in_km_not_m(widget):
    rs = _sample_result_set()
    raw_x_m = rs.series["sat-1.position_N"].data[:, 0]

    widget.set_result(rs)

    plotted_x = widget.axes.get_lines()[0].get_ydata()
    np.testing.assert_allclose(plotted_x, raw_x_m / 1000.0)
    assert "[km]" in widget.axes.get_ylabel()


def test_velocity_series_plots_in_km_s_not_m_s(widget):
    rs = _sample_result_set()
    raw_vx_m_s = rs.series["sat-1.velocity_N"].data[:, 0]

    widget.set_result(rs)
    widget.series_combo.setCurrentIndex(1)  # "sat-1.velocity_N"

    plotted_x = widget.axes.get_lines()[0].get_ydata()
    np.testing.assert_allclose(plotted_x, raw_vx_m_s / 1000.0)
    assert "[km/s]" in widget.axes.get_ylabel()


def test_dimensionless_series_is_not_unit_converted(widget):
    from missionstudio.engine.results import ResultSet, TimeSeries

    rs = ResultSet(scenario_name="demo")
    rs.add(TimeSeries("sat-1.eccentricity", np.linspace(0, 100, 5), ("e",), np.full((5, 1), 0.01), units="-"))
    widget.set_result(rs)

    plotted = widget.axes.get_lines()[0].get_ydata()
    np.testing.assert_allclose(plotted, 0.01)  # unchanged -- "-" isn't in _DISPLAY_UNIT_CONVERSIONS
    assert widget.axes.get_ylabel() == "sat-1.eccentricity [-]"


def test_default_x_axis_is_elapsed_time_in_hours(widget):
    rs = _sample_result_set()
    widget.set_result(rs)

    plotted_x = widget.axes.get_lines()[0].get_xdata()
    np.testing.assert_allclose(plotted_x, rs.series["sat-1.position_N"].time_s / 3600.0)
    assert "elapsed time" in widget.axes.get_xlabel()


def test_epoch_x_axis_converts_time_s_to_datetimes(widget):
    from datetime import datetime, timedelta

    rs = _sample_result_set(n=5)
    widget.set_result(rs, epoch_utc="2030-01-01T00:00:00")
    widget.x_axis_combo.setCurrentIndex(widget.x_axis_combo.findData("epoch"))

    plotted_x = widget.axes.get_lines()[0].get_xdata()
    base = datetime.fromisoformat("2030-01-01T00:00:00")
    expected = [base + timedelta(seconds=float(t)) for t in rs.series["sat-1.position_N"].time_s]
    assert list(plotted_x) == expected
    assert widget.axes.get_xlabel() == "epoch (UTC)"


def test_epoch_x_axis_falls_back_to_elapsed_time_without_a_known_epoch(widget):
    rs = _sample_result_set()
    widget.set_result(rs)  # no epoch_utc given
    widget.x_axis_combo.setCurrentIndex(widget.x_axis_combo.findData("epoch"))

    assert "elapsed time" in widget.axes.get_xlabel()


def test_epoch_x_axis_falls_back_to_elapsed_time_on_unparseable_epoch(widget):
    rs = _sample_result_set()
    widget.set_result(rs, epoch_utc="not a real epoch string")
    widget.x_axis_combo.setCurrentIndex(widget.x_axis_combo.findData("epoch"))

    assert "elapsed time" in widget.axes.get_xlabel()


def test_switching_x_axis_back_to_elapsed_time_restores_it(widget):
    rs = _sample_result_set()
    widget.set_result(rs, epoch_utc="2030-01-01T00:00:00")
    widget.x_axis_combo.setCurrentIndex(widget.x_axis_combo.findData("epoch"))
    widget.x_axis_combo.setCurrentIndex(widget.x_axis_combo.findData("elapsed"))

    assert "elapsed time" in widget.axes.get_xlabel()


def test_live_result_carries_epoch_through_to_the_plot(widget):
    rs = _sample_result_set(n=5)
    widget.set_live_result(rs, epoch_utc="2030-06-15T00:00:00")
    widget.x_axis_combo.setCurrentIndex(widget.x_axis_combo.findData("epoch"))

    assert widget.axes.get_xlabel() == "epoch (UTC)"


def test_set_live_result_rebuilds_combo_if_series_names_change(widget):
    from missionstudio.engine.results import ResultSet, TimeSeries

    widget.set_live_result(_sample_result_set(n=5))
    widget.series_combo.setCurrentIndex(1)

    other = ResultSet(scenario_name="demo")
    other.add(TimeSeries("sat-2.position_N", np.linspace(0, 10, 5), ("x", "y", "z"),
                          np.zeros((5, 3)), units="m"))
    widget.set_live_result(other)

    assert widget.series_combo.count() == 1
    assert widget.series_combo.currentText() == "sat-2.position_N"
