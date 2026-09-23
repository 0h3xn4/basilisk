"""Tests for gui.icons."""

import pytest

pytestmark = pytest.mark.requires_gui


def test_app_icon_returns_a_non_null_icon(qapp):
    from missionstudio.gui.icons import app_icon

    icon = app_icon()
    assert not icon.isNull()
    assert len(icon.availableSizes()) > 0


def test_app_icon_pixmap_is_not_blank(qapp):
    """Regression test: an earlier version of the icon-drawing code
    reused ``painter.pen()`` for the orbit ring after having just set
    ``Qt.PenStyle.NoPen`` for the central body -- setColor()/setWidthF()
    don't change a pen's STYLE, so the ring silently never drew, and only
    the two dots rendered. Checking for more than 2 distinct non
    -transparent colors catches that class of bug without pinning down
    exact pixel values (which would break on any legitimate color tweak).
    """
    from PySide6.QtGui import QColor

    from missionstudio.gui.icons import _render

    pixmap = _render(64)
    image = pixmap.toImage()
    colors = set()
    for x in range(0, image.width(), 2):
        for y in range(0, image.height(), 2):
            pixel = QColor(image.pixel(x, y))
            if pixel.alpha() > 0:
                colors.add((pixel.red(), pixel.green(), pixel.blue()))
    assert len(colors) >= 3, f"expected at least 3 distinct colors (body/ring/satellite), got {colors}"


def test_ensure_icon_file_creates_a_real_png(qapp, tmp_path):
    from missionstudio.gui.icons import ensure_icon_file

    target = tmp_path / "icons" / "missionstudio.png"
    result = ensure_icon_file(target)

    assert result == target
    assert target.exists()
    assert target.stat().st_size > 0
    assert target.read_bytes().startswith(b"\x89PNG")


def test_ensure_icon_file_does_not_overwrite_an_existing_file(qapp, tmp_path):
    from missionstudio.gui.icons import ensure_icon_file

    target = tmp_path / "missionstudio.png"
    target.write_bytes(b"not a real png, just a marker")

    result = ensure_icon_file(target)

    assert result == target
    assert target.read_bytes() == b"not a real png, just a marker"
