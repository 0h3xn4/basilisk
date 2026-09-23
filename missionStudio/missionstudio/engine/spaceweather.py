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
Space-weather resolution for Basilisk's ``spaceWeatherData`` module (which
drives ``msisAtmosphere`` for atmospheric drag), per the user's explicit
instruction: fetch from CelesTrak; if that isn't possible, fall back to a
user-provided local file; only fall back further than that (a synthetic
profile) loudly, never silently.

No Basilisk import in this module -- it is pure standard library + numpy,
fully unit-testable without a Basilisk build (see ``tests/test_spaceweather.py``).
The network fetch itself is the one thing this module cannot prove works in
THIS sandbox: this session's outbound-network policy blocks
``celestrak.org`` (confirmed with a direct ``curl`` test -- a 403 policy
denial, not a timeout), so :func:`fetch` is written against CelesTrak's
documented CSV format but has not been exercised end-to-end here. The CSV
validation, synthetic-fallback generation, and the ``resolve()`` fallback
chain are all fully tested here (no network needed for any of them).

Format note (verified against this checkout's own
``spaceWeatherData.cpp``, not assumed): the loader parses its input CSV by
**column name** from the header row, requiring only
``DATE, AP1..AP8, AP_AVG, F10.7_OBS, F10.7_OBS_CENTER81`` to be present --
extra columns are ignored. A real CelesTrak ``SW-All.csv``/
``SW-Last5Years.csv`` download has those exact column names (plus many
more Basilisk doesn't need), so it can be hand to
``spaceWeatherData.loadSpaceWeatherFile()`` completely unmodified: no
reformatting step exists or is needed in this module.

CelesTrak's files only cover the past plus a short (~1 year) predicted
window -- they cannot cover a mission that starts far enough out and runs
long enough. :func:`resolve` handles that the same way
``missionAnalysis/generate_space_weather_placeholder.py`` does: fall back
to a synthetic, solar-cycle-shaped (but not a real forecast) profile,
loudly warned about, never silently substituted.
"""

from __future__ import annotations

import csv
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

REQUIRED_COLUMNS = (
    "DATE", "AP1", "AP2", "AP3", "AP4", "AP5", "AP6", "AP7", "AP8",
    "AP_AVG", "F10.7_OBS", "F10.7_OBS_CENTER81",
)

# CelesTrak's two space-weather CSV products -- Last5Years is smaller/faster
# to fetch and covers most near-term missions; All is the full historical
# record (needed if the scenario epoch is more than ~5 years in the past).
CELESTRAK_URLS = {
    "SW-Last5Years": "https://celestrak.org/SpaceData/SW-Last5Years.csv",
    "SW-All": "https://celestrak.org/SpaceData/SW-All.csv",
}

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "missionStudio" / "spaceweather"

# Synthetic fallback: a smooth ~11-year solar-cycle envelope with correlated
# day-to-day noise and occasional storm episodes -- shaped like real solar
# activity, but not tied to any actual cycle forecast. Ported from
# ../missionAnalysis/generate_space_weather_placeholder.py, generalized to
# take an arbitrary date range instead of reading missionAnalysis's own
# mission_config.py.
_PAD_DAYS = 10
_F107_SOLAR_MIN = 70.0  # [sfu]
_F107_SOLAR_MAX = 150.0  # [sfu]
_CYCLE_PERIOD_DAYS = 11.0 * 365.25  # [day]
_CYCLE_PHASE_DAYS = -2.0 * 365.25  # [day]


class SpaceWeatherError(Exception):
    """Raised on an unresolvable space-weather request (bad source name,
    local file missing/invalid with no fallback available, etc.) -- never
    a silent empty/garbage file.
    """


@dataclass
class ValidationResult:
    ok: bool
    covers_range: bool
    missing_columns: list
    duplicate_dates: list
    unsorted: bool
    first_date: Optional[str]
    last_date: Optional[str]
    message: str


@dataclass
class ResolvedSpaceWeather:
    path: Path
    is_synthetic: bool
    warnings: list = field(default_factory=list)


def validate_file(path, start_utc: datetime, end_utc: datetime) -> ValidationResult:
    """Pre-flight-check a space-weather CSV against exactly what
    ``spaceWeatherData.cpp``'s ``loadSpaceWeatherFile()`` itself requires
    (required columns present by name, ``DATE`` rows unique and sorted
    ascending -- mirroring that C++ loader's own validation so this tool
    can raise a friendly, specific error BEFORE handing the file to
    Basilisk) plus a range check.
    """
    path = Path(path)
    if not path.exists():
        return ValidationResult(False, False, list(REQUIRED_COLUMNS), [], False, None, None,
                                 f"{path} does not exist")

    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        date_idx = header.index("DATE") if "DATE" in header else None

        dates = []
        duplicates = []
        unsorted = False
        seen = set()
        prev = None
        if date_idx is not None:
            for row in reader:
                if not row or date_idx >= len(row):
                    continue
                d = row[date_idx].strip()
                if not d:
                    continue
                dates.append(d)
                if d in seen:
                    duplicates.append(d)
                seen.add(d)
                if prev is not None and d < prev:
                    unsorted = True
                prev = d

    first_date, last_date = (dates[0], dates[-1]) if dates else (None, None)

    covers_range = False
    if first_date and last_date:
        try:
            # Compare calendar dates, not full datetimes: each DATE row is
            # daily-resolution data covering its ENTIRE day, but
            # start_utc/end_utc can carry a non-zero time-of-day (e.g.
            # scenario.epoch_utc="...T14:00:00" -- Scenario.validate()
            # only requires it to parse as ISO 8601, not to be midnight).
            # Comparing full datetimes made a file whose last row is the
            # scenario's own end date fail this check whenever end_utc's
            # time-of-day was after midnight, even though that day's data
            # is genuinely present -- see this module's docstring/audit
            # note.
            covers_range = (
                datetime.strptime(first_date, "%Y-%m-%d").date() <= start_utc.date()
                and datetime.strptime(last_date, "%Y-%m-%d").date() >= end_utc.date()
            )
        except ValueError:
            covers_range = False

    ok = not missing and not duplicates and not unsorted and covers_range
    reasons = []
    if missing:
        reasons.append(f"missing required column(s): {missing}")
    if duplicates:
        reasons.append(f"{len(duplicates)} duplicate DATE row(s)")
    if unsorted:
        reasons.append("DATE rows are not sorted ascending")
    if not covers_range:
        reasons.append(f"file covers {first_date}..{last_date}, scenario needs "
                        f"{start_utc.date()}..{end_utc.date()}")

    return ValidationResult(ok, covers_range, missing, duplicates, unsorted, first_date, last_date,
                             "OK" if ok else "; ".join(reasons))


def fetch(dataset: str = "SW-All", cache_dir: Optional[Path] = None, force: bool = False,
          timeout_s: float = 30.0) -> Path:
    """Download a CelesTrak space-weather CSV to a local cache and return
    its path. Raises :class:`SpaceWeatherError` (never returns a partial/
    corrupt file) on any network or HTTP failure -- callers (see
    :func:`resolve`) are expected to catch this and fall back per the
    documented chain, not to treat a fetch failure as fatal on its own.

    NOT exercised end-to-end in this development sandbox -- ``celestrak.org``
    is blocked by this environment's outbound-network policy (confirmed via
    a direct ``curl`` returning a 403 policy denial, not a timeout). Written
    directly against CelesTrak's documented CSV endpoints; verify on first
    real-network use.
    """
    if dataset not in CELESTRAK_URLS:
        raise SpaceWeatherError(f"unknown CelesTrak dataset {dataset!r}, expected one of {list(CELESTRAK_URLS)}")

    cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{dataset}.csv"
    if dest.exists() and not force:
        return dest

    url = CELESTRAK_URLS[dataset]
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SpaceWeatherError(f"could not fetch {url}: {exc}") from exc

    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)  # atomic-ish: never leave a half-written file at `dest`
    return dest


def _f107_base(day_index: np.ndarray) -> np.ndarray:
    phase = 2.0 * np.pi * (day_index + _CYCLE_PHASE_DAYS) / _CYCLE_PERIOD_DAYS
    midpoint = 0.5 * (_F107_SOLAR_MAX + _F107_SOLAR_MIN)
    amplitude = 0.5 * (_F107_SOLAR_MAX - _F107_SOLAR_MIN)
    return midpoint + amplitude * np.cos(phase)


def generate_synthetic(start_utc: datetime, end_utc: datetime, dest_path, seed: int = 42) -> Path:
    """Write a synthetic, solar-cycle-shaped (NOT a real forecast)
    space-weather CSV covering ``[start_utc, end_utc]`` (plus padding) to
    ``dest_path``, in the exact column layout :func:`validate_file`/
    Basilisk's loader expect. Deterministic given the same inputs (fixed
    default seed) so repeated runs of the same scenario are reproducible.
    """
    rng = np.random.default_rng(seed)

    start = start_utc - timedelta(days=_PAD_DAYS)
    end = end_utc + timedelta(days=_PAD_DAYS)
    n_days = (end - start).days + 1
    dates = [start + timedelta(days=i) for i in range(n_days)]
    day_index = np.arange(n_days, dtype=float)

    f107_base = _f107_base(day_index)
    noise = np.zeros(n_days)
    for i in range(1, n_days):
        noise[i] = 0.85 * noise[i - 1] + rng.normal(0.0, 3.0)
    f107_obs = np.clip(f107_base + noise, 65.0, 300.0)

    f107_center81 = np.array([
        f107_obs[max(0, i - 40): min(n_days, i + 41)].mean() for i in range(n_days)
    ])

    ap_avg = np.zeros(n_days)
    storm_prob = 0.02 + 0.03 * (f107_base - _F107_SOLAR_MIN) / (_F107_SOLAR_MAX - _F107_SOLAR_MIN)
    day = 0
    while day < n_days:
        if rng.random() < storm_prob[day]:
            duration = rng.integers(1, 4)
            peak = rng.uniform(30.0, 110.0)
            for k in range(duration):
                if day + k < n_days:
                    ap_avg[day + k] = max(ap_avg[day + k], peak * (0.6 ** k))
            day += duration
        else:
            ap_avg[day] = rng.uniform(3.0, 12.0)
            day += 1

    ap_3hr = np.clip(ap_avg[:, None] + rng.normal(0.0, 2.0, size=(n_days, 8)), 0.0, None)

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["DATE", "AP1", "AP2", "AP3", "AP4", "AP5", "AP6", "AP7", "AP8",
                          "AP_AVG", "F10.7_OBS", "F10.7_OBS_CENTER81"])
        for i, d in enumerate(dates):
            writer.writerow(
                [d.strftime("%Y-%m-%d")]
                + [f"{v:.1f}" for v in ap_3hr[i]]
                + [f"{ap_avg[i]:.1f}", f"{f107_obs[i]:.1f}", f"{f107_center81[i]:.1f}"]
            )
    return dest_path


def _synthetic_cache_path(cache_dir: Optional[Path], start_utc: datetime, end_utc: datetime) -> Path:
    cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    name = f"synthetic_{start_utc:%Y%m%d}_{end_utc:%Y%m%d}.csv"
    return cache_dir / name


def resolve(source: str, start_utc: datetime, end_utc: datetime,
            local_file_path: Optional[str] = None, cache_dir: Optional[Path] = None) -> ResolvedSpaceWeather:
    """Top-level entry point -- resolves a ``SpaceWeatherConfig`` (see
    ``schema.scenario``) into an actual, validated CSV path Basilisk's
    ``spaceWeatherData.loadSpaceWeatherFile()`` can load, following the
    user-specified fallback chain:

    * ``source == "local_file"``: use exactly that file; error if missing
      or invalid (no silent fallback -- the user asked for this file).
    * ``source == "synthetic"``: generate the synthetic profile directly
      (explicitly requested, so still loud about being synthetic, but not
      a "fallback" in the sense of something failing first).
    * ``source == "celestrak"`` (the default): try ``SW-Last5Years`` then
      ``SW-All`` from CelesTrak; if the fetch fails OR the downloaded file
      doesn't cover the scenario's date range, fall back to
      ``local_file_path`` if one was given; if that also isn't usable,
      fall back to the synthetic generator as a last resort -- every
      fallback step appends a human-readable warning to the returned
      :class:`ResolvedSpaceWeather`, so the GUI/CLI can surface exactly
      what happened rather than silently substituting data.
    """
    warnings: list = []

    if source == "local_file":
        if not local_file_path:
            raise SpaceWeatherError("space_weather.source is 'local_file' but local_file_path was not set")
        result = validate_file(local_file_path, start_utc, end_utc)
        if not result.ok:
            raise SpaceWeatherError(f"{local_file_path} failed validation: {result.message}")
        return ResolvedSpaceWeather(Path(local_file_path), False, warnings)

    if source == "synthetic":
        path = _synthetic_cache_path(cache_dir, start_utc, end_utc)
        generate_synthetic(start_utc, end_utc, path)
        warnings.append("space weather is SYNTHETIC (not real observed/forecast data) -- explicitly requested.")
        return ResolvedSpaceWeather(path, True, warnings)

    if source != "celestrak":
        raise SpaceWeatherError(f"unknown space_weather.source {source!r}")

    for dataset in ("SW-Last5Years", "SW-All"):
        try:
            path = fetch(dataset=dataset, cache_dir=cache_dir)
        except SpaceWeatherError as exc:
            warnings.append(f"CelesTrak fetch of {dataset} failed: {exc}")
            continue
        result = validate_file(path, start_utc, end_utc)
        if result.ok:
            return ResolvedSpaceWeather(path, False, warnings)
        warnings.append(f"CelesTrak {dataset} does not cover the requested range ({result.message})")

    if local_file_path:
        result = validate_file(local_file_path, start_utc, end_utc)
        if result.ok:
            warnings.append(f"CelesTrak was unavailable/insufficient; used provided local_file_path instead: "
                             f"{local_file_path}")
            return ResolvedSpaceWeather(Path(local_file_path), False, warnings)
        warnings.append(f"provided local_file_path also failed validation: {result.message}")

    path = _synthetic_cache_path(cache_dir, start_utc, end_utc)
    generate_synthetic(start_utc, end_utc, path)
    warnings.append(
        "FALLING BACK TO SYNTHETIC space weather: CelesTrak could not be reached or did not cover the "
        "scenario's date range, and no usable local_file_path was provided. This is NOT real observed/"
        "forecast data -- replace it with a real CelesTrak extract (or a valid local_file_path) once one "
        "covering this date range is available."
    )
    return ResolvedSpaceWeather(path, True, warnings)
