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
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..schema.scenario import MonteCarloConfig, Scenario


class RunWorker(QThread):
    finished_ok = Signal(object)  # engine.results.ResultSet
    failed = Signal(str)

    def __init__(self, scenario: Scenario, vizard_request: Optional[object] = None, parent=None):
        super().__init__(parent)
        self.scenario = scenario
        self.vizard_request = vizard_request  # engine.vizard.VizardRequest, or None

    def run(self) -> None:
        try:
            from ..engine.service import SimulationService
        except ImportError as exc:
            self.failed.emit(
                f"Basilisk is not installed/built ({exc}) -- cannot run a simulation until it is. "
                f"See missionStudio/README.md."
            )
            return
        try:
            service = SimulationService(self.scenario, vizard_request=self.vizard_request)
            result = service.run()
        except Exception as exc:  # noqa: BLE001 -- surface ANY failure to the GUI, never crash the worker silently
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result)


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
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(failures)
