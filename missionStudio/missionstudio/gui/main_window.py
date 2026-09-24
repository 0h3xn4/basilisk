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

from PySide6.QtCore import QElapsedTimer, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolBar,
)

from ..schema.scenario import Scenario, ScenarioValidationError, load_scenario
from .kernel_status_widget import KernelStatusWidget
from .mission_output_widget import MissionOutputWidget
from .results_widget import ResultsWidget
from .run_worker import MonteCarloWorker, RunWorker
from .scenario_editor import ScenarioEditorWidget
from .vizard_dialog import VizardDialog

_FILE_FILTER = "missionStudio scenario (*.json)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1200, 800)

        self._current_path: Path | None = None
        self._dirty = False
        self._run_worker: RunWorker | None = None
        self._mc_worker: MonteCarloWorker | None = None
        self._vizard_request = None  # engine.vizard.VizardRequest, or None -- set via the Run menu's "Vizard..." action

        self.scenario_editor = ScenarioEditorWidget()
        self.scenario_editor.reset_to_default()
        self.scenario_editor.changed.connect(self._mark_dirty)

        self.results_widget = ResultsWidget()
        self.mission_output_widget = MissionOutputWidget()
        self.kernel_status_widget = KernelStatusWidget()

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.results_widget, "Results")
        self.right_tabs.addTab(self.mission_output_widget, "Mission Output")
        self.right_tabs.addTab(self.kernel_status_widget, "Kernel Status")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.scenario_editor)
        splitter.addWidget(self.right_tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._build_menu()

        # Run-in-progress feedback (status bar): an indeterminate busy bar
        # plus an elapsed-time label, shown for the duration of ANY
        # run/Monte Carlo worker. Indeterminate rather than a real percentage
        # because neither SimBaseClass.ExecuteSimulation() nor
        # MonteCarlo.Controller.executeSimulations() exposes a step/run
        # progress callback to drive one -- this at least answers "is it
        # running, or did it silently die" (users previously had only a
        # static status-bar string and no other feedback while a run was in
        # flight -- see the on_run/on_run_monte_carlo history).
        self._busy_elapsed = QElapsedTimer()
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(200)
        self._busy_timer.timeout.connect(self._update_busy_elapsed)
        self._busy_label = QLabel()
        self._busy_label.setVisible(False)
        self._busy_progress = QProgressBar()
        self._busy_progress.setRange(0, 0)  # indeterminate ("marching ants") -- see comment above
        self._busy_progress.setMaximumWidth(120)
        self._busy_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._busy_label)
        self.statusBar().addPermanentWidget(self._busy_progress)

        self.statusBar().showMessage("Ready.")
        self._update_window_title()

    # -- menu ---------------------------------------------------------------
    def _build_menu(self) -> None:
        style = self.style()
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileIcon), "&New Scenario", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.setToolTip("New Scenario (Ctrl+N)")
        new_action.triggered.connect(self.on_new)
        file_menu.addAction(new_action)
        self.new_action = new_action

        open_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), "&Open...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.setToolTip("Open a scenario file (Ctrl+O)")
        open_action.triggered.connect(self.on_open)
        file_menu.addAction(open_action)
        self.open_action = open_action

        save_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "&Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.setToolTip("Save (Ctrl+S)")
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
        run_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "&Run Simulation", self)
        run_action.setShortcut("Ctrl+R")
        run_action.setToolTip("Run Simulation (Ctrl+R)")
        run_action.triggered.connect(self.on_run)
        run_menu.addAction(run_action)
        self.run_action = run_action

        live_plot_action = QAction("&Live Plot", self)
        live_plot_action.setCheckable(True)
        live_plot_action.setChecked(True)
        live_plot_action.setToolTip(
            "Update the Results plot as the simulation runs, instead of only once it finishes"
        )
        run_menu.addAction(live_plot_action)
        self.live_plot_action = live_plot_action

        check_kernels_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
                                        "&Check Kernels", self)
        check_kernels_action.setToolTip("Check/fetch SPICE kernels")
        check_kernels_action.triggered.connect(self.kernel_status_widget.refresh)
        run_menu.addAction(check_kernels_action)
        self.check_kernels_action = check_kernels_action

        vizard_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DesktopIcon), "&Vizard...", self)
        vizard_action.setToolTip("Configure Vizard visualization for the next run")
        vizard_action.triggered.connect(self.on_configure_vizard)
        run_menu.addAction(vizard_action)
        self.vizard_action = vizard_action

        monte_carlo_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekForward),
                                      "Run &Monte Carlo...", self)
        monte_carlo_action.setToolTip("Run a Monte Carlo batch")
        monte_carlo_action.triggered.connect(self.on_run_monte_carlo)
        run_menu.addAction(monte_carlo_action)
        self.monte_carlo_action = monte_carlo_action

        self._build_toolbar()

    def _build_toolbar(self) -> None:
        """Puts the SAME QAction instances the menu bar uses onto a
        QToolBar -- one signal connection per action, both surfaces always
        agree (enabled/disabled state included, e.g. while a run is in
        flight -- see :meth:`_set_running`).
        """
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        toolbar.addAction(self.new_action)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.save_action)
        toolbar.addSeparator()
        toolbar.addAction(self.run_action)
        toolbar.addAction(self.live_plot_action)
        toolbar.addAction(self.monte_carlo_action)
        toolbar.addAction(self.vizard_action)
        toolbar.addSeparator()
        toolbar.addAction(self.check_kernels_action)

        # "Run Simulation" is the app's primary call-to-action -- visually
        # distinguished with the accent color (see theme.py's
        # QToolButton#primaryToolButton rule), same idea as a web app's
        # primary button.
        run_button = toolbar.widgetForAction(self.run_action)
        if run_button is not None:
            run_button.setObjectName("primaryToolButton")

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
        self.mission_output_widget.clear()
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
        self.mission_output_widget.clear()
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

    # -- run-in-progress feedback -------------------------------------------
    def _set_running(self, running: bool) -> None:
        """Disables every Run-menu action while ANY run (single or Monte
        Carlo) is in flight -- previously only the action that started the
        run was disabled, so e.g. Run Monte Carlo could be triggered while a
        single run's worker was still using ``self._run_worker``, silently
        losing track of it. One run at a time.
        """
        for action in (self.run_action, self.live_plot_action, self.monte_carlo_action, self.vizard_action,
                       self.check_kernels_action):
            action.setEnabled(not running)

    def _start_busy(self, message: str, determinate: bool = False) -> None:
        self._set_running(True)
        self._busy_elapsed.start()
        self._busy_label.setText("0:00 elapsed")
        self._busy_label.setVisible(True)
        # A live-plot run reports real progress (engine.service.
        # SimulationService.run_live()'s fraction_complete) -- a real
        # percentage bar for it, rather than the indeterminate ("marching
        # ants") bar every other run still uses, since nothing else here
        # exposes a step/run progress callback to drive one (see the
        # class-level comment by self._busy_progress's construction).
        self._busy_progress.setRange(0, 100 if determinate else 0)
        if determinate:
            self._busy_progress.setValue(0)
        self._busy_progress.setVisible(True)
        self._busy_timer.start()
        self.statusBar().showMessage(message)

    def _stop_busy(self, message: str) -> None:
        self._set_running(False)
        self._busy_timer.stop()
        self._busy_label.setVisible(False)
        self._busy_progress.setVisible(False)
        self.statusBar().showMessage(message)

    def _update_busy_elapsed(self) -> None:
        seconds = self._busy_elapsed.elapsed() // 1000
        self._busy_label.setText(f"{seconds // 60}:{seconds % 60:02d} elapsed")

    # -- Run --------------------------------------------------------------
    def on_configure_vizard(self) -> None:
        current_save_file = getattr(self._vizard_request, "save_file", None)
        current_live_stream = getattr(self._vizard_request, "live_stream", False)
        current_camera_target = getattr(self._vizard_request, "camera_target", None)
        current_show_orbit_lines = getattr(self._vizard_request, "show_orbit_lines", True)
        dialog = VizardDialog(current_save_file=current_save_file, current_live_stream=current_live_stream,
                               current_camera_target=current_camera_target,
                               current_show_orbit_lines=current_show_orbit_lines, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._vizard_request = dialog.to_request()
            if self._vizard_request is None:
                self.statusBar().showMessage("Vizard disabled for the next run.")
            else:
                self.statusBar().showMessage("Vizard enabled for the next run.")

    def on_run(self) -> None:
        try:
            scenario = self.scenario_editor.to_scenario()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Cannot run invalid scenario", str(exc))
            return

        # engine.mission_engine.MissionEngine (used when scenario.
        # mission_sequence is non-empty) has no run_live() equivalent --
        # see RunWorker.run()'s docstring -- so live plotting only applies
        # when there's no mission sequence to execute instead.
        live = self.live_plot_action.isChecked() and not scenario.mission_sequence
        self._start_busy(f"Running {scenario.name}...", determinate=live)
        if live:
            # Clear any previous run's plot rather than leaving it up
            # while this run's first chunk is still in flight -- it would
            # otherwise look like this run already has results before it
            # actually does.
            self.results_widget.set_result(None)
            self.right_tabs.setCurrentWidget(self.results_widget)
        self.mission_output_widget.clear()
        self._run_worker = RunWorker(scenario, vizard_request=self._vizard_request, live=live)
        self._run_worker.progress.connect(self._on_run_progress)
        self._run_worker.finished_ok.connect(self._on_run_finished)
        self._run_worker.failed.connect(self._on_run_failed)
        self._run_worker.start()

    def _on_run_progress(self, partial_result, fraction: float) -> None:
        self.results_widget.set_live_result(partial_result)
        self._busy_progress.setValue(int(round(fraction * 100)))

    def _on_run_finished(self, result, command_summary=None) -> None:
        self._stop_busy(f"Run complete: {len(result.series)} result series.")
        # set_live_result(), not set_result(): a live run's final chunk and
        # its "finished" result always share the same series names, so
        # using set_result() here would rebuild series_combo and silently
        # snap the user's current selection back to the first series the
        # instant the run they were watching actually completes -- see
        # ResultsWidget.set_live_result()'s docstring for why that rebuild
        # is skipped when the series set hasn't changed. Also correct for
        # a non-live run: set_live_result() still rebuilds normally
        # whenever the series set differs from whatever was shown before.
        self.results_widget.set_live_result(result)
        if command_summary is not None:
            self.mission_output_widget.set_command_summary(command_summary)
            self.right_tabs.setCurrentWidget(self.mission_output_widget)
        else:
            self.right_tabs.setCurrentWidget(self.results_widget)

    def _on_run_failed(self, message: str) -> None:
        self._stop_busy("Run failed.")
        QMessageBox.critical(self, "Simulation failed", message)

    def on_run_monte_carlo(self) -> None:
        try:
            scenario = self.scenario_editor.to_scenario()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Cannot run invalid scenario", str(exc))
            return
        if not scenario.monte_carlo.enabled:
            QMessageBox.critical(self, "Monte Carlo is disabled",
                                  "Enable Monte Carlo (and add at least one dispersion) in the scenario form "
                                  "before running it.")
            return

        archive_dir_str = QFileDialog.getExistingDirectory(self, "Monte Carlo archive directory")
        if not archive_dir_str:
            return
        archive_dir = Path(archive_dir_str)

        self._start_busy(f"Running {scenario.monte_carlo.num_runs} Monte Carlo case(s)...")
        self._mc_worker = MonteCarloWorker(scenario, scenario.monte_carlo, archive_dir)
        self._mc_worker.finished_ok.connect(self._on_monte_carlo_finished)
        self._mc_worker.failed.connect(self._on_monte_carlo_failed)
        self._mc_worker.start()

    def _on_monte_carlo_finished(self, failures: list) -> None:
        if failures:
            self._stop_busy(f"Monte Carlo complete with {len(failures)} failed run(s).")
            QMessageBox.warning(self, "Monte Carlo finished with failures",
                                 f"Run indices that failed: {failures}")
        else:
            self._stop_busy("Monte Carlo complete -- all runs succeeded.")

    def _on_monte_carlo_failed(self, message: str) -> None:
        self._stop_busy("Monte Carlo run failed.")
        QMessageBox.critical(self, "Monte Carlo failed", message)

    # -- window lifecycle ---------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        # Refuse to close while a background run/Monte Carlo QThread is
        # still alive -- starting a run doesn't mark the scenario dirty, so
        # _confirm_discard_unsaved() alone would let the window (and, with
        # it, the whole process, since Qt tears down QApplication.exec()
        # once the last window closes) close right out from under a still
        # -running worker. Neither worker is parented, and
        # SimulationService.run()/run_live()/run_monte_carlo() are
        # synchronous Basilisk calls with no cooperative-cancellation hook
        # to interrupt, so there is no safe way to stop it early here --
        # closing must simply wait, same as it would for any other
        # in-progress, no-undo operation.
        for worker, label in ((self._run_worker, "A simulation"), (self._mc_worker, "A Monte Carlo run")):
            if worker is not None and worker.isRunning():
                QMessageBox.information(
                    self, "Run in progress",
                    f"{label} is still running. Please wait for it to finish (or fail) before closing missionStudio.",
                )
                event.ignore()
                return
        if self._confirm_discard_unsaved():
            event.accept()
        else:
            event.ignore()
