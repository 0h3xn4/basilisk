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

"""The application icon -- drawn procedurally with :class:`QPainter`
(a central body + an inclined orbit ellipse + a satellite dot on it,
matching ``theme.py``'s accent color) rather than shipped as a bitmap
asset, so there is no binary file to keep in sync with the theme and no
new packaging step (``packaging/build_wheel.sh``/the installer's
``.desktop`` entry already just point at whatever
:func:`app_icon`/:func:`window_icon_path` produce). Used as both the
``QApplication``/``QMainWindow`` window icon (see ``app.py``) and, cached
to a PNG on disk, the ``.desktop`` entry's ``Icon=`` target (see
``packaging/``) -- a ``.desktop`` file needs a real file path, not an
in-memory ``QIcon``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPen, QPixmap

_ACCENT = "#3457D5"
_ACCENT_DARK = "#243C99"
_BODY = "#1F2530"


def _ensure_application() -> None:
    """``QPixmap``/``QPainter`` need a ``QGuiApplication`` instance to
    already exist in the process -- constructing one before it does is a
    silent no-op in Qt (a stderr warning, not a raised exception): the
    resulting pixmap is null and ``.save()`` just returns ``False``, so a
    caller that doesn't check that return value (``app_icon()`` doesn't;
    :func:`ensure_icon_file` does, see below) would appear to succeed
    while producing nothing. Every caller in THIS module runs inside
    ``gui/app.py``'s already-running ``QApplication`` except
    ``packaging/install.sh``'s standalone icon-render step, which imports
    only this module -- so this constructs a minimal, display-less
    ``QGuiApplication`` there rather than trusting every future call site
    to remember to.
    """
    if QGuiApplication.instance() is None:
        QGuiApplication([])


def _render(size: int) -> QPixmap:
    _ensure_application()
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    center = QPointF(size / 2.0, size / 2.0)

    # Central body.
    body_radius = size * 0.20
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_BODY))
    painter.drawEllipse(center, body_radius, body_radius)

    # Inclined orbit ellipse (rotated ~20 degrees for a dynamic, "in
    # motion" look rather than a flat static ring).
    painter.save()
    painter.translate(center)
    painter.rotate(-20.0)
    orbit_rect = QRectF(-size * 0.44, -size * 0.24, size * 0.88, size * 0.48)
    # A fresh QPen, not painter.pen() -- that would inherit NoPen's style
    # from the central-body fill above (setColor()/setWidthF() only
    # change a pen's color/width, never its style, so the ring drew
    # nothing at all until this was caught by actually rendering the icon
    # and looking at it rather than trusting the code alone).
    pen = QPen(QColor(_ACCENT))
    pen.setWidthF(size * 0.045)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(orbit_rect)

    # Satellite dot, on the orbit ellipse.
    sat_radius = size * 0.075
    sat_point = QPointF(orbit_rect.right(), 0.0)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_ACCENT_DARK))
    painter.drawEllipse(sat_point, sat_radius, sat_radius)
    painter.restore()

    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """A multi-resolution :class:`QIcon` -- Qt picks the best size for
    each context (window titlebar, taskbar, alt-tab switcher, ...) from
    whichever sizes are registered.
    """
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render(size))
    return icon


def ensure_icon_file(path: "str | Path", size: int = 256) -> Path:
    """Renders the icon to a PNG at ``path`` (creating parent directories
    as needed) if it doesn't already exist, and returns the path. Used by
    ``packaging/`` for the ``.desktop`` entry's ``Icon=`` target, which
    needs a real file, not an in-memory :class:`QIcon`.

    Raises :class:`OSError` if the render/save fails (e.g. no usable Qt
    platform plugin) -- ``QPixmap.save()`` only returns ``False`` on
    failure rather than raising, which would otherwise let
    ``install.sh``'s calling ``python3 -c ...`` exit 0 having silently
    written nothing, and its shell ``if`` guard report success anyway.
    """
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not _render(size).save(str(path), "PNG"):
            raise OSError(f"could not render/save the app icon to {path}")
    return path
