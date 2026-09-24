"""Tests for logging_setup -- see its own module docstring for the real
user report ("a crash whose only information anywhere was one bare line
in a GUI error dialog") this exists to fix.

No Basilisk/Qt dependency (pure ``logging``/``pathlib``/``datetime``), so
these run unconditionally, unlike most of this test suite.

Every test here relies on ``conftest.py``'s autouse ``_isolate_logging_
setup`` fixture, which already resets ``logging_setup._log_file_path``,
redirects ``Path.home()`` to a per-test ``tmp_path``, and restores the
root logger's handlers/level/excepthook afterward -- ``configure_logging()``
deliberately mutates global logging state (that's the whole point: it
must work from a bare entry point with no app-level context to thread a
logger instance through), so without that isolation a test that left
handlers behind would leak into every OTHER test's log output for the
rest of this process. ``_clean_logging_state`` below is kept only as a
descriptive alias for that autouse fixture, so these tests read as
depending on it explicitly.
"""

import logging

import pytest


@pytest.fixture
def _clean_logging_state(_isolate_logging_setup):
    """Alias for conftest.py's autouse isolation fixture -- see module
    docstring. Depending on it by name (even though it already applies to
    every test via autouse) documents that these specific tests need it.
    """
    yield


def test_configure_logging_creates_a_log_file(tmp_path, _clean_logging_state):
    from missionstudio.logging_setup import configure_logging

    log_file = configure_logging(log_dir=tmp_path)

    assert log_file.exists()
    assert log_file.parent == tmp_path


def test_configure_logging_returns_get_log_file_path(tmp_path, _clean_logging_state):
    from missionstudio.logging_setup import configure_logging, get_log_file_path

    log_file = configure_logging(log_dir=tmp_path)

    assert get_log_file_path() == log_file


def test_get_log_file_path_is_none_before_configure(_clean_logging_state):
    from missionstudio.logging_setup import get_log_file_path

    assert get_log_file_path() is None


def test_configure_logging_is_idempotent(tmp_path, _clean_logging_state):
    """A second call in the same process (see cli.main()'s own comment on
    why this happens for real: cmd_gui() dispatches into gui.app.main(),
    which calls this same function again) must not create a second log
    file or double up root-logger handlers (which would print/write
    every subsequent message twice).
    """
    from missionstudio.logging_setup import configure_logging

    root_logger = logging.getLogger()
    handlers_before = len(root_logger.handlers)

    first = configure_logging(log_dir=tmp_path)
    handlers_after_first = len(root_logger.handlers)
    second = configure_logging(log_dir=tmp_path / "different_dir_ignored")

    assert second == first
    assert len(root_logger.handlers) == handlers_after_first
    assert handlers_after_first > handlers_before


def test_a_logged_exception_lands_in_the_log_file(tmp_path, _clean_logging_state):
    """The actual point of this whole module: an exception logged via
    logger.exception() (exactly what run_worker.py's/kernel_status_widget
    .py's own except Exception catch-alls now do) must have its full
    traceback readable in the log file afterward, not just a bare
    message.
    """
    from missionstudio.logging_setup import configure_logging

    log_file = configure_logging(log_dir=tmp_path)
    logger = logging.getLogger("missionstudio.test_logging_setup")

    try:
        raise ValueError("a distinctive marker exception for this test")
    except ValueError:
        logger.exception("something failed")

    for handler in logging.getLogger().handlers:
        handler.flush()
    contents = log_file.read_text()

    assert "something failed" in contents
    assert "a distinctive marker exception for this test" in contents
    assert "Traceback (most recent call last)" in contents
    assert "test_a_logged_exception_lands_in_the_log_file" in contents  # the real call site, not just the message


def test_uncaught_exception_hook_logs_to_the_file(tmp_path, _clean_logging_state):
    from missionstudio.logging_setup import configure_logging

    log_file = configure_logging(log_dir=tmp_path)

    try:
        raise RuntimeError("an uncaught marker exception for this test")
    except RuntimeError:
        import sys

        sys.excepthook(*sys.exc_info())

    for handler in logging.getLogger().handlers:
        handler.flush()
    contents = log_file.read_text()

    assert "Uncaught exception" in contents
    assert "an uncaught marker exception for this test" in contents


def test_default_log_dir_is_under_home_dot_missionstudio():
    from missionstudio.logging_setup import default_log_dir

    result = default_log_dir()

    assert result.name == "logs"
    assert result.parent.name == ".missionstudio"
