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

"""MainWindow: the top-level PySide6 window. Wires
:class:`ScenarioEditorWidget`, :class:`ResultsWidget`, and
:class:`KernelStatusWidget` together via File/Run menu actions.

No scenario or simulation logic lives here -- everything goes through
``ScenarioEditorWidget.to_scenario()``/``from_scenario()``,
``schema.load_scenario()``/``Scenario.save()``, and :class:`RunWorker`,
which is the "decoupled from the sim engine via a clean API/service
layer" requirement in practice: this class could be deleted and replaced
with a different UI toolkit entirely without touching
``schema``/``engine``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QSplitter, QTabWidget

from ..schema.scenario import Scenario, ScenarioValidationError, load_scenario
from .kernel_status_widget import KernelStatusWidget
from .results_widget import ResultsWidget
from .run_worker import RunWorker
from .scenario_editor import ScenarioEditorWidget

_FILE_FILTER = "missionStudio scenario (*.json)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1200, 800)

        self._current_path: Path | None = None
        self._dirty = False
        self._run_worker: RunWorker | None = None

        self.scenario_editor = ScenarioEditorWidget()
        self.scenario_editor.reset_to_default()
        self.scenario_editor.changed.connect(self._mark_dirty)

        self.results_widget = ResultsWidget()
        self.kernel_status_widget = KernelStatusWidget()

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.results_widget, "Results")
        self.right_tabs.addTab(self.kernel_status_widget, "Kernel Status")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.scenario_editor)
        splitter.addWidget(self.right_tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._build_menu()
        self.statusBar().showMessage("Ready.")
        self._update_window_title()

    # -- menu ---------------------------------------------------------------
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New Scenario", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.on_new)
        file_menu.addAction(new_action)
        self.new_action = new_action

        open_action = QAction("&Open...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.on_open)
        file_menu.addAction(open_action)
        self.open_action = open_action

        save_action = QAction("&Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.on_save)
        file_menu.addAction(save_action)
        self.save_action = save_action

        save_as_action = QAction("Save &As...", self)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_action.triggered.connect(self.on_save_as)
        file_menu.addAction(save_as_action)
        self.save_as_action = save_as_action

        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        run_menu = self.menuBar().addMenu("&Run")
        run_action = QAction("&Run Simulation", self)
        run_action.setShortcut("Ctrl+R")
        run_action.triggered.connect(self.on_run)
        run_menu.addAction(run_action)
        self.run_action = run_action

        check_kernels_action = QAction("&Check Kernels", self)
        check_kernels_action.triggered.connect(self.kernel_status_widget.refresh)
        run_menu.addAction(check_kernels_action)
        self.check_kernels_action = check_kernels_action

    def _update_window_title(self) -> None:
        name = self._current_path.name if self._current_path else "untitled"
        star = "*" if self._dirty else ""
        self.setWindowTitle(f"missionStudio -- {name}{star}")

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_window_title()

    def _mark_clean(self) -> None:
        self._dirty = False
        self._update_window_title()

    def _confirm_discard_unsaved(self) -> bool:
        """Returns True if it's OK to proceed (no unsaved changes, or the
        user explicitly said to discard them) -- never silently discards.
        """
        if not self._dirty:
            return True
        response = QMessageBox.question(
            self, "Unsaved changes",
            "This scenario has unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return response == QMessageBox.StandardButton.Discard

    # -- File actions ---------------------------------------------------------
    def on_new(self) -> None:
        if not self._confirm_discard_unsaved():
            return
        self.scenario_editor.reset_to_default()
        self._current_path = None
        self.results_widget.set_result(None)
        self._mark_clean()
        self.statusBar().showMessage("New scenario.")

    def on_open(self) -> None:
        if not self._confirm_discard_unsaved():
            return
        path_str, _selected_filter = QFileDialog.getOpenFileName(self, "Open scenario", "", _FILE_FILTER)
        if not path_str:
            return
        self.open_path(Path(path_str))

    def open_path(self, path: Path) -> None:
        try:
            scenario = load_scenario(path)
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Could not open scenario", str(exc))
            return
        self.scenario_editor.from_scenario(scenario)
        self._current_path = path
        self.results_widget.set_result(None)
        self._mark_clean()
        self.statusBar().showMessage(f"Opened {path}")

    def on_save(self) -> None:
        if self._current_path is None:
            self.on_save_as()
            return
        self._save_to(self._current_path)

    def on_save_as(self) -> None:
        path_str, _selected_filter = QFileDialog.getSaveFileName(self, "Save scenario as", "", _FILE_FILTER)
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix != ".json":
            path = path.with_suffix(".json")
        self._save_to(path)

    def _save_to(self, path: Path) -> None:
        try:
            scenario: Scenario = self.scenario_editor.to_scenario()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Cannot save invalid scenario", str(exc))
            return
        scenario.save(path)
        self._current_path = path
        self._mark_clean()
        self.statusBar().showMessage(f"Saved {path}")

    # -- Run --------------------------------------------------------------
    def on_run(self) -> None:
        try:
            scenario = self.scenario_editor.to_scenario()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Cannot run invalid scenario", str(exc))
            return

        self.run_action.setEnabled(False)
        self.statusBar().showMessage(f"Running {scenario.name}...")
        self._run_worker = RunWorker(scenario)
        self._run_worker.finished_ok.connect(self._on_run_finished)
        self._run_worker.failed.connect(self._on_run_failed)
        self._run_worker.start()

    def _on_run_finished(self, result) -> None:
        self.run_action.setEnabled(True)
        self.results_widget.set_result(result)
        self.right_tabs.setCurrentWidget(self.results_widget)
        self.statusBar().showMessage(f"Run complete: {len(result.series)} result series.")

    def _on_run_failed(self, message: str) -> None:
        self.run_action.setEnabled(True)
        self.statusBar().showMessage("Run failed.")
        QMessageBox.critical(self, "Simulation failed", message)

    # -- window lifecycle ---------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard_unsaved():
            event.accept()
        else:
            event.ignore()
