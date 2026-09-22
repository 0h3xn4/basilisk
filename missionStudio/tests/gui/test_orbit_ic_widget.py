"""Tests for gui.orbit_ic_widget.OrbitIcWidget."""

import pytest

pytestmark = pytest.mark.requires_gui


@pytest.fixture
def widget(qtbot):
    from missionstudio.gui.orbit_ic_widget import OrbitIcWidget

    w = OrbitIcWidget()
    qtbot.addWidget(w)
    return w


def test_default_is_classical_elements(widget):
    oe = widget.to_dataclass()
    assert oe.type == "classical_elements"
    assert oe.semi_major_axis_km == 7000.0


def test_editing_a_field_emits_changed_and_updates_value(widget, qtbot):
    with qtbot.waitSignal(widget.changed, timeout=1000):
        widget.sma_km.setValue(8000.0)
    assert widget.to_dataclass().semi_major_axis_km == 8000.0


def test_switching_type_emits_changed_and_updates_dataclass(widget, qtbot):
    with qtbot.waitSignal(widget.changed, timeout=1000):
        widget.type_combo.setCurrentIndex(widget.type_combo.findData("cartesian"))
    cart = widget.to_dataclass()
    assert cart.type == "cartesian"
    assert cart.position_km == [7000.0, 0.0, 0.0]


@pytest.mark.parametrize("orbit_kwargs", [
    dict(type="classical_elements", semi_major_axis_km=6800.0, eccentricity=0.01,
         inclination_deg=45.0, raan_deg=10.0, arg_periapsis_deg=20.0, true_anomaly_deg=30.0),
    dict(type="cartesian", position_km=[1.0, 2.0, 3.0], velocity_km_s=[4.0, 5.0, 6.0]),
    dict(type="tle", tle_line1="1 25544U", tle_line2="2 25544"),
])
def test_from_dataclass_round_trips(widget, orbit_kwargs):
    from missionstudio.schema.scenario import OrbitIC

    orbit = OrbitIC(**orbit_kwargs)
    widget.from_dataclass(orbit)
    got = widget.to_dataclass()
    assert got == orbit


def test_from_dataclass_rejects_unknown_type(widget):
    from missionstudio.schema.scenario import OrbitIC

    with pytest.raises(ValueError, match="doesn't know orbit type"):
        widget.from_dataclass(OrbitIC(type="wormhole"))
