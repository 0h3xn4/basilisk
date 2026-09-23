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
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..engine.results import ResultSet


class ResultsWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._result: ResultSet | None = None

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Series:"))
        self.series_combo = QComboBox()
        self.series_combo.currentIndexChanged.connect(self._redraw)
        top_row.addWidget(self.series_combo, stretch=1)
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

    def set_result(self, result: ResultSet | None) -> None:
        self._result = result
        self.series_combo.blockSignals(True)
        self.series_combo.clear()
        if result is not None:
            for name in result.series:
                self.series_combo.addItem(name)
        self.series_combo.blockSignals(False)
        self.export_button.setEnabled(result is not None and bool(result.series))
        self._redraw()

    def set_live_result(self, result: ResultSet) -> None:
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
        if is_first_update:
            self.series_combo.blockSignals(True)
            self.series_combo.clear()
            for name in result.series:
                self.series_combo.addItem(name)
            self.series_combo.blockSignals(False)
            self.export_button.setEnabled(bool(result.series))
        self._redraw()

    def _redraw(self) -> None:
        self.axes.clear()
        if self._result is not None and self.series_combo.count() > 0:
            name = self.series_combo.currentText()
            series = self._result.series.get(name)
            if series is not None:
                t_hours = series.time_s / 3600.0
                for i, column in enumerate(series.columns):
                    self.axes.plot(t_hours, series.data[:, i], label=column)
                unit_suffix = f" [{series.units}]" if series.units else ""
                self.axes.set_xlabel("elapsed time [hr]")
                self.axes.set_ylabel(f"{name}{unit_suffix}")
                self.axes.legend()
                self.axes.grid(True, linewidth=0.3)
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
