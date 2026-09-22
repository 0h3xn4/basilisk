"""Tests for missionstudio.engine.link_budget -- no Basilisk import, runs
anywhere; verifies against a hand-computed link budget and against the
free-space-path-loss identity (range up by 10x -> FSPL up by 20 dB ->
margin down by 20 dB) rather than a second copy of the same formula.
"""

import numpy as np
import pytest

from missionstudio.engine.link_budget import link_margin_db, link_margin_series
from missionstudio.engine.results import ResultSet, ResultsError, TimeSeries
from missionstudio.schema.scenario import GroundStationConfig, RFLinkConfig


def _rf_link(**overrides):
    defaults = dict(tx_power_w=15.0, frequency_hz=8.2e9, data_rate_bps=1.0e6,
                     tx_antenna_gain_dbi=6.0, implementation_loss_db=2.0, required_ebno_db=6.0)
    defaults.update(overrides)
    return RFLinkConfig(**defaults)


def _ground_station(**overrides):
    defaults = dict(name="gs1", latitude_deg=0.0, longitude_deg=0.0,
                     rx_antenna_gain_dbi=45.0, system_noise_temp_k=500.0)
    defaults.update(overrides)
    return GroundStationConfig(**defaults)


def test_link_margin_db_matches_hand_computed_value():
    # Independently computed (not copy-pasted from link_budget.py's own
    # expression): EIRP = 10*log10(15) + 6 - 2 = 15.761 dBW
    # FSPL @ 1000 km, 8.2 GHz = 20*log10(4*pi*1e6*8.2e9/299792458) = 170.724 dB
    # received = 15.761 - 170.724 + 45 = -109.963 dBW
    # N0 = -228.6 + 10*log10(500) = -201.610 dBW/Hz
    # C/N0 = -109.963 - (-201.610) = 91.647 dB-Hz
    # Eb/N0 = 91.647 - 10*log10(1e6) = 31.647 dB
    # margin = 31.647 - 6 = 25.647 dB
    margin = link_margin_db(1_000_000.0, _rf_link(), _ground_station())
    assert margin == pytest.approx(25.647, abs=0.01)


def test_link_margin_decreases_20db_per_decade_of_range():
    rf_link, gs = _rf_link(), _ground_station()
    margin_near = link_margin_db(1.0e6, rf_link, gs)
    margin_far = link_margin_db(1.0e7, rf_link, gs)
    assert margin_near - margin_far == pytest.approx(20.0, abs=1e-6)


def test_higher_tx_power_increases_margin_by_matching_db():
    rf_link_lo, gs = _rf_link(tx_power_w=10.0), _ground_station()
    rf_link_hi = _rf_link(tx_power_w=20.0)  # +3.01 dB
    delta = link_margin_db(1.0e6, rf_link_hi, gs) - link_margin_db(1.0e6, rf_link_lo, gs)
    assert delta == pytest.approx(10.0 * np.log10(2.0), abs=1e-9)


def _access_result(range_m, has_access, n=5):
    t = np.linspace(0.0, 100.0, n)
    result = ResultSet(scenario_name="test")
    result.add(TimeSeries("gs1.access_to_sat1.slant_range", t, ("slant_range",),
                           np.full((n, 1), range_m), units="m"))
    result.add(TimeSeries("gs1.access_to_sat1.has_access", t, ("has_access",),
                           np.array(has_access, dtype=float).reshape(-1, 1), units="-"))
    return result


def test_link_margin_series_only_defined_during_access():
    has_access = [0, 1, 1, 0, 0]
    result = _access_result(1.0e6, has_access)
    series = link_margin_series(result, "gs1", "sat1", _rf_link(), _ground_station())

    assert series.name == "gs1.access_to_sat1.link_margin_db"
    assert series.units == "dB"
    expected_margin = link_margin_db(1.0e6, _rf_link(), _ground_station())
    for i, accessible in enumerate(has_access):
        if accessible:
            assert series.data[i, 0] == pytest.approx(expected_margin)
        else:
            assert np.isnan(series.data[i, 0])


def test_link_margin_series_missing_pair_raises_clear_error():
    result = ResultSet(scenario_name="test")
    with pytest.raises(ResultsError, match="no access-analysis series found"):
        link_margin_series(result, "gs1", "sat1", _rf_link(), _ground_station())
