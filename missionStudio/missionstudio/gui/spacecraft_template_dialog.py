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

"""SpacecraftTemplateDialog: pick one of
:data:`engine.spacecraft_templates.SPACECRAFT_TEMPLATES` by name, with its
description shown alongside. Does not import
``engine.spacecraft_templates`` beyond the template list/dataclass itself
-- no Basilisk anywhere in that chain (see that module's docstring),
consistent with this project's "gui/ doesn't need to know engine/ imports
Basilisk" split used elsewhere (e.g. ``constellation_dialog.py``).

Only collects the CHOICE -- :meth:`selected_template`'s ``.build()``
still needs calling by the caller (``gui.spacecraft_editor.
SpacecraftListWidget._on_new_from_template``), which then opens the
ordinary :class:`SpacecraftEditorDialog` on the built config so the user
sets the actual name/orbit/anything else there, same as "Add..."/"Edit...".
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..engine.spacecraft_templates import SPACECRAFT_TEMPLATES, SpacecraftTemplate


class SpacecraftTemplateDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New spacecraft from template")
        self.resize(520, 320)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Start a new spacecraft from a physically-reasonable preset instead of a blank default -- "
            "you can adjust everything (including the orbit) in the editor that opens next."
        ))

        body = QHBoxLayout()
        self.list_widget = QListWidget()
        for template in SPACECRAFT_TEMPLATES:
            self.list_widget.addItem(QListWidgetItem(template.name))
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        body.addWidget(self.list_widget, stretch=1)

        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet("color: palette(mid);")
        body.addWidget(self.description_label, stretch=1)
        layout.addLayout(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if SPACECRAFT_TEMPLATES:
            self.list_widget.setCurrentRow(0)

    def _on_selection_changed(self, row: int) -> None:
        if 0 <= row < len(SPACECRAFT_TEMPLATES):
            self.description_label.setText(SPACECRAFT_TEMPLATES[row].description)
        else:
            self.description_label.setText("")

    def selected_template(self) -> "SpacecraftTemplate | None":
        row = self.list_widget.currentRow()
        if 0 <= row < len(SPACECRAFT_TEMPLATES):
            return SPACECRAFT_TEMPLATES[row]
        return None
