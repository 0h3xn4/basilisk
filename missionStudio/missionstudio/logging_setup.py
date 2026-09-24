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

"""Direct user feedback, after a crash this project's own error-reporting
turned out to have no way to actually diagnose: "would be good if you
could add some kind of debug mode, that outputs everything that happens
in the terminal and also saves it in a log file."

Root problem this fixes: every background worker (``gui.run_worker.
RunWorker``/``MonteCarloWorker``, ``gui.kernel_status_widget``'s own
worker) catches literally any exception and reports it to the GUI as
``str(exc)`` only -- exactly matching this project's own "never crash
the worker thread silently, always report a specific message" design
(see each catch site's own comment). That design is right for what the
USER sees (a real error, not a frozen/crashed app), but it throws away
the one thing actually needed to debug a genuinely unexpected failure --
which Python call site the exception came from, and (via
``traceback.format_exc()``) everything between there and where it was
caught. For an exception whose ``str()`` is just a bare C++ message with
no further context (e.g. a raw ``std::bad_alloc``/``basic_string::
_M_create`` crossing the SWIG boundary from Basilisk's own C++ layer --
see ``engine.orbit_maintenance``'s and ``engine.service.
_osculating_elements``'s own docstrings for two real examples), that
`str()` is genuinely ALL the information there is anywhere -- there was
nothing more to find, anywhere, not even in the terminal, because
nothing ever logged the traceback in the first place.

:func:`configure_logging` fixes that at the source: every one of those
``except Exception`` catch sites additionally calls ``logger.exception(
...)`` (via each module's own ``logging.getLogger(__name__)``), which
captures the full traceback -- including the exact Python call site that
crossed into Basilisk's C++ layer -- to both the terminal (so a user
already running from one, as this project's own README has always
recommended, sees it live) and a persistent log file (so it survives a
scrolled-past or closed terminal, and can be attached to a bug report).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Set once by configure_logging(), read back by get_log_file_path() --
# e.g. so gui.main_window's error dialogs can point the user at exactly
# where the full traceback for what they just saw actually landed.
_log_file_path: Optional[Path] = None


def default_log_dir() -> Path:
    """``~/.missionstudio/logs`` -- alongside ``QSettings``' own default
    per-platform app-data convention (see ``gui.vizard_launcher``'s own
    ``QSettings()`` usage), but a plain filesystem path rather than
    ``QSettings`` itself: this needs to work from the CLI too, which has
    no ``QApplication``/organization-name set up to anchor ``QSettings``
    to.
    """
    return Path.home() / ".missionstudio" / "logs"


def configure_logging(log_dir: Optional[Path] = None, console_level: int = logging.INFO) -> Path:
    """Call once, at the very start of both entry points (``gui.app.main``,
    ``cli.main``) -- before anything else runs, so nothing that happens
    afterward (including import-time errors from lazily-imported modules)
    is ever missed.

    Returns the log file path just created, also retrievable afterward
    via :func:`get_log_file_path`.

    Idempotent: a second call in the same process (``cli.cmd_gui()``
    dispatching into ``gui.app.main()``, which is ALSO a documented
    standalone entry point in its own right -- see its own docstring --
    so it must configure logging itself too, independent of whether it
    was reached through the CLI or launched directly) returns the
    already-created path unchanged rather than adding duplicate handlers
    (which would print/write every message twice) or creating a second
    log file.

    Args:
        log_dir: directory to write the log file into. Defaults to
            :func:`default_log_dir`; overridable for tests (so they never
            touch the real developer machine's actual home directory).
        console_level: level for the terminal (stderr) handler -- the log
            FILE always captures ``DEBUG`` and up regardless (the whole
            point being to have somewhere that genuinely has "everything
            that happens," even when the terminal itself is deliberately
            kept less noisy for ordinary use).
    """
    global _log_file_path

    if _log_file_path is not None:
        return _log_file_path

    log_dir = log_dir if log_dir is not None else default_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    # One file per process launch (timestamped, not appended/rotated) --
    # simplest possible answer to "which run does this log belong to"
    # when several are kept around; old ones are left for the user to
    # clean up themselves (matching this project's existing archive
    # -directory conventions elsewhere, e.g. Monte Carlo's own
    # --archive-dir, rather than silently deleting anything).
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_file = log_dir / f"missionstudio_{timestamp}.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Uncaught exceptions (a genuine bug reaching all the way up through
    # a code path with no try/except at all -- e.g. a bug in Qt event
    # -handling code itself, not one of the three deliberate "never crash
    # the worker" catch-alls this module's own docstring is mainly
    # about) would otherwise print to stderr via Python's own default
    # hook and never reach the log file at all.
    def _log_uncaught_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("missionstudio.uncaught").critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = _log_uncaught_exception

    logging.getLogger(__name__).info("Logging to %s", log_file)
    _log_file_path = log_file
    return log_file


def get_log_file_path() -> Optional[Path]:
    """The path :func:`configure_logging` last created, or ``None`` if it
    was never called this process (e.g. a unit test that imports
    ``gui``/``cli`` modules directly without going through either real
    entry point).
    """
    return _log_file_path
