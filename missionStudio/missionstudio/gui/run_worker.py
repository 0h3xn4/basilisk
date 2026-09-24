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

"""RunWorker/MonteCarloWorker: run :class:`engine.service.SimulationService`/
:func:`engine.monte_carlo.run_monte_carlo` on a background ``QThread`` so a
(potentially long) propagation or batch never freezes the GUI's event
loop. Importing ``engine.service``/``engine.monte_carlo`` needs a
Basilisk build; when it's missing, each worker reports that clearly via
its own ``failed`` signal -- there is only one error-reporting path for
the caller (``MainWindow``) to handle per worker, whether the problem is
"no Basilisk", a bad scenario, or a Basilisk-internal error.

``RunWorker.run()`` dispatches on ``scenario.mission_sequence`` exactly
like ``cli.py``'s ``cmd_run()`` does: a non-empty sequence runs through
``engine.mission_engine.MissionEngine`` instead of
``SimulationService.run()``/``run_live()`` directly, and ``finished_ok``
always carries both the :class:`engine.results.ResultSet` and (when a
``mission_sequence`` ran) its :class:`engine.results.CommandSummary`, or
``None`` for the summary otherwise.

**Abort a running simulation** (direct user feedback: "there should be
an option to abort a running simulation, if needed, without breaking
the tool"): :meth:`RunWorker.request_cancel` sets a
:class:`threading.Event`, checked cooperatively between simulation
chunks (``SimulationService.run_live``'s ``should_cancel``) or between
mission_sequence commands (``MissionEngine``'s ``should_cancel``) --
never via ``QThread.terminate()`` or any other forced kill, which could
leave Basilisk's C++ simulation state mid-mutation and is exactly the
kind of "breaking the tool" this was asked to avoid. Cancellation
therefore always takes effect at the next such checkpoint, not
instantly (there is no hook into the middle of a single
``ExecuteSimulation()`` call -- see both ``should_cancel`` docstrings),
and a cancelled run reports the ``cancelled`` signal with whatever
partial ``ResultSet``/``CommandSummary`` had been produced so far,
rather than silently discarding it.

The non-mission_sequence path now ALWAYS runs through
``SimulationService.run_live()`` (never the plain, non-chunked
``run()``), specifically so it's always cancellable regardless of the
"Live Plot" toggle -- ``self.live`` now only controls whether
``progress`` is actually emitted (i.e. whether the plot redraws as it
goes), not whether the run is chunked at all. ``run_live()``'s own
docstring already notes ``_LIVE_DEFAULT_FRAMES`` (60) bounds this to a
small, fixed number of extra ``ExecuteSimulation()`` calls regardless
of run length -- negligible next to the actual simulated work, so this
applies with no live plot watching just as safely as with one.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..schema.scenario import MonteCarloConfig, Scenario

_logger = logging.getLogger(__name__)


class RunWorker(QThread):
    finished_ok = Signal(object, object)  # engine.results.ResultSet, Optional[engine.results.CommandSummary]
    failed = Signal(str)
    progress = Signal(object, float)  # engine.results.ResultSet (partial), fraction_complete in [0, 1]
    cancelled = Signal(object, object)  # engine.results.ResultSet (partial), Optional[engine.results.CommandSummary]

    def __init__(self, scenario: Scenario, vizard_request: Optional[object] = None, live: bool = False, parent=None):
        super().__init__(parent)
        self.scenario = scenario
        self.vizard_request = vizard_request  # engine.vizard.VizardRequest, or None
        # Whether `progress` is actually emitted as the run goes (driving
        # a live-updating plot -- see MainWindow.on_run()/the "Live plot"
        # toggle). No longer decides HOW the run executes -- see this
        # module's own docstring on why the non-mission_sequence path is
        # always chunked via run_live() now, live or not. Qt signals
        # emitted from a QThread are queued to the receiver's own thread
        # automatically (the default AutoConnection), so this is safe to
        # connect straight to GUI-thread slots without extra locking.
        self.live = live
        self._cancel_requested = threading.Event()

    def request_cancel(self) -> None:
        """Thread-safe -- called from the GUI thread while this worker's
        run() is executing on its own thread (see this module's own
        docstring for the cooperative-cancellation design and why a
        forced kill was never an option here).
        """
        self._cancel_requested.set()

    def _should_cancel(self) -> bool:
        return self._cancel_requested.is_set()

    def run(self) -> None:
        try:
            from ..engine.service import SimulationCancelled, SimulationService
        except ImportError as exc:
            self.failed.emit(
                f"Basilisk is not installed/built ({exc}) -- cannot run a simulation until it is. "
                f"See missionStudio/README.md."
            )
            return
        try:
            service = SimulationService(self.scenario, vizard_request=self.vizard_request)
            command_summary = None
            if self.scenario.mission_sequence:
                from ..engine.mission_engine import MissionEngine, MissionEngineCancelled

                try:
                    result, command_summary = MissionEngine(
                        self.scenario, service=service, should_cancel=self._should_cancel
                    ).run()
                except MissionEngineCancelled as exc:
                    self.cancelled.emit(exc.partial_result, exc.summary)
                    return
            else:
                def on_progress(partial, fraction):
                    if self.live:
                        self.progress.emit(partial, fraction)

                try:
                    result = service.run_live(on_progress, should_cancel=self._should_cancel)
                except SimulationCancelled as exc:
                    self.cancelled.emit(exc.partial_result, None)
                    return
        except Exception as exc:  # noqa: BLE001 -- surface ANY failure to the GUI, never crash the worker silently
            # Full traceback to the log file/terminal -- see
            # logging_setup's own module docstring for why str(exc) alone
            # (all the GUI's own error dialog ever shows) can be the ONLY
            # information anywhere about a genuinely unexpected failure,
            # with nothing else to go on, unless this is logged here.
            _logger.exception("RunWorker failed")
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result, command_summary)


class MonteCarloWorker(QThread):
    finished_ok = Signal(list)  # list[int] of failed run indices (empty == all succeeded)
    failed = Signal(str)

    def __init__(self, scenario: Scenario, mc_config: MonteCarloConfig, archive_dir: Path, parent=None):
        super().__init__(parent)
        self.scenario = scenario
        self.mc_config = mc_config
        self.archive_dir = archive_dir

    def run(self) -> None:
        try:
            from ..engine.monte_carlo import MonteCarloError, run_monte_carlo
        except ImportError as exc:
            self.failed.emit(
                f"Basilisk is not installed/built ({exc}) -- cannot run Monte Carlo until it is. "
                f"See missionStudio/README.md."
            )
            return
        try:
            failures = run_monte_carlo(self.scenario, self.mc_config, self.archive_dir)
        except MonteCarloError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 -- surface ANY failure to the GUI, never crash the worker silently
            _logger.exception("MonteCarloWorker failed")
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(failures)
