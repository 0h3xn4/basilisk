# missionStudio (Phase 0)

A standalone, GUI-based mission-analysis application for Linux, using the
Basilisk astrodynamics framework (AVS Lab, University of Colorado Boulder)
as its sole simulation/dynamics engine. Think "STK/FreeFlyer-lite" --
every capability maps to a specific Basilisk module (see the capability
matrix delivered earlier in this project's history) or is explicitly
flagged as custom/out-of-scope, never fabricated.

This is **Phase 0** of the roadmap: backend foundations only, no GUI yet.
See "What Phase 0 delivers" below for exactly what that means.

## Environment honesty note (read this first)

This checkout does not have a built Basilisk Python package available. A
from-source build was attempted in this development sandbox and failed:
`conanfile.py` reached the dependency-resolution step and then failed to
fetch `eigen/3.4.0` from Conan Center, because this sandbox's outbound
-network policy blocks `center2.conan.io` (a 403 policy denial, not a
flaky network -- confirmed directly). `celestrak.org` is blocked the same
way.

Consequently, in **this** environment:

* Everything in `missionstudio/schema/`, `missionstudio/engine/spaceweather.py`,
  and `missionstudio/engine/results.py` has **no Basilisk import** and has
  been fully exercised here -- `pytest tests/` genuinely runs and passes
  35 tests covering the scenario schema, its versioning/migration
  machinery, the space-weather fetch/validate/fallback chain (including a
  real, unmocked network call that fails exactly the way it will on any
  network-restricted machine, proving the fallback chain works for real,
  not just in a mock), and the results/CSV-export layer.
* `missionstudio/engine/time_system.py`, `kernels.py`, and `service.py`
  import Basilisk and **could not be executed or tested here**. They are
  written directly against this checkout's own verified source (module
  names, function signatures, and call sequences confirmed by reading the
  actual `.py`/`.cpp`/`.i` files in `../src/`, and in several cases by
  copying an exact call sequence already proven to work in
  `../missionAnalysis/run_constellation_mission.py`, which HAS been run
  against a real Basilisk build earlier in this project) -- not from
  memory, and not guessed. Each of these files' docstring says exactly
  which parts are verified-by-example versus verified-by-reading-source
  -only, so nothing here should be trusted as "tested" that isn't.
* `tests/test_two_body_validation.py` -- the end-to-end analytical
  validation scenario this project's own requirements call for -- is
  written and ready, but is marked `@pytest.mark.requires_basilisk` and
  auto-skips here (see `tests/conftest.py`). **Run it on a machine with
  Basilisk built** to get the first real confirmation that
  `engine.service.SimulationService` actually works.

None of this is a reason to distrust the design -- it's the same
"write carefully against verified source, disclose what's untested"
discipline `../missionAnalysis` used throughout this project, applied to
a new codebase.

## What Phase 0 delivers

* **`missionstudio/schema/`** -- a versioned, human-readable JSON scenario
  format (spacecraft, orbit ICs in three forms, gravity, ground stations,
  space weather, sim settings), with hand-written validation (clear,
  specific error messages -- never a silent NaN or a bare `KeyError`) and
  a migration registry so old scenario files keep loading as the schema
  grows. No Basilisk dependency; no third-party schema library.
* **`missionstudio/engine/time_system.py`** -- single source of truth for
  time: every scenario stores exactly one epoch representation
  (`epoch_utc`, ISO 8601 UTC); every other representation (SPICE ET, TAI,
  TT, or a Basilisk `EpochMsg`) is derived from it on demand by this
  module, via the real CSPICE time API (through `pyswice`) -- not
  hand-rolled date math.
* **`missionstudio/engine/kernels.py`** -- SPICE kernel management: wraps
  Basilisk's own versioned, `pooch`-cached kernel fetcher
  (`Basilisk.utilities.supportDataTools.dataFetcher`) and adds a status
  report (path, fetched-or-not, cache-file modified time) so kernel state
  is always visible, never silently assumed current.
* **`missionstudio/engine/spaceweather.py`** -- CelesTrak space-weather
  fetch → validate → fallback, exactly per this project's own
  instruction: try CelesTrak first; if that isn't possible, fall back to
  a user-provided local file; only fall back further than that (a
  synthetic, solar-cycle-shaped profile) loudly, with an explicit warning
  in the returned result, never silently. The CSV format check mirrors
  Basilisk's own `spaceWeatherData.cpp` loader validation exactly (same
  required columns, same duplicate/sort checks), so a bad file is caught
  here with a specific message instead of failing deep inside Basilisk.
* **`missionstudio/engine/results.py`** -- a typed result container
  (`TimeSeries`/`ResultSet`) with CSV export, independent of how the data
  was produced -- reusable by the future GUI (plotting) and by headless
  runs (export) without either depending on the other.
