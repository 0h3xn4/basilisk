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
Downlink RF link-margin ESTIMATE: a simplified free-space-path-loss Eb/N0
budget, ported directly from ``../missionAnalysis``'s
``run_constellation_mission.py::_rf_link_margin_db()`` -- no
atmosphere/rain/pointing-loss/coding-gain terms, just EIRP - FSPL + G/T
against the required Eb/N0 for the assumed data rate. See
``schema.scenario.RFLinkConfig``'s docstring for what this does and does
NOT feed into.

This module has NO Basilisk import and is fully unit-testable here with
synthetic data -- it only consumes the already-recorded ``slant_range``/
``has_access`` :class:`~engine.results.TimeSeries` that
``engine.service.SimulationService.run()`` produces for every ground
-station/spacecraft pair from Basilisk's real, simulated orbit geometry
(``groundLocation.GroundLocation``); this module never computes geometry
itself.
"""

from __future__ import annotations

import numpy as np

from ..schema.scenario import GroundStationConfig, RFLinkConfig
from .results import ResultSet, ResultsError, TimeSeries

_C_LIGHT_M_S = 299792458.0  # [m/s]
_K_BOLTZMANN_DBW_HZ = -228.6  # [dBW/K/Hz] 10*log10(1.380649e-23)


def link_margin_db(range_m: float, rf_link: RFLinkConfig, ground_station: GroundStationConfig) -> float:
    """Downlink Eb/N0 margin [dB] at the given slant range: positive means
    the link closes with that much margin to spare; negative means it
    doesn't close at that range with these parameters.
    """
    eirp_dbw = 10.0 * np.log10(rf_link.tx_power_w) + rf_link.tx_antenna_gain_dbi - rf_link.implementation_loss_db
    fspl_db = 20.0 * np.log10(4.0 * np.pi * range_m * rf_link.frequency_hz / _C_LIGHT_M_S)
    received_dbw = eirp_dbw - fspl_db + ground_station.rx_antenna_gain_dbi
    n0_dbw_hz = _K_BOLTZMANN_DBW_HZ + 10.0 * np.log10(ground_station.system_noise_temp_k)
    cn0_db_hz = received_dbw - n0_dbw_hz
    ebno_db = cn0_db_hz - 10.0 * np.log10(rf_link.data_rate_bps)
    return float(ebno_db - rf_link.required_ebno_db)


def link_margin_series(result: ResultSet, ground_station_name: str, spacecraft_name: str,
                        rf_link: RFLinkConfig, ground_station: GroundStationConfig) -> TimeSeries:
    """Builds a ``"<gs>.access_to_<sc>.link_margin_db"`` :class:`TimeSeries`
    from that pair's already-recorded ``slant_range``/``has_access`` series
    (see ``engine.service.SimulationService.run()``'s access-analysis
    wiring). The margin is only defined while ``has_access`` is true --
    there is no link (and so no meaningful margin) outside an access
    window, so those samples are ``NaN`` rather than a misleadingly large
    negative number.
    """
    prefix = f"{ground_station_name}.access_to_{spacecraft_name}"
    range_series = result.series.get(f"{prefix}.slant_range")
    access_series = result.series.get(f"{prefix}.has_access")
    if range_series is None or access_series is None:
        raise ResultsError(
            f"no access-analysis series found for ground station {ground_station_name!r} / spacecraft "
            f"{spacecraft_name!r} -- was this pair actually simulated? (expected "
            f"{prefix}.slant_range/{prefix}.has_access in result.series)"
        )

    margin_db = np.full(len(range_series.time_s), np.nan)
    has_access = access_series.data[:, 0] > 0.5
    for i in np.nonzero(has_access)[0]:
        margin_db[i] = link_margin_db(float(range_series.data[i, 0]), rf_link, ground_station)

    return TimeSeries(f"{prefix}.link_margin_db", range_series.time_s, ("link_margin_db",),
                       margin_db.reshape(-1, 1), units="dB")
