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
import os

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


def pytest_collection_modifyitems(config, items):
    skip_basilisk = pytest.mark.skip(reason="Basilisk is not installed/built in this environment")
    skip_gui = pytest.mark.skip(reason="PySide6 is not installed (pip install -e '.[gui]')")
    for item in items:
        if not BASILISK_AVAILABLE and "requires_basilisk" in item.keywords:
            item.add_marker(skip_basilisk)
        if not GUI_AVAILABLE and "requires_gui" in item.keywords:
            item.add_marker(skip_gui)
