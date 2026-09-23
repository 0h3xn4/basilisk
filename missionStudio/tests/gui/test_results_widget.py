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
