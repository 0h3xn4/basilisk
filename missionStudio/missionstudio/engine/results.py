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
produced -- :class:`engine.service.SimulationService` builds these from
Basilisk recorders, but nothing in this module imports Basilisk, so it is
fully unit-testable here with synthetic arrays (see
``tests/test_results.py``) and reusable by both the future GUI (for
plotting) and headless/batch runs (for CSV export) without either one
depending on the other.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Sequence

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
            self.data = self.data.reshape(-1, 1)
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
