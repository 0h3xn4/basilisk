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

"""LoadScenarioWidget: the "Load Scenario" tab -- lets a user pick one of
missionStudio's built-in template missions (``missionstudio/scenarios/
templates/``, see that directory's own README and
``scripts/_generate_templates.py``) without needing to already know
where they're installed, or browse for any other scenario file. Built in
response to a direct request that the bundled templates be reachable
from inside the GUI itself, not just as files a user has to go find on
disk.

Deliberately thin: this widget only picks a *path* and emits it via
:attr:`path_chosen` -- ``MainWindow.open_path()`` does the actual
loading (``schema.scenario.load_scenario()`` plus its existing
unsaved-changes/error-message handling), so there is exactly one place
that knows how to open a scenario file, matching how every other
GUI-vs-``schema``/``engine`` split in this app works (see this module's
own class docstring).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import missionstudio

from ..schema import load_scenario

# Where scripts/_generate_templates.py writes the built-in templates, and
# where setuptools package-data (see pyproject.toml's own comment on
# this) copies them to in an installed wheel -- missionstudio.__file__ is
# <install>/missionstudio/__init__.py either way (a checkout or a real
# install), so this resolves correctly in both.
TEMPLATES_DIR = Path(missionstudio.__file__).resolve().parent / "scenarios" / "templates"

_FILE_FILTER = "missionStudio scenario (*.json)"


class LoadScenarioWidget(QWidget):
    path_chosen = Signal(object)  # pathlib.Path

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._template_paths: Dict[str, Path] = {}

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Start from one of missionStudio's built-in template missions -- each demonstrates one "
            "concept in isolation and is a good starting point for your own scenario (see the "
            "description below once one is selected) -- or browse for any other scenario file."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.description_label)

        button_row = QHBoxLayout()
        self.open_template_button = QPushButton("Open Template")
        self.open_template_button.setEnabled(False)
        self.open_template_button.clicked.connect(self._on_open_template_clicked)
        button_row.addWidget(self.open_template_button)
        self.browse_button = QPushButton("Browse for a file...")
        self.browse_button.clicked.connect(self._on_browse_clicked)
        button_row.addWidget(self.browse_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_open_template_clicked())

        self._populate_templates()

    def _populate_templates(self) -> None:
        if not TEMPLATES_DIR.is_dir():
            return
        for path in sorted(TEMPLATES_DIR.glob("*.json")):
            try:
                scenario = load_scenario(path)
            except Exception:  # noqa: BLE001 -- a malformed bundled template must never crash the GUI on open
                continue
            self._template_paths[scenario.name] = path
            item = QListWidgetItem(scenario.name)
            item.setData(Qt.ItemDataRole.UserRole, scenario.description)
            self.list_widget.addItem(item)

    def _on_selection_changed(self, current: Optional[QListWidgetItem], _previous) -> None:
        self.open_template_button.setEnabled(current is not None)
        self.description_label.setText(current.data(Qt.ItemDataRole.UserRole) if current is not None else "")

    def _on_open_template_clicked(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        path = self._template_paths.get(item.text())
        if path is not None:
            self.path_chosen.emit(path)

    def _on_browse_clicked(self) -> None:
        path_str, _selected_filter = QFileDialog.getOpenFileName(self, "Open scenario", "", _FILE_FILTER)
        if path_str:
            self.path_chosen.emit(Path(path_str))
