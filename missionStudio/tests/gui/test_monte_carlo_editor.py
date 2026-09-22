"""Tests for gui.monte_carlo_editor."""

import pytest

pytestmark = pytest.mark.requires_gui


def test_group_default_state(qtbot):
    from missionstudio.gui.monte_carlo_editor import MonteCarloGroupWidget

    widget = MonteCarloGroupWidget()
    qtbot.addWidget(widget)
    config = widget.to_dataclass()
    assert config.enabled is False
    assert config.num_runs == 10
    assert config.thread_count == 1
    assert config.dispersions == []


def test_group_round_trip(qtbot):
    from missionstudio.gui.monte_carlo_editor import MonteCarloGroupWidget
    from missionstudio.schema.scenario import DispersionConfig, MonteCarloConfig

    widget = MonteCarloGroupWidget()
    qtbot.addWidget(widget)
    widget.set_spacecraft_names(["sat-1"])
    mc = MonteCarloConfig(
        enabled=True, num_runs=42, thread_count=3, verbose=True,
        dispersions=[DispersionConfig(spacecraft="sat-1", quantity="attitude_sigma_bn", kind="uniform_euler_mrp",
                                       bounds=[0.0, 6.28])],
    )
    widget.from_dataclass(mc)
    got = widget.to_dataclass()
    assert got.enabled is True
    assert got.num_runs == 42
    assert got.thread_count == 3
    assert got.verbose is True
    assert got.dispersions[0].quantity == "attitude_sigma_bn"
    assert got.dispersions[0].bounds == [0.0, 6.28]


def test_dispersion_dialog_uniform(qtbot):
    from missionstudio.gui.monte_carlo_editor import _DispersionEditorDialog

    dialog = _DispersionEditorDialog(["sat-1", "sat-2"])
    qtbot.addWidget(dialog)
    dialog.spacecraft_combo.setCurrentText("sat-2")
    dialog.quantity_combo.setCurrentText("dry_mass_kg")
    dialog.kind_combo.setCurrentText("uniform")
    dialog.bounds_lo_spin.setValue(90.0)
    dialog.bounds_hi_spin.setValue(110.0)

    config = dialog.to_dataclass()
    assert config.spacecraft == "sat-2"
    assert config.quantity == "dry_mass_kg"
    assert config.kind == "uniform"
    assert config.bounds == [90.0, 110.0]
    assert config.mean is None


def test_dispersion_dialog_normal(qtbot):
    from missionstudio.gui.monte_carlo_editor import _DispersionEditorDialog

    dialog = _DispersionEditorDialog(["sat-1"])
    qtbot.addWidget(dialog)
    dialog.quantity_combo.setCurrentText("dry_mass_kg")
    dialog.kind_combo.setCurrentText("normal")
    dialog.mean_spin.setValue(100.0)
    dialog.std_spin.setValue(5.0)

    config = dialog.to_dataclass()
    assert config.kind == "normal"
    assert config.mean == 100.0
    assert config.std_deviation == 5.0
    assert config.bounds is None


def test_dispersion_dialog_kind_choices_follow_quantity(qtbot):
    from missionstudio.gui.monte_carlo_editor import _DispersionEditorDialog

    dialog = _DispersionEditorDialog(["sat-1"])
    qtbot.addWidget(dialog)
    dialog.quantity_combo.setCurrentText("attitude_sigma_bn")
    kinds = [dialog.kind_combo.itemText(i) for i in range(dialog.kind_combo.count())]
    assert kinds == ["uniform_euler_mrp"]

    dialog.quantity_combo.setCurrentText("dry_mass_kg")
    kinds = [dialog.kind_combo.itemText(i) for i in range(dialog.kind_combo.count())]
    assert set(kinds) == {"uniform", "normal"}


def test_dispersion_dialog_rejects_when_no_spacecraft(qtbot):
    from missionstudio.gui.monte_carlo_editor import _DispersionEditorDialog

    dialog = _DispersionEditorDialog([])
    qtbot.addWidget(dialog)
    with pytest.raises(ValueError, match="no spacecraft"):
        dialog.to_dataclass()


def test_dispersion_list_add_edit_remove(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from missionstudio.gui.monte_carlo_editor import DispersionListWidget, _DispersionEditorDialog

    widget = DispersionListWidget()
    qtbot.addWidget(widget)
    widget.set_spacecraft_names(["sat-1"])

    def fake_exec(self):
        self.quantity_combo.setCurrentText("dry_mass_kg")
        self.kind_combo.setCurrentText("uniform")
        self.bounds_lo_spin.setValue(1.0)
        self.bounds_hi_spin.setValue(2.0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_DispersionEditorDialog, "exec", fake_exec)
    changed_count = []
    widget.changed.connect(lambda: changed_count.append(1))

    widget._on_add()
    assert len(widget.to_list()) == 1
    assert changed_count == [1]

    widget.list_widget.setCurrentRow(0)
    widget._on_edit()
    assert len(widget.to_list()) == 1

    widget.list_widget.setCurrentRow(0)
    widget._on_remove()
    assert widget.to_list() == []
