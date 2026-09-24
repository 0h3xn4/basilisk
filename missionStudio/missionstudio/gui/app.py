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

"""GUI entry point. Launch with ``python3 -m missionstudio.gui.app``, or
via ``missionstudio gui`` (see ``../cli.py``).
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ..logging_setup import configure_logging
from .icons import app_icon
from .main_window import MainWindow
from .theme import apply_theme


def main(argv: list | None = None) -> int:
    # First thing, before anything else can fail -- see logging_setup's
    # own module docstring for why (direct user feedback: a crash whose
    # only information anywhere was one bare line in a GUI error dialog).
    configure_logging()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("missionStudio")
    # Needed for QSettings() (used by gui.vizard_launcher to remember a
    # user-picked Vizard executable path) to resolve to a stable
    # per-platform location -- QSettings() with no explicit org/app name
    # falls back to whatever these two are set to.
    app.setOrganizationName("AVSLab")
    apply_theme(app)
    icon = app_icon()
    app.setWindowIcon(icon)
    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
