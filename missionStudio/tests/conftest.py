"""Shared pytest fixtures/markers for the missionStudio test suite.

This checkout does not have a built Basilisk Python package available (see
``missionStudio/README.md`` -- a from-source build was attempted and
failed because this development sandbox's network policy blocks Conan
Center). Tests that need ``import Basilisk`` are marked with
``@pytest.mark.requires_basilisk`` and are auto-skipped (not silently
passed, not errored) when Basilisk isn't importable, so:

* running the suite here honestly reports what could and couldn't be
  checked, instead of the whole run failing at collection time or a
  Basilisk-dependent test being miscounted as "passed", and
* the exact same test file runs those tests for real, no changes needed,
  the moment it's executed on a machine with Basilisk built.
"""

import importlib.util

import pytest

BASILISK_AVAILABLE = importlib.util.find_spec("Basilisk") is not None


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_basilisk: test needs a built Basilisk Python package (auto-skipped without one)"
    )


def pytest_collection_modifyitems(config, items):
    if BASILISK_AVAILABLE:
        return
    skip_marker = pytest.mark.skip(reason="Basilisk is not installed/built in this environment")
    for item in items:
        if "requires_basilisk" in item.keywords:
            item.add_marker(skip_marker)
