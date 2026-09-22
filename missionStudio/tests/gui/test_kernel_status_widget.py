"""Tests for gui.kernel_status_widget.KernelStatusWidget.

This development sandbox genuinely has no Basilisk build, so
``test_refresh_without_basilisk_reports_clear_status`` below exercises the
REAL no-Basilisk path through an actual background QThread -- not a mock
of what that path "should" do.

``test_refresh_disables_button_while_running`` mocks the worker's ``run()``
instead: a REAL kernel fetch is a genuine network call (``engine.kernels.
ensure_kernels()``), and on a machine that DOES have Basilisk but a slow or
blocked network, that call can take far longer than any reasonable test
timeout -- confirmed directly: running this suite against a real Basilisk
install in an environment that blocks the NAIF kernel host, the un-mocked
version of this test genuinely timed out past 5 seconds (pooch's retry
-with-backoff loop across two kernels-and-mirrors). The button's disable
-then-re-enable behavior is what this test is actually about, so it's
verified with a fast, deterministic stand-in for the worker's real body,
independent of Basilisk's availability or the network's.
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


def test_refresh_disables_button_while_running(widget, qtbot, monkeypatch):
    from missionstudio.gui.kernel_status_widget import _KernelFetchWorker

    monkeypatch.setattr(_KernelFetchWorker, "run", lambda self: self.finished_ok.emit([]))

    widget.refresh()
    assert not widget.refresh_button.isEnabled()
    qtbot.waitUntil(lambda: widget.refresh_button.isEnabled(), timeout=5000)


@pytest.mark.skipif(_BASILISK_AVAILABLE, reason="this test's premise is specifically that Basilisk is unavailable")
def test_refresh_without_basilisk_reports_clear_status(widget, qtbot):
    widget.refresh()
    qtbot.waitUntil(lambda: widget.refresh_button.isEnabled(), timeout=5000)
    assert "Basilisk is not installed" in widget.status_label.text()
    assert widget.table.rowCount() == 0
