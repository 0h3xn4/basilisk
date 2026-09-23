# Packaging

Phase 3 scope, per the roadmap ("Phase 3: Monte Carlo + access analysis +
packaging"). This directory covers the Basilisk-independent half of
packaging missionStudio into a real, installable Linux artifact --
everything here has been built and run for real in this project's
development sandbox. The Basilisk-dependent half (vendoring an actual
Basilisk wheel) could not be, and that limit is explained below rather
than glossed over.

## What's here

* **`build_wheel.sh`** -- builds `missionstudio`'s own wheel + sdist
  (`python -m build`). Genuinely run here: `dist/missionstudio-<version>-py3-none-any.whl`
  was built, installed into a throwaway venv, and its CLI entry point
  (`missionstudio validate ...`) and GUI (`missionstudio.gui.main_window.MainWindow`,
  constructed headless) were both exercised against the INSTALLED copy,
  not the checkout.

  A real bug was caught doing this: `missionstudio/scenarios/*.json` (the
  two-body validation scenario) was silently missing from the built wheel,
  because `setuptools.packages.find()` only picks up Python packages
  (directories with `__init__.py`), and `scenarios/` has none. Fixed via
  `pyproject.toml`'s `[tool.setuptools.package-data]` -- re-verified by
  rebuilding and confirming the file is now present in the wheel and
  loadable from the installed copy.

  A second real bug was caught running this script TWICE in a row:
  `python -m build`'s own temp output directory (`./build/`, gitignored)
  is left behind after a run, and because Python inserts the current
  directory at the front of `sys.path` for both `-c` and `-m` invocations,
  that leftover directory silently SHADOWED the real installed `build`
  package on the next run (`ModuleNotFoundError`-adjacent: `No module
  named build.__main__`). Fixed by having the script clean `./build/`
  before it starts, and by checking installedness with `pip show build`
  instead of `python -c "import build"` (which was itself vulnerable to
  the same shadowing). Re-verified by running the script twice
  back-to-back after the fix.

* **`install.sh`** -- an end-user installer: creates a private venv,
  builds (or accepts) a missionstudio wheel and installs it with the
  `gui` extra, optionally installs a vendored Basilisk wheel into the same
  venv (`--basilisk-wheel PATH_OR_URL`), writes a `missionstudio` launcher
  script, and installs a `~/.local/share/applications/missionstudio.desktop`
  entry (skippable with `--no-desktop-entry`). Genuinely run here TWICE in
  a row (the regression check for the bug above) with a fake `$HOME`/
  `$XDG_DATA_HOME`, confirming: the venv installs cleanly, the launcher
  script's `missionstudio validate` works against the installed scenario
  file, and the desktop entry is written with the correct `Exec=` path.
  The `--basilisk-wheel` path itself (`pip install <wheel>` into the venv)
  is ordinary, non-missionstudio-specific `pip` behavior -- not something
  this project can miswire in a Basilisk-specific way -- but it could NOT
  be exercised end-to-end here, because this development sandbox has no
  built Basilisk wheel to test it against (see the main README's
  "Environment honesty note": the same Conan Center network block that
  stopped a from-source Basilisk build here also means there's nothing
  vendorable sitting around to install with this flag).

* **`missionstudio.desktop.in`** -- the desktop-entry template `install.sh`
  fills in (`@INSTALL_PREFIX@` -> the venv's parent directory).
  `Icon=missionstudio` now resolves to a real icon: `install.sh` renders
  `gui/icons.py`'s procedurally-drawn app icon (QPainter, no bitmap asset
  in the repo -- see that module's docstring) to
  `$XDG_DATA_HOME/icons/hicolor/256x256/apps/missionstudio.png` (the
  standard hicolor icon theme location) right after writing the desktop
  entry, using the `offscreen` Qt platform plugin so no display is needed
  even on a headless install. Non-fatal if it fails (e.g. no Qt platform
  plugins present at all) -- the desktop entry still installs, just with
  the icon theme's generic fallback.

## The vendoring decision (why there's no Basilisk wheel here)

Flagged since Phase 0's README: **vendor a prebuilt Basilisk wheel pinned
to a specific release/commit** as the default install path for end users,
keeping "build Basilisk from source" a documented, opt-in developer path
only (building from source in an automated/sandboxed context is fragile --
this project hit exactly that failure mode, a Conan Center network block,
before Phase 0 even started).

This phase implements the RECEIVING end of that decision (`install.sh
--basilisk-wheel`) but does not itself produce a Basilisk wheel, because
doing so needs a working Basilisk build -- which this development sandbox
has never had, for the same network-policy reason throughout this whole
project (see `../README.md`'s "Environment honesty note"). Producing that
wheel is a separate, one-time release-engineering task (on a machine that
CAN build Basilisk, following `../../docs/source/Build.rst`, then
`python -m pip wheel .` from that checkout, or using Basilisk's own
distributed wheel if/when AVS Lab publishes one) -- not something that
belongs inside this app's own packaging scripts, and not something this
phase can fabricate without a real build to produce it from.

## Producing a full offline installable bundle

Not built in this phase (would need the vendored Basilisk wheel above to
be meaningful to test): the natural next step, once a Basilisk wheel
exists, is `pip download` -ing missionstudio + Basilisk + all extras'
dependencies into a local directory (`--no-deps` per package, or a
`requirements.txt` with hashes) so `install.sh` can run fully offline,
and/or wrapping the venv + launcher in a single self-extracting archive
(e.g. `makeself`) for a true single-file installer. Flagged here rather
than attempted blind, per this whole project's "don't fabricate what
can't be verified" discipline.
