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

"""VizardDialog: lets the user turn Vizard on for the NEXT run, choosing
between the two modes ``engine.vizard.VizardRequest`` supports -- see that
module's docstring for what "live simulation data" means in each mode.
Does not import ``engine.vizard`` at module scope (no Basilisk import
needed to show this dialog -- the request is only handed to
``engine.vizard`` once a run actually starts, matching this app's general
"engine/ imports Basilisk, gui/ doesn't have to" split).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)


class VizardDialog(QDialog):
    """Modal "Enable Vizard" dialog. Construct with the current request (or
    ``None`` to start disabled); read back the new choice via
    :meth:`to_request` after ``exec()`` returns ``Accepted``.
    """

    def __init__(self, current_save_file: str | None = None, current_live_stream: bool = False,
                 current_camera_target: str | None = None, current_show_orbit_lines: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vizard visualization")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Vizard is a separate application and cannot be embedded here -- pick how this run "
            "feeds it. See missionStudio/README.md for how to open Vizard itself."
        ))

        self.disabled_radio = QRadioButton("Disabled (no Vizard output this run)")
        self.save_file_radio = QRadioButton("Write a .bin playback file to open in Vizard afterward")
        self.live_stream_radio = QRadioButton("Live-stream to a Vizard instance already running on this machine")
        layout.addWidget(self.disabled_radio)
        layout.addWidget(self.save_file_radio)

        save_file_row = QHBoxLayout()
        self.save_file_edit = QLineEdit(current_save_file or "")
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._on_browse)
        save_file_row.addWidget(self.save_file_edit)
        save_file_row.addWidget(self.browse_button)
        layout.addLayout(save_file_row)

        layout.addWidget(self.live_stream_radio)

        view_form = QFormLayout()
        self.camera_target_edit = QLineEdit(current_camera_target or "")
        self.camera_target_edit.setPlaceholderText("(default: central body -- Earth-centered view, like STK/GMAT/FreeFlyer)")
        view_form.addRow("Camera starts locked on", self.camera_target_edit)
        layout.addLayout(view_form)

        self.orbit_lines_check = QCheckBox("Show orbit trace lines")
        self.orbit_lines_check.setChecked(current_show_orbit_lines)
        layout.addWidget(self.orbit_lines_check)

        if current_live_stream:
            self.live_stream_radio.setChecked(True)
        elif current_save_file:
            self.save_file_radio.setChecked(True)
        else:
            self.disabled_radio.setChecked(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_browse(self) -> None:
        path_str, _selected_filter = QFileDialog.getSaveFileName(self, "Vizard playback file", "", "Vizard playback (*.bin)")
        if path_str:
            self.save_file_edit.setText(path_str)
            self.save_file_radio.setChecked(True)

    def _on_accept(self) -> None:
        if self.save_file_radio.isChecked() and not self.save_file_edit.text().strip():
            # Every other validation-on-accept in this app (dispersion/
            # ground-station/propagation-setup/constellation dialogs) tells
            # the user WHY OK didn't do anything via QMessageBox.critical --
            # this used to just move focus back to the empty field with no
            # explanation, which looks like a broken OK button rather than a
            # rejected, fixable input.
            QMessageBox.critical(self, "Playback file required",
                                  "Enter (or Browse... to) a .bin playback file path, or pick a different mode.")
            self.save_file_edit.setFocus()
            return
        self.accept()

    def to_request(self):
        """Returns an ``engine.vizard.VizardRequest``, or ``None`` if the
        user chose "Disabled". Imports ``engine.vizard`` lazily (see module
        docstring).
        """
        if self.disabled_radio.isChecked():
            return None
        from ..engine.vizard import VizardRequest

        camera_target = self.camera_target_edit.text().strip() or None
        show_orbit_lines = self.orbit_lines_check.isChecked()
        if self.live_stream_radio.isChecked():
            return VizardRequest(live_stream=True, camera_target=camera_target, show_orbit_lines=show_orbit_lines)
        return VizardRequest(save_file=self.save_file_edit.text().strip(),
                              camera_target=camera_target, show_orbit_lines=show_orbit_lines)
