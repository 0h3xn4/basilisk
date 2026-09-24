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


def test_mid_palette_role_is_readable_not_left_at_qt_default(qapp):
    """Regression test for a real user report, with a screenshot: several
    widgets' own inline stylesheets use "color: palette(mid);" for muted
    hint/description text (see e.g. LoadScenarioWidget's template
    description) -- QPalette.Mid was never explicitly set, so it stayed
    at Qt's own computed default (a subtle 3D-bevel shading tone, not
    meant for body text), making that text unreadably low-contrast
    against this theme's light background. Must be mapped to the same
    text_muted this theme already uses for PlaceholderText, not left
    unset.
    """
    from PySide6.QtGui import QPalette

    from missionstudio.gui.theme import _C, apply_theme

    apply_theme(qapp)
    assert qapp.palette().color(QPalette.ColorRole.Mid).name() == _C["text_muted"].lower()


def test_apply_theme_is_idempotent(qapp):
    """Applying the theme twice (e.g. two MainWindow instances created in
    the same process, as tests here sometimes do) must not raise or leave
    the application in a broken state.
    """
    from missionstudio.gui.theme import apply_theme

    apply_theme(qapp)
    apply_theme(qapp)
    assert qapp.styleSheet().strip() != ""
