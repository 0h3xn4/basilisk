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

"""RunWorker: runs :class:`engine.service.SimulationService` on a
background ``QThread`` so a (potentially long) propagation never freezes
the GUI's event loop. Importing ``engine.service`` needs a Basilisk
build; when it's missing, this worker reports that clearly via the same
``failed`` signal used for any other run failure -- there is only one
error-reporting path for the caller (``MainWindow``) to handle, whether
the problem is "no Basilisk", a bad scenario, or a Basilisk-internal
error.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..schema.scenario import Scenario


class RunWorker(QThread):
    finished_ok = Signal(object)  # engine.results.ResultSet
    failed = Signal(str)

    def __init__(self, scenario: Scenario, parent=None):
        super().__init__(parent)
        self.scenario = scenario

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
            service = SimulationService(self.scenario)
            result = service.run()
        except Exception as exc:  # noqa: BLE001 -- surface ANY failure to the GUI, never crash the worker silently
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result)
