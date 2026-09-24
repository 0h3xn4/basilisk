"""Tests for gui.vizard_launcher -- path lookup/persistence and process
launch, all with real filesystem/QSettings I/O redirected into tmp_path
(never touching the real developer machine's actual Vizard install or
settings store).
"""

import subprocess
import sys

import pytest
from PySide6.QtCore import QSettings

pytestmark = pytest.mark.requires_gui


def _settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def test_find_returns_none_with_no_remembered_path_and_nothing_on_disk(tmp_path, monkeypatch):
    from missionstudio.gui import vizard_launcher

    monkeypatch.setattr(vizard_launcher, "_candidate_roots", lambda: [tmp_path / "does_not_exist"])
    assert vizard_launcher.find_vizard_executable(settings=_settings(tmp_path)) is None


def test_remember_then_find_returns_the_remembered_path(tmp_path, monkeypatch):
    from missionstudio.gui import vizard_launcher

    fake_exe = tmp_path / "Vizard.x86_64"
    fake_exe.write_bytes(b"")
    settings = _settings(tmp_path)

    vizard_launcher.remember_vizard_executable(fake_exe, settings=settings)
    assert vizard_launcher.find_vizard_executable(settings=settings) == fake_exe


def test_remembered_path_that_no_longer_exists_falls_back_to_search(tmp_path, monkeypatch):
    from missionstudio.gui import vizard_launcher

    settings = _settings(tmp_path)
    vizard_launcher.remember_vizard_executable(tmp_path / "gone" / "Vizard.x86_64", settings=settings)

    search_root = tmp_path / "search_root"
    search_root.mkdir()
    found_exe = search_root / vizard_launcher._EXECUTABLE_NAME
    found_exe.write_bytes(b"")
    monkeypatch.setattr(vizard_launcher, "_candidate_roots", lambda: [search_root])

    assert vizard_launcher.find_vizard_executable(settings=settings) == found_exe


def test_search_finds_executable_directly_in_a_candidate_root(tmp_path, monkeypatch):
    from missionstudio.gui import vizard_launcher

    root = tmp_path / "Desktop"
    root.mkdir()
    exe = root / vizard_launcher._EXECUTABLE_NAME
    exe.write_bytes(b"")
    monkeypatch.setattr(vizard_launcher, "_candidate_roots", lambda: [root])

    assert vizard_launcher.find_vizard_executable(settings=_settings(tmp_path)) == exe


def test_search_finds_executable_one_level_down_in_a_candidate_root(tmp_path, monkeypatch):
    """Covers "unzipped into its own subfolder" (e.g. Desktop/Vizard_Windows64/Vizard.exe)."""
    from missionstudio.gui import vizard_launcher

    root = tmp_path / "Downloads"
    nested = root / "Vizard_Windows64"
    nested.mkdir(parents=True)
    exe = nested / vizard_launcher._EXECUTABLE_NAME
    exe.write_bytes(b"")
    monkeypatch.setattr(vizard_launcher, "_candidate_roots", lambda: [root])

    assert vizard_launcher.find_vizard_executable(settings=_settings(tmp_path)) == exe


def test_search_skips_a_nonexistent_root_without_raising(tmp_path, monkeypatch):
    from missionstudio.gui import vizard_launcher

    real_root = tmp_path / "real"
    real_root.mkdir()
    exe = real_root / vizard_launcher._EXECUTABLE_NAME
    exe.write_bytes(b"")
    # A missing root ahead of a real one must be skipped, not raise.
    monkeypatch.setattr(vizard_launcher, "_candidate_roots", lambda: [tmp_path / "missing", real_root])

    assert vizard_launcher.find_vizard_executable(settings=_settings(tmp_path)) == exe


def test_launch_starts_the_given_executable_directly_on_non_macos(tmp_path, monkeypatch):
    from missionstudio.gui import vizard_launcher

    monkeypatch.setattr(vizard_launcher.sys, "platform", "linux")
    exe = tmp_path / "Vizard.x86_64"
    exe.write_bytes(b"")

    captured = {}

    class _FakeProcess:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(args):
        captured["args"] = args
        return _FakeProcess()

    monkeypatch.setattr(vizard_launcher.subprocess, "Popen", fake_popen)
    result = vizard_launcher.launch_vizard(exe)

    assert captured["args"] == [str(exe)]
    assert result.pid == 4242


def test_launch_resolves_macos_app_bundle_to_its_inner_binary(tmp_path, monkeypatch):
    from missionstudio.gui import vizard_launcher

    monkeypatch.setattr(vizard_launcher.sys, "platform", "darwin")
    bundle = tmp_path / "Vizard.app"
    macos_dir = bundle / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    inner_binary = macos_dir / "Vizard"
    inner_binary.write_bytes(b"")

    captured = {}
    monkeypatch.setattr(vizard_launcher.subprocess, "Popen", lambda args: captured.setdefault("args", args))

    vizard_launcher.launch_vizard(bundle)
    assert captured["args"] == [str(inner_binary)]


def test_launch_raises_a_clear_error_for_an_empty_macos_bundle(tmp_path, monkeypatch):
    from missionstudio.gui import vizard_launcher

    monkeypatch.setattr(vizard_launcher.sys, "platform", "darwin")
    bundle = tmp_path / "Vizard.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="does not look like a valid macOS app bundle"):
        vizard_launcher.launch_vizard(bundle)
