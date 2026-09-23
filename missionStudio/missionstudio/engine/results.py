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

r"""
Typed simulation result containers, independent of how the data was
produced -- :class:`engine.service.SimulationService` builds :class:`TimeSeries`/
:class:`ResultSet` from Basilisk recorders, and
:class:`engine.mission_engine.MissionEngine` builds :class:`ReportEntry`/
:class:`CommandSummary` from executing a scenario's ``mission_sequence``
-- but nothing in this module imports Basilisk, so it is fully
unit-testable here with synthetic arrays (see ``tests/test_results.py``)
and reusable by both the future GUI (for plotting/tables) and headless/
batch runs (for CSV export) without either one depending on the other.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np


class ResultsError(Exception):
    """Raised on malformed result data (mismatched array lengths, etc.) --
    never silently truncated or NaN-padded.
    """


@dataclass
class TimeSeries:
    """One named, multi-column time history (e.g. inertial position, in
    which case ``columns == ("x", "y", "z")`` and ``data`` has shape
    ``(n_samples, 3)``), plus the units it's in -- carried explicitly so a
    plot/export never has to guess.
    """

    name: str
    time_s: np.ndarray  # shape (n,), seconds since scenario epoch
    columns: Sequence[str]
    data: np.ndarray  # shape (n, len(columns))
    units: str = ""

    def __post_init__(self) -> None:
        self.time_s = np.asarray(self.time_s, dtype=float)
        self.data = np.asarray(self.data, dtype=float)
        if self.data.ndim == 1:
            # A recorder that never logged a single sample (e.g.
            # engine.mission_engine.MissionEngine.run() on a
            # mission_sequence with no propagate command in it at all --
            # ExecuteSimulation() is never called, so Basilisk's own
            # recorder .r_BN_N-style accessor returns a bare 1-D array of
            # shape (0,) rather than (0, len(columns)), losing the column
            # count entirely) can't be told apart from a genuinely
            # single-column series by shape alone once it's empty -- trust
            # the caller-supplied `columns` for the column count in that
            # case rather than guessing 1 (confirmed reachable directly
            # against a real Basilisk build; not a hypothetical).
            self.data = self.data.reshape(0, len(self.columns)) if self.data.shape[0] == 0 \
                else self.data.reshape(-1, 1)
        if self.data.shape[0] != self.time_s.shape[0]:
            raise ResultsError(
                f"TimeSeries {self.name!r}: time_s has {self.time_s.shape[0]} samples but "
                f"data has {self.data.shape[0]} rows -- these must match"
            )
        if self.data.shape[1] != len(self.columns):
            raise ResultsError(
                f"TimeSeries {self.name!r}: data has {self.data.shape[1]} columns but "
                f"{len(self.columns)} column names were given ({list(self.columns)})"
            )

    def to_csv(self, path: "str | Path") -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            header = ["time_s"] + [f"{c}" + (f"_{self.units}" if self.units else "") for c in self.columns]
            writer.writerow(header)
            for t, row in zip(self.time_s, self.data):
                writer.writerow([f"{t:.9g}"] + [f"{v:.9g}" for v in row])
        return path


@dataclass
class ResultSet:
    """Every :class:`TimeSeries` produced by one simulation run, keyed by
    name (e.g. ``"sat-1.position_N"``, ``"sat-1.velocity_N"``). One
    :class:`ResultSet` per completed :meth:`engine.service.SimulationService.run`
    call.
    """

    scenario_name: str
    series: Dict[str, TimeSeries] = field(default_factory=dict)

    def add(self, series: TimeSeries) -> None:
        if series.name in self.series:
            raise ResultsError(f"a TimeSeries named {series.name!r} was already added to this ResultSet")
        self.series[series.name] = series

    def export_csv(self, out_dir: "str | Path") -> Dict[str, Path]:
        """Write one CSV per series into ``out_dir`` (created if needed);
        returns ``{series_name: written_path}``.
        """
        out_dir = Path(out_dir)
        return {name: ts.to_csv(out_dir / f"{name}.csv") for name, ts in self.series.items()}


@dataclass
class ReportEntry:
    """One ``engine.mission_engine.Command(kind="report")``'s result: a
    snapshot (not a time history -- see ``MissionEngine._run_report``'s
    own docstring) of the requested series' most recent values at the
    mission time this report command ran. Defined here (Basilisk-free),
    not in ``engine.mission_engine`` (which imports ``engine.service`` ->
    Basilisk at module level), so it and :class:`CommandSummary` stay
    unit-testable with synthetic data the same way :class:`TimeSeries`/
    :class:`ResultSet` already are.
    """

    label: Optional[str]
    t_s: float  # [s] elapsed mission time when this report ran
    values: Dict[str, np.ndarray]


@dataclass
class CommandSummary:
    """Everything a ``mission_sequence`` run produced beyond the raw
    :class:`ResultSet`: one :class:`ReportEntry` per executed ``report``
    command, in execution order (so a ``report`` inside an ``if``/
    ``while`` only appears when that branch/iteration actually ran), plus
    a count of every command actually executed (a ``while`` body run 5
    times counts each of those 5 runs separately, matching how many times
    each command really affected the simulation). Built by
    ``engine.mission_engine.MissionEngine.run()``.
    """

    reports: List[ReportEntry] = field(default_factory=list)
    commands_executed: int = 0

    def export_csv(self, path: "str | Path") -> Path:
        """Writes every :class:`ReportEntry` to one CSV at ``path``, long
        format (one row per scalar component of every requested series in
        every report -- ``report_index, t_s, label, series, component,
        value``) rather than one column per series: different ``report``
        commands can request different series with different shapes (a
        3-vector position alongside a scalar mass, say), so there is no
        single fixed set of columns a wide-format table could use across
        every row. Matches :meth:`TimeSeries.to_csv`'s own formatting
        convention (``%.9g``) for consistency with the per-series CSVs
        :meth:`ResultSet.export_csv` already writes.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["report_index", "t_s", "label", "series", "component", "value"])
            for report_index, report in enumerate(self.reports):
                for series_name, values in report.values.items():
                    flat = np.asarray(values).reshape(-1)
                    for component_index, value in enumerate(flat):
                        writer.writerow([
                            report_index, f"{report.t_s:.9g}", report.label or "", series_name,
                            component_index, f"{float(value):.9g}",
                        ])
        return path
