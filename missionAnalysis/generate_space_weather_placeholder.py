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
Generate a PLACEHOLDER multi-year solar-activity (F10.7 / Ap) table in the
CelesTrak CSV column layout consumed by Basilisk's ``spaceWeatherData``
module (which in turn drives ``msisAtmosphere`` for atmospheric drag).

Why a placeholder is needed
----------------------------
``spaceWeatherData`` is built to load real observed/forecast data from
CelesTrak (``SW-Last5Years.csv`` / ``SW-All.csv``). Those files only cover the
past plus a short (~1 year) predicted window, and the loader deliberately
stops parsing at the first row missing Ap values (the monthly-prediction
tail), so they cannot cover a mission that starts more than ~1 year out and
runs for 5 more years (2028-10-01 through 2033-10-01, as of this writing).
There is no way to get "real" multi-year solar activity that far in the
future -- only a synthetic profile that is at least shaped like a real solar
cycle (smooth ~11-year modulation, day-to-day persistence, occasional
storms), which is what this script produces.

Replace the generated CSV with a real CelesTrak download (trimmed/extended as
needed) once the mission gets close enough to launch that forecast data
actually covers the operational window.

Usage::

    python3 generate_space_weather_placeholder.py

writes ``data/placeholder_space_weather.csv``.
"""

import os
from datetime import datetime, timedelta

import numpy as np

import mission_config as mc

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "placeholder_space_weather.csv")

# Pad a few days on each side: msisAtmosphere/spaceWeatherData need a short
# look-back window (current day + 3 prior days) and this keeps the very first
# and last simulated days safely inside the table.
PAD_DAYS = 10
RANDOM_SEED = 42

# Synthetic ~11-year solar-cycle envelope. Not tied to any actual Cycle 25/26
# forecast -- purely a plausible, smoothly-varying placeholder shape.
F107_SOLAR_MIN = 70.0  # [sfu]
F107_SOLAR_MAX = 150.0  # [sfu]
CYCLE_PERIOD_DAYS = 11.0 * 365.25  # [day]
CYCLE_PHASE_DAYS = -2.0 * 365.25  # [day] offset so the window opens past a cycle max, declining


def _f107_base(day_index: np.ndarray) -> np.ndarray:
    """Smooth solar-cycle-like F10.7 base level [sfu] vs. day index."""
    phase = 2.0 * np.pi * (day_index + CYCLE_PHASE_DAYS) / CYCLE_PERIOD_DAYS
    midpoint = 0.5 * (F107_SOLAR_MAX + F107_SOLAR_MIN)
    amplitude = 0.5 * (F107_SOLAR_MAX - F107_SOLAR_MIN)
    return midpoint + amplitude * np.cos(phase)


def generate(start_utc: datetime, end_utc: datetime, seed: int = RANDOM_SEED):
    rng = np.random.default_rng(seed)

    start = start_utc - timedelta(days=PAD_DAYS)
    end = end_utc + timedelta(days=PAD_DAYS)
    n_days = (end - start).days + 1
    dates = [start + timedelta(days=i) for i in range(n_days)]
    day_index = np.arange(n_days, dtype=float)

    f107_base = _f107_base(day_index)

    # Day-to-day F10.7 noise: smoothed random walk (AR(1)-like) so consecutive
    # days are correlated, as real F10.7 is.
    noise = np.zeros(n_days)
    for i in range(1, n_days):
        noise[i] = 0.85 * noise[i - 1] + rng.normal(0.0, 3.0)
    f107_obs = np.clip(f107_base + noise, 65.0, 300.0)  # [sfu]

    # Centered 81-day running mean (matches the F10.7_OBS_CENTER81 column
    # meaning); edges just use whatever window is available.
    f107_center81 = np.array(
        [
            f107_obs[max(0, i - 40) : min(n_days, i + 41)].mean()
            for i in range(n_days)
        ]
    )

    # Daily Ap: mostly quiet (4-15) with occasional storm episodes (Poisson
    # -triggered multi-day elevated-Ap events), loosely modulated by solar
    # activity level (more storms nearer solar max).
    ap_avg = np.zeros(n_days)
    storm_prob = 0.02 + 0.03 * (f107_base - F107_SOLAR_MIN) / (F107_SOLAR_MAX - F107_SOLAR_MIN)
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

    # Split each day's Ap average into 8 three-hour bins with mild scatter
    # around the daily average (kept non-negative).
    ap_3hr = np.clip(
        ap_avg[:, None] + rng.normal(0.0, 2.0, size=(n_days, 8)), 0.0, None
    )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    header = (
        "DATE,AP1,AP2,AP3,AP4,AP5,AP6,AP7,AP8,AP_AVG,"
        "F10.7_OBS,F10.7_OBS_CENTER81"
    )
    with open(OUTPUT_PATH, "w") as f:
        f.write(header + "\n")
        for i, d in enumerate(dates):
            row = [d.strftime("%Y-%m-%d")]
            row += [f"{v:.1f}" for v in ap_3hr[i]]
            row += [f"{ap_avg[i]:.1f}"]
            row += [f"{f107_obs[i]:.1f}", f"{f107_center81[i]:.1f}"]
            f.write(",".join(row) + "\n")

    return OUTPUT_PATH, n_days


if __name__ == "__main__":
    path, n_days = generate(mc.EPOCH_UTC, mc.MISSION_END_UTC)
    print(f"Wrote {n_days} days of PLACEHOLDER space-weather data to {path}")
    print("Replace with a real CelesTrak SW-All.csv extract once the mission is close to launch.")
