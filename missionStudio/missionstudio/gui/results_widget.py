#
#  ISC License
#
#  Copyright (c) 2026, Autonomous Vehicle Systems Lab, University of Colorado at Boulder
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
#  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
#  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
#  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
#  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
#  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
#  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#

"""ResultsWidget: plots a :class:`engine.results.ResultSet` (matplotlib,
embedded via ``FigureCanvasQTAgg`` -- matplotlib is already a Basilisk
dependency, see ``../../requirements.txt``, so this adds no new heavy
dependency beyond PySide6 itself) and exports it to CSV. Takes a plain
``ResultSet`` -- no Basilisk import in this module, so it's testable here
with synthetic data exactly like ``engine/results.py`` itself is.

Two independent display choices, both user feedback, both PLOT-only
(``export_csv()``/``_on_export()`` below keep writing exactly what
``TimeSeries`` holds -- raw SI units, elapsed seconds -- since a CSV a
user hands to another tool should stay unambiguous, not follow a
plot-only display preference):

* Length/length-rate series (``units in {"m", "m/s"}`` -- position,
  velocity, altitude, slant range, delta-V, ...) are shown in km/km-s,
  not raw meters -- meter-scale numbers on an orbit-scale plot were the
  complaint (e.g. a LEO position plot's y-axis in the millions).
  ``_DISPLAY_UNIT_CONVERSIONS`` is deliberately narrow: everything else
  (accelerometer m/s^2, torque N*m, angles rad/deg, ...) is left as
  ``TimeSeries`` already has it, since km-scale units would be actively
  worse there, not better.
* The x-axis defaults to elapsed time (hours since the scenario epoch,
  as before) but can be switched to absolute epoch (UTC datetimes,
  ``series.time_s`` added to the epoch :meth:`set_result`/
  :meth:`set_live_result` were given) via ``x_axis_combo``. ``epoch_utc``
  is optional and defaults to ``None`` (falls back to elapsed time even
  if "Epoch (UTC)" is selected) so every existing caller/test that only
  ever passed a bare ``ResultSet`` keeps working unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..engine.results import ResultSet, TimeSeries

# unit -> (display unit, divisor) -- see module docstring for why this is
# narrowly scoped to length/length-rate units only.
_DISPLAY_UNIT_CONVERSIONS = {
    "m": ("km", 1000.0),
    "m/s": ("km/s", 1000.0),
}


def _display_units(series: TimeSeries) -> Tuple["object", str]:
    """Returns ``(data, unit_label)`` for PLOTTING -- ``series.data``
    itself/``series.units`` unchanged unless a km-scale conversion
    applies (see ``_DISPLAY_UNIT_CONVERSIONS``).
    """
    conversion = _DISPLAY_UNIT_CONVERSIONS.get(series.units)
    if conversion is None:
        return series.data, series.units
    display_unit, divisor = conversion
    return series.data / divisor, display_unit


class ResultsWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._result: ResultSet | None = None
        self._epoch_utc: Optional[str] = None

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Series:"))
        self.series_combo = QComboBox()
        self.series_combo.currentIndexChanged.connect(self._redraw)
        top_row.addWidget(self.series_combo, stretch=1)
        top_row.addWidget(QLabel("X-axis:"))
        self.x_axis_combo = QComboBox()
        self.x_axis_combo.addItem("Elapsed time", "elapsed")
        self.x_axis_combo.addItem("Epoch (UTC)", "epoch")
        self.x_axis_combo.setToolTip(
            "\"Epoch (UTC)\" needs the scenario's epoch, which is only known once a run has actually "
            "produced this result -- falls back to elapsed time if it isn't available."
        )
        self.x_axis_combo.currentIndexChanged.connect(self._redraw)
        top_row.addWidget(self.x_axis_combo)
        self.export_button = QPushButton("Export all series to CSV...")
        self.export_button.clicked.connect(self._on_export)
        self.export_button.setEnabled(False)
        top_row.addWidget(self.export_button)
        layout.addLayout(top_row)

        self.figure = Figure(figsize=(6, 4))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111)
        layout.addWidget(self.canvas)
        self._redraw()  # shows the empty-state message immediately, not just after the first set_result() call

    def set_result(self, result: ResultSet | None, epoch_utc: Optional[str] = None) -> None:
        self._result = result
        self._epoch_utc = epoch_utc
        self.series_combo.blockSignals(True)
        self.series_combo.clear()
        if result is not None:
            for name in result.series:
                self.series_combo.addItem(name)
        self.series_combo.blockSignals(False)
        self.export_button.setEnabled(result is not None and bool(result.series))
        self._redraw()

    def set_live_result(self, result: ResultSet, epoch_utc: Optional[str] = None) -> None:
        """Updates the plot with one chunk's worth of a still-running
        simulation (see ``gui.run_worker.RunWorker``'s ``progress`` signal /
        :meth:`engine.service.SimulationService.run_live`). Unlike
        :meth:`set_result`, this never rebuilds ``series_combo`` once it
        already holds this result's series names -- the set of series a
        live run reports is fixed from its very first callback (which
        series exist is decided by the scenario, not by how much data has
        been recorded), so rebuilding it every chunk would keep resetting
        whatever series the user is currently looking at, fighting them
        while they watch it run.
        """
        is_first_update = self._result is None or set(self._result.series) != set(result.series)
        self._result = result
        self._epoch_utc = epoch_utc  # same every chunk of one run, but cheap enough not to bother guarding
        if is_first_update:
            self.series_combo.blockSignals(True)
            self.series_combo.clear()
            for name in result.series:
                self.series_combo.addItem(name)
            self.series_combo.blockSignals(False)
            self.export_button.setEnabled(bool(result.series))
        self._redraw()

    def _x_axis_values(self, time_s):
        """Returns ``(x_values, axis_label)``. "Epoch (UTC)" needs both a
        real epoch (``set_result``/``set_live_result`` were given one --
        absent for e.g. a bare synthetic ``ResultSet`` in a test, or
        before any run has actually happened yet) and for it to parse;
        either problem falls back to elapsed time rather than raising,
        matching this widget's existing "never crash the GUI over
        display preferences" behavior (see e.g. ``_redraw``'s own
        empty-state handling).
        """
        if self.x_axis_combo.currentData() == "epoch" and self._epoch_utc:
            try:
                base = datetime.fromisoformat(self._epoch_utc)
            except ValueError:
                pass
            else:
                return [base + timedelta(seconds=float(t)) for t in time_s], "epoch (UTC)"
        return time_s / 3600.0, "elapsed time [hr]"

    def _redraw(self) -> None:
        self.axes.clear()
        if self._result is not None and self.series_combo.count() > 0:
            name = self.series_combo.currentText()
            series = self._result.series.get(name)
            if series is not None:
                display_data, display_unit = _display_units(series)
                x_values, x_label = self._x_axis_values(series.time_s)
                for i, column in enumerate(series.columns):
                    self.axes.plot(x_values, display_data[:, i], label=column)
                unit_suffix = f" [{display_unit}]" if display_unit else ""
                self.axes.set_xlabel(x_label)
                self.axes.set_ylabel(f"{name}{unit_suffix}")
                self.axes.legend()
                self.axes.grid(True, linewidth=0.3)
                if x_label == "epoch (UTC)":
                    self.figure.autofmt_xdate()  # slants/spaces datetime tick labels so they don't overlap
        else:
            # Previously just a blank white canvas with no explanation --
            # confusing on first launch, before any run has happened (part
            # of the "looks unfinished" feedback this addresses).
            self.axes.set_axis_off()
            self.axes.text(
                0.5, 0.5, "Run a simulation to see results here",
                ha="center", va="center", transform=self.axes.transAxes,
                fontsize=11, color="#8A93A3",
            )
        self.canvas.draw_idle()

    def _on_export(self) -> None:
        if self._result is None:
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Export results to CSV")
        if not out_dir:
            return
        try:
            paths = self._result.export_csv(Path(out_dir))
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Export complete", f"Wrote {len(paths)} CSV file(s) to {out_dir}")
