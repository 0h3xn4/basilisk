"""Shared pytest fixtures/markers for the missionStudio test suite.

Two independent "is this optional dependency installed" markers, both
auto-skipping (not failing collection, not silently passing) rather than
erroring the whole run when the corresponding install extra is missing:

* ``requires_basilisk``: needs a built Basilisk Python package. This
  development sandbox doesn't have one (see ``missionStudio/README.md`` --
  a from-source build was attempted and failed because this sandbox's
  network policy blocks Conan Center).
* ``requires_gui``: needs PySide6 (the ``gui`` extra, ``pip install
  -e ".[gui]"``). Also forces ``QT_QPA_PLATFORM=offscreen`` before any Qt
  import happens (unless the environment already set ``QT_QPA_PLATFORM``
  explicitly) so the GUI test suite runs on a machine with no display --
  this is how it is genuinely exercised in this development sandbox too,
  not just designed to work that way in theory.
"""

import importlib.util
import logging
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASILISK_AVAILABLE = importlib.util.find_spec("Basilisk") is not None
GUI_AVAILABLE = importlib.util.find_spec("PySide6") is not None


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_basilisk: test needs a built Basilisk Python package (auto-skipped without one)"
    )
    config.addinivalue_line(
        "markers", "requires_gui: test needs PySide6 (the 'gui' extra; auto-skipped without it)"
    )


@pytest.fixture(autouse=True)
def _isolate_logging_setup(tmp_path, monkeypatch):
    """``cli.main()``/``gui.app.main()`` both call ``logging_setup.
    configure_logging()`` for real -- and several tests (``test_cli.py``
    in particular) call ``cli.main()`` directly, not through a subprocess,
    so without this, the FIRST such test in the whole session would
    permanently mutate this test process's real root logger (adding a
    ``StreamHandler`` bound to whatever ``sys.stderr`` happened to be at
    that moment -- pytest's own per-test capture replaces ``sys.stderr``
    with a fresh object every test and closes the old one, so that
    handler would start raising "I/O operation on closed file" on every
    later test that logs anything) and would write real log files into
    this machine's actual ``~/.missionstudio/logs``, neither of which any
    test should do as a side effect of something unrelated.

    Autouse (applies to literally every test, not just ``test_logging_
    setup.py``'s own) since the leak this prevents is caused by ANY test
    that happens to invoke a real entry point, not just tests that are
    themselves about logging.
    """
    from pathlib import Path

    from missionstudio import logging_setup

    monkeypatch.setattr(logging_setup, "_log_file_path", None)
    # Patch Path.home() rather than default_log_dir() itself, so
    # default_log_dir()'s own logic (exercised directly by
    # test_default_log_dir_is_under_home_dot_missionstudio) still runs for
    # real -- it just resolves under this test's tmp_path instead of the
    # real ~ -- rather than being replaced wholesale, which would make that
    # test observe this fixture's stand-in instead of the function it's
    # meant to test.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    original_excepthook = sys.excepthook

    yield

    for handler in list(root_logger.handlers):
        if handler not in original_handlers:
            root_logger.removeHandler(handler)
            handler.close()
    root_logger.setLevel(original_level)
    sys.excepthook = original_excepthook


def pytest_collection_modifyitems(config, items):
    skip_basilisk = pytest.mark.skip(reason="Basilisk is not installed/built in this environment")
    skip_gui = pytest.mark.skip(reason="PySide6 is not installed (pip install -e '.[gui]')")
    for item in items:
        if not BASILISK_AVAILABLE and "requires_basilisk" in item.keywords:
            item.add_marker(skip_basilisk)
        if not GUI_AVAILABLE and "requires_gui" in item.keywords:
            item.add_marker(skip_gui)
