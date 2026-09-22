"""Tests for gui.kernel_status_widget.KernelStatusWidget.

This development sandbox genuinely has no Basilisk build, so
``test_refresh_without_basilisk_reports_clear_status`` below exercises the
REAL no-Basilisk path through an actual background QThread -- not a mock
of what that path "should" do.
"""

import importlib.util

import pytest

pytestmark = pytest.mark.requires_gui

_BASILISK_AVAILABLE = importlib.util.find_spec("Basilisk") is not None


@pytest.fixture
def widget(qtbot):
    from missionstudio.gui.kernel_status_widget import KernelStatusWidget

    w = KernelStatusWidget()
    qtbot.addWidget(w)
    return w


def test_initial_state(widget):
    assert "not checked" in widget.status_label.text()
    assert widget.table.rowCount() == 0


def test_refresh_disables_button_while_running(widget, qtbot):
    widget.refresh()
    assert not widget.refresh_button.isEnabled()
    qtbot.waitUntil(lambda: widget.refresh_button.isEnabled(), timeout=5000)


@pytest.mark.skipif(_BASILISK_AVAILABLE, reason="this test's premise is specifically that Basilisk is unavailable")
def test_refresh_without_basilisk_reports_clear_status(widget, qtbot):
    widget.refresh()
    qtbot.waitUntil(lambda: widget.refresh_button.isEnabled(), timeout=5000)
    assert "Basilisk is not installed" in widget.status_label.text()
    assert widget.table.rowCount() == 0
