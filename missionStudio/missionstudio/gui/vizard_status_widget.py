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

"""VizardStatusWidget: the "Vizard" tab in ``MainWindow.right_tabs`` --
shows whether the external Vizard application is currently running and
lets the user launch/relaunch it. Selecting this tab auto-launches
Vizard if it isn't already running (see ``MainWindow``'s
``right_tabs.currentChanged`` wiring, in response to "when clicking on
the Vizard tab, I want Vizard to start"); the Launch/Relaunch button
does the same thing on demand -- e.g. after the user closed Vizard
themselves, or right after browsing for its executable for the first
time.

This widget only starts the external process -- it does not feed it
data. See ``gui/vizard_dialog.py`` (the Run menu's "Vizard..." action)
for enabling a playback file / live stream on the next simulation run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .vizard_launcher import find_vizard_executable, launch_vizard, remember_vizard_executable


class VizardStatusWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._process = None  # subprocess.Popen, or None if never launched (or it has since exited)
        self._last_known_executable: Optional[Path] = find_vizard_executable()

        layout = QVBoxLayout(self)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.launch_button = QPushButton("Launch Vizard")
        self.launch_button.clicked.connect(self._on_launch_clicked)
        button_row.addWidget(self.launch_button)
        self.browse_button = QPushButton("Browse for Vizard...")
        self.browse_button.setToolTip("Point at Vizard's executable/app once -- missionStudio remembers your choice.")
        self.browse_button.clicked.connect(self._on_browse_clicked)
        button_row.addWidget(self.browse_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)

        # Popen gives no signal/callback for a child exiting, only
        # poll()/wait() -- this timer polls it so the status label/button
        # re-enable promptly if the user closes Vizard themselves rather
        # than staying stuck on "running" until something else happens to
        # refresh it. Cheap: a plain poll() syscall, no filesystem search.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_tick)
        self._poll_timer.start()

        self._update_display()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def ensure_launched(self) -> None:
        """Launches Vizard if it isn't already running -- a no-op
        otherwise. This is what selecting the Vizard tab calls; explicit
        clicks on the Launch button go through :meth:`_launch` directly
        since a user-visible "Relaunch" click should always actually
        relaunch, not silently no-op just because a previous process
        handle is (perhaps wrongly) still considered live.
        """
        if self.is_running():
            return
        self._launch()

    def _launch(self) -> None:
        executable = find_vizard_executable()
        self._last_known_executable = executable
        if executable is None:
            self._update_display()
            return
        try:
            self._process = launch_vizard(executable)
        except OSError as exc:
            QMessageBox.critical(self, "Could not launch Vizard", f"{executable}: {exc}")
            self._process = None
        self._update_display()

    def _on_launch_clicked(self) -> None:
        self._launch()

    def _on_browse_clicked(self) -> None:
        path_str, _selected_filter = QFileDialog.getOpenFileName(self, "Locate the Vizard application")
        if not path_str:
            return
        remember_vizard_executable(Path(path_str))
        self._launch()

    def _poll_tick(self) -> None:
        if self._process is not None and self._process.poll() is not None:
            self._process = None
            self._update_display()

    def _update_display(self) -> None:
        if self.is_running():
            self.status_label.setText(f"Vizard is running (PID {self._process.pid}).")
            self.launch_button.setText("Relaunch Vizard")
        elif self._last_known_executable is not None:
            self.status_label.setText(f"Vizard is not running. Found at: {self._last_known_executable}")
            self.launch_button.setText("Launch Vizard")
        else:
            self.status_label.setText(
                "Vizard was not found in any common install location. Use \"Browse for Vizard...\" "
                "below to point at it once -- missionStudio will remember your choice."
            )
            self.launch_button.setText("Launch Vizard")
