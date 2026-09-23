"""Tests for gui.theme."""

import pytest

pytestmark = pytest.mark.requires_gui


def test_apply_theme_runs_without_error(qapp):
    from PySide6.QtGui import QPalette

    from missionstudio.gui.theme import _C, apply_theme

    apply_theme(qapp)
    assert qapp.styleSheet().strip() != ""
    # The palette's actual colors are the meaningful, stable thing to
    # check here -- app.style()'s runtime class hierarchy changes once a
    # stylesheet is active (Qt wraps the base style in a QStyleSheetStyle
    # proxy) and isn't a reliable signal to assert on.
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == _C["bg"].lower()
    assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == _C["accent"].lower()


def test_apply_theme_is_idempotent(qapp):
    """Applying the theme twice (e.g. two MainWindow instances created in
    the same process, as tests here sometimes do) must not raise or leave
    the application in a broken state.
    """
    from missionstudio.gui.theme import apply_theme

    apply_theme(qapp)
    apply_theme(qapp)
    assert qapp.styleSheet().strip() != ""
