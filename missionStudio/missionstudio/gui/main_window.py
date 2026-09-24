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

import subprocess
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
from .load_scenario_widget import LoadScenarioWidget
from .mission_output_widget import MissionOutputWidget
from .results_widget import ResultsWidget
from .run_worker import MonteCarloWorker, RunWorker
from .scenario_editor import ScenarioEditorWidget
from .vizard_dialog import VizardDialog
from .vizard_launcher import (
    DEFAULT_LIVE_STREAM_ADDRESS,
    find_vizard_executable,
    launch_vizard,
    remember_vizard_executable,
)

_FILE_FILTER = "missionStudio scenario (*.json)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Wider default than before: the scenario form's own natural
        # content width (~576px, e.g. the "Full attitude (sensors,
        # actuators, FSW, power)" mode combo) needs a genuinely wide left
        # pane, and giving the left pane a smaller SHARE of the window
        # (see the splitter setup below) without also growing the window
        # itself would starve that content back down to where it needed
        # its own horizontal scrollbar.
        self.resize(1400, 850)

        self._current_path: Path | None = None
        self._dirty = False
        self._run_worker: RunWorker | None = None
        self._mc_worker: MonteCarloWorker | None = None
        self._vizard_request = None  # engine.vizard.VizardRequest, or None -- set via the Run menu's "Vizard Configuration..." action
        self._vizard_process = None  # subprocess.Popen, or None -- set via the Run menu's "Launch Vizard" action
        # The direct_comm_address self._vizard_process was actually launched
        # with (None if it was launched with no -directComm flag at all) --
        # lets on_launch_vizard() tell a live-stream-ready instance apart
        # from one that isn't, instead of trusting ANY already-running
        # process regardless of how it was started. See on_launch_vizard()'s
        # own docstring.
        self._vizard_direct_comm_address = None
        # -directComm pre-fills Vizard's own socket address field and
        # selects DirectComm/Live Display for the user, but -- confirmed
        # by direct user report -- does NOT click its "Start
        # Visualization" button for them; that one click is still needed
        # every time Vizard is (re)launched this way, and no documented
        # command-line flag skips it while keeping the visible live view
        # (see on_launch_vizard()'s own comment). Shown once per session
        # (not on every single launch/run) so the user isn't stuck
        # wondering why the run is "stuck" without knowing this, but
        # also isn't nagged repeatedly once they do.
        self._vizard_live_stream_hint_shown = False
        self._last_run_epoch_utc: str | None = None  # set in on_run(); see its own comment

        self.scenario_editor = ScenarioEditorWidget()
        self.scenario_editor.reset_to_default()
        self.scenario_editor.changed.connect(self._mark_dirty)

        self.load_scenario_widget = LoadScenarioWidget()
        self.load_scenario_widget.path_chosen.connect(self._on_load_scenario_path_chosen)

        self.results_widget = ResultsWidget()
        self.mission_output_widget = MissionOutputWidget()
        self.kernel_status_widget = KernelStatusWidget()

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.results_widget, "Results")
        self.right_tabs.addTab(self.mission_output_widget, "Mission Output")
        self.right_tabs.addTab(self.kernel_status_widget, "Kernel Status")

        # "Load Scenario" first (index 0, so it's what a freshly launched
        # window shows) -- a new user's first move is picking a built-in
        # template or browsing for a file, not editing the blank default
        # scenario reset_to_default() just set up. open_path() (below)
        # switches to "Scenario Editor" the moment anything actually
        # loads, whichever of the two ways (this tab, or File > Open) got
        # it there.
        self.left_tabs = QTabWidget()
        self.left_tabs.addTab(self.load_scenario_widget, "Load Scenario")
        self.left_tabs.addTab(self.scenario_editor, "Scenario Editor")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left_tabs)
        splitter.addWidget(self.right_tabs)
        # Left (scenario form/template picker) is narrower than right
        # (results plots/mission output/kernel status) by design -- an
        # even 50/50 split left the form looking oversized relative to
        # what it actually needs, and shortchanged the plots/text on the
        # right. setSizes() fixes the initial split; the stretch factors
        # keep that same ~3:5 ratio if the user resizes the window.
        splitter.setSizes([580, 820])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
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

        # "Abort a running simulation, if needed, without breaking the
        # tool" -- direct user feedback. Only ever enabled while a single
        # (non-Monte-Carlo) run is actually in flight -- see on_run()/
        # _stop_busy() for where it's toggled -- since RunWorker is the
        # only worker with a request_cancel() to call (see its module
        # docstring for the cooperative-cancellation design; Monte Carlo
        # batches have no equivalent hook and are out of scope here).
        abort_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop), "&Abort Run", self)
        abort_action.setToolTip("Abort the running simulation (takes effect at the next checkpoint, not instantly)")
        abort_action.setEnabled(False)
        abort_action.triggered.connect(self.on_abort_run)
        run_menu.addAction(abort_action)
        self.abort_action = abort_action

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

        vizard_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DesktopIcon),
                                 "Vizard &Configuration...", self)
        vizard_action.setToolTip("Configure Vizard visualization for the next run")
        vizard_action.triggered.connect(self.on_configure_vizard)
        run_menu.addAction(vizard_action)
        self.vizard_action = vizard_action

        # Distinct from "Vizard Configuration..." above (which only
        # decides how the NEXT run feeds Vizard, e.g. a live stream or a
        # playback file) -- this one actually starts the separate Vizard
        # application, so live-stream mode has something to connect to.
        vizard_launch_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
                                        "&Launch Vizard", self)
        vizard_launch_action.setToolTip("Start the external Vizard application")
        vizard_launch_action.triggered.connect(self.on_launch_vizard)
        run_menu.addAction(vizard_launch_action)
        self.vizard_launch_action = vizard_launch_action

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
        toolbar.addAction(self.abort_action)
        toolbar.addAction(self.live_plot_action)
        toolbar.addAction(self.monte_carlo_action)
        toolbar.addAction(self.vizard_action)
        toolbar.addAction(self.vizard_launch_action)
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
        self.left_tabs.setCurrentWidget(self.scenario_editor)

    def on_open(self) -> None:
        if not self._confirm_discard_unsaved():
            return
        path_str, _selected_filter = QFileDialog.getOpenFileName(self, "Open scenario", "", _FILE_FILTER)
        if not path_str:
            return
        self.open_path(Path(path_str))

    def _on_load_scenario_path_chosen(self, path) -> None:
        """Handles LoadScenarioWidget.path_chosen -- a template picked
        from its built-in list, or a file picked via its own "Browse for
        a file..." button. Gated by the same unsaved-changes confirmation
        as File > New/Open, since it replaces the scenario currently
        being edited exactly like those do.
        """
        if not self._confirm_discard_unsaved():
            return
        self.open_path(Path(path))

    def open_path(self, path: Path) -> bool:
        try:
            scenario = load_scenario(path)
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Could not open scenario", str(exc))
            return False
        self.scenario_editor.from_scenario(scenario)
        self._current_path = path
        self.results_widget.set_result(None)
        self.mission_output_widget.clear()
        self._mark_clean()
        self.statusBar().showMessage(f"Opened {path}")
        self.left_tabs.setCurrentWidget(self.scenario_editor)
        return True

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
                       self.vizard_launch_action, self.check_kernels_action):
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
        self.abort_action.setEnabled(False)
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

    def on_launch_vizard(self) -> bool:
        """Starts the external Vizard application -- a no-op if an
        instance already running is already suitable (see below).
        Distinct from :meth:`on_configure_vizard`, which never touches a
        process at all: it only decides how the NEXT run feeds an
        instance of Vizard, wherever/however that instance got started.

        When the current Vizard Configuration is set to live-stream,
        Vizard is launched with its own ``-directComm`` command-line
        argument (see ``vizard_launcher.DEFAULT_LIVE_STREAM_ADDRESS``'s
        own comment) -- direct user feedback that manually launching
        Vizard left it sitting on its own "Load Data Using One of the
        Following" screen, doing nothing, because nobody had typed the
        socket address in by hand. ``-directComm`` pre-fills that
        address and selects DirectComm/Live Display, but -- confirmed by
        a further direct user report -- does NOT click Vizard's own
        "Start Visualization" button; no documented command-line flag
        does that while keeping the visible live view (the fully
        headless ``-batchmode -noDisplay`` combination skips it, but
        also skips rendering anything at all, defeating the point of a
        LIVE VISUALIZATION). That one click is therefore still needed
        each time Vizard is (re)launched this way -- see
        ``self._vizard_live_stream_hint_shown`` for how that's
        communicated instead of silently left for the user to discover.

        A previously-tracked ``self._vizard_process`` (one THIS method
        itself launched earlier, in this same session -- see
        ``self._vizard_direct_comm_address``) is only trusted as-is if it
        already matches what's needed now: still running, and either no
        ``-directComm`` is needed this time, or it already has the one
        needed. A live-stream run needing one that the tracked instance
        doesn't have is a real, reachable case -- e.g. Vizard was
        launched earlier for a save-file run, or before Vizard
        Configuration was ever set to live-stream -- and trusting it
        anyway would reproduce the exact original bug, just one launch
        later. That mismatched instance is terminated and a fresh one
        relaunched with the correct flag instead. The reverse (a
        live-stream-ready instance already running, but a save-file/no
        -request launch is what's needed now) is left alone -- having
        ``-directComm`` active doesn't stop Vizard from also opening a
        save file, so there is nothing broken to fix there. An instance
        this session never itself launched (``self._vizard_process`` is
        still ``None`` -- started by the user outside missionStudio, or
        in an earlier session) is left completely alone; a second,
        correctly-configured instance is launched alongside it instead,
        since there is no reliable way to ask an arbitrary already
        -running Vizard process "are you already connected".

        Returns True once Vizard is confirmed running (already was, or
        was just started) by the end of this call, False if the user
        cancelled a browse prompt or launching genuinely failed (an
        error was already shown in that case) -- :meth:`on_run` uses
        this to decide whether it's safe to start a live-stream run at
        all.
        """
        direct_comm_address = (
            DEFAULT_LIVE_STREAM_ADDRESS
            if self._vizard_request is not None and self._vizard_request.live_stream
            else None
        )
        if self._vizard_process is not None and self._vizard_process.poll() is None:
            if not direct_comm_address or self._vizard_direct_comm_address == direct_comm_address:
                self.statusBar().showMessage("Vizard is already running.")
                return True
            self._terminate_vizard_process()

        executable = find_vizard_executable()
        if executable is None:
            path_str, _selected_filter = QFileDialog.getOpenFileName(self, "Locate the Vizard application")
            if not path_str:
                return False
            executable = Path(path_str)
            remember_vizard_executable(executable)
        try:
            self._vizard_process = launch_vizard(executable, direct_comm_address=direct_comm_address)
        except OSError as exc:
            QMessageBox.critical(self, "Could not launch Vizard", f"{executable}: {exc}")
            return False
        self._vizard_direct_comm_address = direct_comm_address
        if direct_comm_address:
            self.statusBar().showMessage(
                f"Launched Vizard ({executable}) -- click \"Start Visualization\" in the Vizard window to connect."
            )
            if not self._vizard_live_stream_hint_shown:
                # Once per session, not once per launch/run -- see
                # self._vizard_live_stream_hint_shown's own comment. The
                # status bar message above (shown every time) is easy to
                # miss/get overwritten by the "Running..." message that
                # follows moments later when this was triggered from
                # on_run() -- this dialog can't be missed the first time.
                QMessageBox.information(
                    self, "Vizard needs one click to connect",
                    f"Vizard was launched with its socket address already filled in "
                    f"({direct_comm_address}), but it still needs \"Start Visualization\" clicked in "
                    f"its own window before the run can begin -- Vizard has no command-line option to "
                    f"skip that one click while still showing the live view. missionStudio will wait "
                    f"for it (this is shown once per session)."
                )
                self._vizard_live_stream_hint_shown = True
        else:
            self.statusBar().showMessage(f"Launched Vizard ({executable}).")
        return True

    def _terminate_vizard_process(self) -> None:
        """Stops ``self._vizard_process`` (a mismatched instance
        :meth:`on_launch_vizard` is about to replace -- see its own
        docstring) and waits (bounded, so a Vizard that refuses to exit
        can't hang the GUI thread forever) for it to actually stop before
        returning, so the port it may have bound is free for the
        replacement instance. ``terminate()`` first (a clean exit, in
        case Vizard has anything to flush/save), ``kill()`` only if that
        doesn't work within the timeout.
        """
        self._vizard_process.terminate()
        try:
            self._vizard_process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._vizard_process.kill()
            self._vizard_process.wait(timeout=5.0)
        self._vizard_process = None
        self._vizard_direct_comm_address = None

    def on_run(self) -> None:
        try:
            scenario = self.scenario_editor.to_scenario()
        except ScenarioValidationError as exc:
            QMessageBox.critical(self, "Cannot run invalid scenario", str(exc))
            return

        if self._vizard_request is not None and self._vizard_request.live_stream:
            # Basilisk's InitializeSimulation() BLOCKS (inside native
            # C++, with no Python-level hook -- see RunWorker's own
            # module docstring on why there's no cancellation checkpoint
            # reachable here) waiting for Vizard to reply to an initial
            # handshake ping in live-stream mode -- direct user report:
            # a run appeared to hang at 0% forever, with Abort having no
            # effect, because Vizard was never actually connected.
            # on_launch_vizard() launches Vizard with -directComm when
            # needed (see its own docstring) so this handshake has
            # something to actually reply to; if it can't even do that
            # (Vizard not found/couldn't start), starting the run at all
            # would just reproduce the same hang, so it's refused here
            # instead, with a clear reason, rather than silently risking
            # it.
            if not self.on_launch_vizard():
                QMessageBox.critical(
                    self, "Vizard not connected",
                    "Vizard Configuration is set to live-stream, but Vizard could not be confirmed running. "
                    "Starting the run now would hang waiting for a Vizard connection that never arrives, "
                    "with no way to abort it -- use \"Launch Vizard\" (or fix the live-stream setup) first."
                )
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
        # Captured now (not read back from self.scenario_editor later,
        # e.g. in _on_run_finished()): the editor isn't locked while a run
        # is in flight, so it could hold different, later edits by the
        # time this run actually finishes. This is the exact epoch that
        # exact ResultSet's time_s values are relative to.
        self._last_run_epoch_utc = scenario.epoch_utc
        self._run_worker = RunWorker(scenario, vizard_request=self._vizard_request, live=live)
        self._run_worker.progress.connect(self._on_run_progress)
        self._run_worker.finished_ok.connect(self._on_run_finished)
        self._run_worker.failed.connect(self._on_run_failed)
        self._run_worker.cancelled.connect(self._on_run_cancelled)
        self._run_worker.start()
        # Only RunWorker has a request_cancel() to call (see on_abort_run
        # and this action's own construction comment) -- enabled here,
        # right after start(), rather than lumped into _set_running(),
        # since on_run_monte_carlo()'s _start_busy() call must NOT enable
        # it.
        self.abort_action.setEnabled(True)

    def on_abort_run(self) -> None:
        if self._run_worker is not None and self._run_worker.isRunning():
            self._run_worker.request_cancel()
            # Cancellation is cooperative, not instant (see RunWorker's own
            # module docstring) -- disabled immediately so the user isn't
            # tempted to click it again while waiting for the next
            # checkpoint; _stop_busy() re-disables it anyway once the
            # worker actually reports back, but that can be a moment away.
            self.abort_action.setEnabled(False)
            self.statusBar().showMessage("Aborting... this takes effect at the next checkpoint, not instantly.")

    def _on_run_progress(self, partial_result, fraction: float) -> None:
        self.results_widget.set_live_result(partial_result, self._last_run_epoch_utc)
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
        self.results_widget.set_live_result(result, self._last_run_epoch_utc)
        if command_summary is not None:
            self.mission_output_widget.set_command_summary(command_summary)
            self.right_tabs.setCurrentWidget(self.mission_output_widget)
        else:
            self.right_tabs.setCurrentWidget(self.results_widget)

    def _on_run_failed(self, message: str) -> None:
        self._stop_busy("Run failed.")
        QMessageBox.critical(self, "Simulation failed", message)

    def _on_run_cancelled(self, partial_result, command_summary=None) -> None:
        """Handles RunWorker.cancelled -- a user-requested abort (see
        on_abort_run()), not a failure: whatever was already simulated
        before the cancellation took effect is shown exactly like a
        normal finish would show it, just with "cancelled" messaging
        instead of "complete".
        """
        self._stop_busy("Run cancelled by user.")
        self.results_widget.set_live_result(partial_result, self._last_run_epoch_utc)
        if command_summary is not None:
            self.mission_output_widget.set_command_summary(command_summary)
            self.right_tabs.setCurrentWidget(self.mission_output_widget)
        else:
            self.right_tabs.setCurrentWidget(self.results_widget)

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
        # -running worker. Neither worker is parented. RunWorker DOES now
        # have a cooperative-cancellation hook (request_cancel(), see its
        # own module docstring / on_abort_run() above), but it only takes
        # effect at the next chunk/command checkpoint, not instantly, and
        # MonteCarloWorker/run_monte_carlo() still has no such hook at
        # all -- so closing must simply wait either way, same as it would
        # for any other in-progress, no-undo operation, rather than firing
        # an implicit abort the user never asked for.
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