* **`missionstudio/engine/service.py`** -- `SimulationService`: the one
  GUI-agnostic backend class both the future GUI and a headless/batch CLI
  will call. Phase 0 scope: central-body point-mass or Earth
  spherical-harmonics gravity, one or more spacecraft from a
  classical-elements/Cartesian/TLE initial condition, propagation with a
  selectable integrator (`euler`/`rk2`/`rkf45`/`rkf78` -- **note: no
  `rk4`**, this Basilisk checkout doesn't ship one; see
  `schema.scenario.SUPPORTED_INTEGRATORS`'s docstring). Drag, SRP,
  third-body gravity, sensors/actuators/FSW modes, ground stations, and
  Monte Carlo are validated by the schema and carried through save/load
  starting now, but not yet wired into the service -- that's Phase 2/3.
* **`missionstudio/scenarios/two_body_validation.json`** +
  **`tests/test_two_body_validation.py`** -- the required end-to-end
  validation scenario: Earth point-mass gravity only, propagated for
  several orbital periods, checked against an independently-computed
  analytical Kepler solution (position/velocity) and against conservation
  of specific orbital energy and angular momentum.

## Repository layout

```
missionStudio/
  README.md                          -- this file
  pyproject.toml                     -- packaging metadata, pytest config
  missionstudio/
    schema/
      scenario.py                    -- Scenario and friends, validation, save/load
      migrations.py                  -- schema-version migration registry
    engine/
      time_system.py                 -- UTC/TAI/TT/ET, single source of truth (needs Basilisk)
      kernels.py                     -- SPICE kernel fetch/status (needs Basilisk)
      spaceweather.py                -- CelesTrak fetch/validate/fallback (no Basilisk needed)
      results.py                     -- TimeSeries/ResultSet, CSV export (no Basilisk needed)
      service.py                     -- SimulationService (needs Basilisk)
    scenarios/
      two_body_validation.json       -- the Phase 0 validation scenario
  tests/
    conftest.py                      -- requires_basilisk auto-skip marker
    test_scenario_schema.py
    test_spaceweather.py
    test_results.py
    test_two_body_validation.py      -- requires_basilisk
```

## Running the tests

```bash
cd missionStudio
python3 -m pip install -e ".[dev]"
python3 -m pytest tests/ -v
```

Without a Basilisk build on `PYTHONPATH`, this runs 35 tests (schema,
space weather, results) and skips the 2 in `test_two_body_validation.py`
with a clear reason, per `tests/conftest.py`. With Basilisk built (see
`../docs/source/Build.rst`, and `../missionAnalysis/README.md`'s own notes
on making sure you're on the right build), the same command runs all 37,
including the analytical validation.

## Using the schema/space-weather layer standalone (no Basilisk needed)

```python
from missionstudio.schema import Scenario, GravityConfig, OrbitIC, SpacecraftConfig

scenario = Scenario(
    name="demo",
    epoch_utc="2030-01-01T00:00:00",
    gravity=GravityConfig(central_body="earth", central_body_degree=0),
    spacecraft=[
        SpacecraftConfig(
            name="sat-1",
            orbit=OrbitIC(type="classical_elements", semi_major_axis_km=7000.0,
                          eccentricity=0.001, inclination_deg=51.6, raan_deg=0.0,
                          arg_periapsis_deg=0.0, true_anomaly_deg=0.0),
        )
    ],
)
scenario.validate()
scenario.save("my_scenario.json")
```

```python
from datetime import datetime
from missionstudio.engine import spaceweather as sw

resolved = sw.resolve("celestrak", datetime(2030, 1, 1), datetime(2030, 4, 1),
                       local_file_path="/path/to/your/SW-All.csv")  # your CelesTrak download, if you have one
print(resolved.path, resolved.is_synthetic, resolved.warnings)
```

## Running a scenario (requires a Basilisk build)

```python
from missionstudio.schema import load_scenario
from missionstudio.engine.service import SimulationService

scenario = load_scenario("missionstudio/scenarios/two_body_validation.json")
service = SimulationService(scenario)
result = service.run()
result.export_csv("out/")
```

## Vendoring vs. building Basilisk from source (a Phase 4 decision, flagged now)

Building from source in an automated/CI/sandboxed context is fragile --
this project hit exactly that failure mode moments before Phase 0 started
(see the honesty note above). The roadmap's Phase 4 packaging plan is to
**vendor a prebuilt wheel pinned to a specific Basilisk release/commit**
as the default install path for end users, keeping "build from source" as
a documented, opt-in developer path only. Nothing in Phase 0 forecloses
that decision; it only affects packaging later.

## Known limitations carried over from the capability audit

See the capability matrix and limitations list delivered earlier in this
project for the full picture. The two most relevant to Phase 0 code
specifically:

* **No `svIntegratorRK4` in this checkout.** Only `svIntegratorEuler`,
  `svIntegratorRK2`, `svIntegratorRKF45`, `svIntegratorRKF78` exist (see
  `../src/simulation/dynamics/Integrators/`). `schema.scenario.SimSettings`
  and `engine.service._INTEGRATORS` only offer those four; `"rkf78"` is
  the default.
* **Spherical-harmonics gravity is Earth-only in Phase 0's `service.py`**
  (GGM03S, the same file `../missionAnalysis` uses). Other central bodies
  are limited to point-mass gravity (`central_body_degree=0`) until a
  later phase adds their gravity-field files.

## Next: Phase 1

Core propagation + minimal GUI + save/load, per the roadmap: a PySide6
shell around `SimulationService` (scenario editor, run button, basic
time-history plots via `ResultSet`), a batch/headless CLI using the same
service layer the GUI calls, and kernel-status/space-weather-source
surfaced in the UI rather than silently resolved in the background.
