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

"""Locating and launching the external Vizard application -- a separate,
non-Python Unity app (see ``docs/source/Vizard/VizardDownload.rst`` in
this checkout) that is NOT bundled with or installable via missionStudio.
This module only starts the standalone process and hands back a way to
tell whether it's still running; actually feeding it simulation data (a
playback ``.bin`` file or a live stream) is ``engine.vizard``'s job,
wired through ``SimulationService`` via ``gui.vizard_dialog.VizardRequest``
-- entirely separate from starting the app itself.

Vizard's own download instructions say only "install the program in the
typical Applications folder or Desktop" -- there's no single guaranteed
install path, so :func:`find_vizard_executable` is inherently best
-effort: it checks a remembered path from a previous
:func:`remember_vizard_executable` call first (an exact answer the user
already gave us), then falls back to guessing a small set of common
per-OS install locations, and returns ``None`` if neither turns up
anything -- at which point the caller (``gui.vizard_status_widget``) asks
the user to browse for it once.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QSettings

_SETTINGS_KEY = "vizard/executable_path"

# engine.vizard/SimulationService never overrides vizInterface's own
# reqComProtocol="tcp"/reqComAddress="0.0.0.0"/reqPortNumber="5556"
# defaults (see docs/source/Vizard/vizardAdvanced/vizardLiveComm.rst) --
# "0.0.0.0" binds to all interfaces but is reachable locally via
# "localhost", so this is the address a live-stream run's Vizard
# instance actually needs to connect to. Passed to :func:`launch_vizard`
# as its ``-directComm`` command-line argument (see
# docs/source/Vizard/vizardAdvanced/vizardCommandLine.rst) so Vizard
# connects automatically instead of sitting on its own manual "Load Data
# Using One of the Following" launcher screen waiting for the user to
# type this address in by hand and click "Start Visualization" --
# direct user feedback: a live-stream run appeared to "do nothing" and
# then froze with Abort having no effect, because Basilisk's
# InitializeSimulation() blocks (inside native C++, no Python-level
# hook -- see gui.main_window.MainWindow.on_run()'s own comment) waiting
# for exactly that handshake, which never arrived.
DEFAULT_LIVE_STREAM_ADDRESS = "tcp://localhost:5556"

# The actual launchable binary/bundle name Vizard's own Unity build
# produces per platform (see VizardDownload.rst's Vizard_<platform>.zip
# contents) -- used to search candidate directories.
if sys.platform == "darwin":
    _EXECUTABLE_NAME = "Vizard.app"
elif sys.platform.startswith("win"):
    _EXECUTABLE_NAME = "Vizard.exe"
else:
    _EXECUTABLE_NAME = "Vizard.x86_64"


def _candidate_roots() -> List[Path]:
    """Best-effort per-OS locations to search, per VizardDownload.rst's
    own "install in the typical Applications folder or Desktop" guidance
    -- there's no single guaranteed location since Vizard ships as a
    .zip the user extracts wherever they like.
    """
    home = Path.home()
    if sys.platform == "darwin":
        return [Path("/Applications"), home / "Applications", home / "Desktop", home / "Downloads"]
    if sys.platform.startswith("win"):
        return [
            Path("C:/Program Files"), Path("C:/Program Files (x86)"),
            home / "Desktop", home / "Downloads", home,
        ]
    return [home / "Desktop", home / "Downloads", home]


def _search_candidate_roots() -> Optional[Path]:
    for root in _candidate_roots():
        if not root.is_dir():
            continue
        # Shallow search: the root itself, plus one level of
        # subdirectories -- covers both "unzipped straight into Desktop"
        # and "unzipped into its own Vizard/ or Vizard_Windows64/
        # subfolder", without an unbounded recursive walk of e.g. the
        # user's whole home directory.
        for candidate in (root / _EXECUTABLE_NAME, *sorted(root.glob(f"*/{_EXECUTABLE_NAME}"))):
            if candidate.exists():
                return candidate
    return None


def find_vizard_executable(settings: Optional[QSettings] = None) -> Optional[Path]:
    """Returns a path to the Vizard executable/app bundle, or ``None`` if
    it can't be found automatically.
    """
    settings = settings if settings is not None else QSettings()
    remembered = settings.value(_SETTINGS_KEY, "", type=str)
    if remembered:
        path = Path(remembered)
        if path.exists():
            return path
    return _search_candidate_roots()


def remember_vizard_executable(path: Path, settings: Optional[QSettings] = None) -> None:
    """Persists ``path`` so the next :func:`find_vizard_executable` call
    (in this run or a future one) returns it directly, without needing to
    guess or ask the user again.
    """
    settings = settings if settings is not None else QSettings()
    settings.setValue(_SETTINGS_KEY, str(path))


def launch_vizard(executable_path: Path, direct_comm_address: Optional[str] = None) -> "subprocess.Popen[bytes]":
    """Starts Vizard as a background process and returns the
    :class:`subprocess.Popen` handle so the caller can poll whether it's
    still running (``.poll() is None``). On macOS this resolves an
    ``.app`` bundle to its actual Mach-O binary inside
    ``Contents/MacOS/`` first -- ``Popen`` can't launch a bundle
    directory itself, only a real executable file, and using the ``open``
    command instead would lose the process handle (``open`` exits
    immediately after handing off to the app, so there would be nothing
    left to poll).

    Args:
        direct_comm_address: when given (typically
            :data:`DEFAULT_LIVE_STREAM_ADDRESS`), passed as Vizard's own
            ``-directComm <address>`` command-line argument (see
            ``docs/source/Vizard/vizardAdvanced/vizardCommandLine.rst``)
            so it connects to a live-stream automatically instead of
            sitting on its manual launcher screen -- see this module's
            own ``DEFAULT_LIVE_STREAM_ADDRESS`` comment for why. ``None``
            (the default) launches Vizard with no arguments, exactly as
            before.
    """
    if sys.platform == "darwin" and executable_path.suffix == ".app":
        macos_dir = executable_path / "Contents" / "MacOS"
        binaries = [p for p in macos_dir.glob("*") if p.is_file()]
        if not binaries:
            raise FileNotFoundError(
                f"{executable_path} does not look like a valid macOS app bundle "
                f"(no executable found in {macos_dir})"
            )
        executable_path = binaries[0]
    args = [str(executable_path)]
    if direct_comm_address:
        args += ["-directComm", direct_comm_address]
    return subprocess.Popen(args)
