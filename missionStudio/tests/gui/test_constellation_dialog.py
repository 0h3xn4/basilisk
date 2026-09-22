"""Tests for gui.constellation_dialog.WalkerConstellationDialog."""

import pytest

pytestmark = pytest.mark.requires_gui


def test_defaults_produce_a_valid_request(qtbot):
    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog

    dialog = WalkerConstellationDialog(template_names=["sat-1"], central_body="earth")
    qtbot.addWidget(dialog)
    request = dialog.to_request()
    assert request.central_body == "earth"
    assert request.total_satellites > 0
    assert dialog.selected_template_name() == "sat-1"


def test_central_body_is_not_independently_selectable(qtbot):
    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog

    dialog = WalkerConstellationDialog(template_names=[], central_body="mars")
    qtbot.addWidget(dialog)
    assert dialog.to_request().central_body == "mars"


def test_empty_template_list_disables_combo_and_returns_none(qtbot):
    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog

    dialog = WalkerConstellationDialog(template_names=[])
    qtbot.addWidget(dialog)
    assert not dialog.template_combo.isEnabled()
    assert dialog.selected_template_name() is None


def test_editing_fields_updates_request(qtbot):
    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog

    dialog = WalkerConstellationDialog(template_names=["sat-1"])
    qtbot.addWidget(dialog)
    dialog.total_satellites.setValue(6)
    dialog.num_planes.setValue(2)
    dialog.phasing_factor.setValue(1)
    dialog.altitude_km.setValue(600.0)
    dialog.inclination_deg.setValue(51.6)
    dialog.name_prefix_edit.setText("iridium")

    request = dialog.to_request()
    assert request.total_satellites == 6
    assert request.num_planes == 2
    assert request.phasing_factor == 1
    assert request.altitude_km == 600.0
    assert request.inclination_deg == 51.6
    assert request.name_prefix == "iridium"


def test_accept_blocked_on_invalid_request(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox

    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    dialog = WalkerConstellationDialog(template_names=["sat-1"])
    qtbot.addWidget(dialog)
    dialog.total_satellites.setValue(10)
    dialog.num_planes.setValue(3)  # 10 not evenly divisible by 3
    dialog._on_accept()
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_pattern_combo_offers_delta_and_star(qtbot):
    from missionstudio.gui.constellation_dialog import WalkerConstellationDialog

    dialog = WalkerConstellationDialog(template_names=["sat-1"])
    qtbot.addWidget(dialog)
    patterns = {dialog.pattern_combo.itemData(i) for i in range(dialog.pattern_combo.count())}
    assert patterns == {"delta", "star"}
