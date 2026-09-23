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

"""MissionOutputWidget: the "debug console" for a ``mission_sequence``
run -- a read-only text log of every ``report`` command's
``engine.results.ReportEntry`` (mission time, label, requested series'
snapshot values), in execution order, plus the total command count from
``engine.results.CommandSummary``. Populated once per run by
``MainWindow._on_run_finished()``, not incrementally -- ``RunWorker``
only emits a whole ``CommandSummary`` at the end (``engine.mission_engine.
MissionEngine.run()`` has no per-command progress callback, same
limitation ``RunWorker``'s own docstring already notes for
``engine.service.SimulationService.run()`` vs. ``run_live()``).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from ..engine.results import CommandSummary


class MissionOutputWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        font = self.text_edit.font()
        font.setFamily("monospace")
        self.text_edit.setFont(font)
        self.text_edit.setPlaceholderText(
            "No mission_sequence commands have run yet -- add commands under Mission sequence and Run Simulation."
        )
        layout.addWidget(self.text_edit)

    def clear(self) -> None:
        self.text_edit.clear()

    def set_command_summary(self, summary: Optional[CommandSummary]) -> None:
        if summary is None:
            self.clear()
            return
        lines = [f"{summary.commands_executed} command(s) executed, {len(summary.reports)} report(s):", ""]
        for i, report in enumerate(summary.reports):
            label = f" ({report.label})" if report.label else ""
            lines.append(f"[{i}] t = {report.t_s:.3f} s{label}")
            for series_name, values in report.values.items():
                lines.append(f"      {series_name} = {values.tolist()}")
        self.text_edit.setPlainText("\n".join(lines))
