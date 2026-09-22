# missionStudio (Phase 2)

A standalone, GUI-based mission-analysis application for Linux, using the
Basilisk astrodynamics framework (AVS Lab, University of Colorado Boulder)
as its sole simulation/dynamics engine. Think "STK/FreeFlyer-lite" --
every capability maps to a specific Basilisk module (see the capability
matrix delivered earlier in this project's history) or is explicitly
flagged as custom/out-of-scope, never fabricated.

This is **Phase 2** of the roadmap: attitude sensors/actuators/FSW pointing
-control modes + Vizard integration, on top of Phase 0's backend
foundations and Phase 1's PySide6 GUI/CLI. See "What Phase 2 adds" below
for exactly what that means.

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
  `missionstudio/engine/results.py`, `missionstudio/cli.py`, and **the
  entire `missionstudio/gui/` package** (including Phase 2's new
  sensor/actuator/FSW-mode/Vizard-request editors) has **no Basilisk
  import** and has been fully exercised here -- `pytest tests/` genuinely
  runs and passes 124 tests. That includes the PySide6 GUI: it was built,
  run headless (`QT_QPA_PLATFORM=offscreen`, set automatically by
  `tests/conftest.py`), and driven with `pytest-qt` for real -- every form
  field, every Save/Open/Run menu action, dirty-state tracking, and the
  unsaved-changes close-confirmation prompt is exercised by an actual
  running `QApplication`, not asserted about in the abstract. Getting
  PySide6 itself running headless in this sandbox needed three system
  packages beyond what was preinstalled (`libegl1 libopengl0
  libxcb-cursor0` on this Ubuntu-based image, via `apt-get`) -- worth
  knowing if a deployment target hits the same `ImportError: libEGL.so.1:
  cannot open shared object file` this session hit first.
* `missionstudio/engine/time_system.py`, `kernels.py`, `service.py`, and
  (new in Phase 2) `fsw.py`/`vizard.py` import Basilisk and **could not be
  executed or tested here**. They are written directly against this
  checkout's own verified source (module names, function signatures, and
  call sequences confirmed by reading the actual `.py`/`.cpp`/`.h`/`.i`
  files in `../src/`, and in several cases by copying an exact call
  sequence already proven to work in a real, already-run example script --
  `../missionAnalysis/run_constellation_mission.py` for Phase 0/1,
  `../examples/scenarioAttitudeFeedbackRW.py`/`scenarioAttitudeGuidance.py`/
  `scenarioHohmann.py`/`scenarioAttLocPoint.py` for Phase 2's FSW chain) --
  not from memory, and not guessed. Each of these files' docstring says
  exactly which parts are verified-by-example versus verified-by-reading
  -source-only, so nothing here should be trusted as "tested" that isn't.
* Because the GUI and CLI both genuinely can't import Basilisk here, both
  were also proven to FAIL GRACEFULLY under that exact condition, for
  real: `gui.run_worker.RunWorker`, `gui.kernel_status_widget`, and
  `cli.py`'s `run`/`kernels-status` commands all correctly report "Basilisk
  is not installed/built" (with no crash, no hang, no silent no-op) when
  actually run in this environment -- this is not a mocked-ImportError
  test, it is what genuinely happens.
* `tests/test_two_body_validation.py` -- the end-to-end analytical
  validation scenario this project's own requirements call for -- is
  written and ready, but is marked `@pytest.mark.requires_basilisk` and
  auto-skips here (see `tests/conftest.py`). **Run it on a machine with
  Basilisk built** to get the first real confirmation that
  `engine.service.SimulationService` actually works.

None of this is a reason to distrust the design -- it's the same
"write carefully against verified source, disclose what's untested"
discipline `../missionAnalysis` used throughout this project, applied to
a new codebase. Phase 1's big change is that far less of the new code
falls into the "untested" bucket than Phase 0's did, because the GUI
layer -- unlike the Basilisk engine layer -- has no hard dependency this
sandbox can't provide.

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
  GUI-agnostic backend class both the GUI and a headless/batch CLI call.
  Phase 0/1 scope: central-body point-mass or Earth spherical-harmonics
  gravity, PLUS third-body point-mass perturbers (`gravity.third_body_perturbers`
  -- genuinely wired up via `addBodiesTo()`, the same mechanism already
  verified in `../missionAnalysis`; an earlier draft of this file's
  docstring incorrectly called this schema-only, since corrected), one or
  more spacecraft from a classical-elements/Cartesian/TLE initial
  condition, propagation with a selectable integrator
  (`euler`/`rk2`/`rkf45`/`rkf78` -- **note: no `rk4`**, this Basilisk
  checkout doesn't ship one; see `schema.scenario.SUPPORTED_INTEGRATORS`'s
  docstring). Drag, SRP, sensors/actuators/FSW modes, ground stations, and
  Monte Carlo are validated by the schema and carried through save/load
  starting now, but not yet wired into the service -- that's Phase 2/3.
  The Phase 1 GUI's scenario editor mirrors this exactly: it edits
  everything the service actually consumes, and deliberately has no
  editor for the not-yet-wired-up fields, so nothing in the GUI looks
  like it does something it doesn't.
* **`missionstudio/scenarios/two_body_validation.json`** +
  **`tests/test_two_body_validation.py`** -- the required end-to-end
  validation scenario: Earth point-mass gravity only, propagated for
  several orbital periods, checked against an independently-computed
  analytical Kepler solution (position/velocity) and against conservation
  of specific orbital energy and angular momentum.

Two Phase 0 bugs were also found and fixed while building Phase 1 on top
of it (both are visible in `git log` for this file's history, not swept
under the rug): `schema.SimSettings` used to carry a second,
redundant `earth_grav_degree` field alongside `GravityConfig.
central_body_degree`, which could disagree with it -- removed, there is
now one field; and `schema.load_scenario()` didn't catch a missing/
unreadable file (`FileNotFoundError` propagated as a raw traceback
instead of the promised `ScenarioValidationError`) -- fixed, with a
regression test.

## What Phase 1 adds

* **`missionstudio/gui/`** -- the PySide6 GUI shell, one widget module per
  concern, none of it duplicating scenario/sim state or logic that
  already lives in `schema`/`engine`:
  * `scenario_editor.py` -- the full scenario form (name/epoch/description,
    gravity incl. third-body perturbers, sim settings, space weather
    source), with a live-updating "valid / here's exactly what's wrong"
    status label re-evaluated on every edit.
  * `spacecraft_editor.py` / `ground_station_editor.py` -- list + add/edit/
    remove dialogs for each. Spacecraft editing deliberately covers only
    what `engine.service.SimulationService` actually consumes (name,
    orbit IC, dry mass, inertia, initial attitude/rate) -- no
    sensors/actuators/FSW-mode/drag/SRP editor yet, so nothing in the GUI
    implies an effect the engine doesn't actually have. Ground stations
    ARE editable despite not being consumed yet, since they're pure
    scenario data (this project's own spec draws exactly that
    distinction) rather than a "looks like it does something" control.
  * `orbit_ic_widget.py` -- one widget covering all three
    `schema.OrbitIC` forms (classical elements / Cartesian / TLE).
  * `kernel_status_widget.py` -- SPICE kernel fetch/cache status with a
    "Check / fetch kernels" button, runs on a background thread.
  * `results_widget.py` -- matplotlib-embedded (`FigureCanvasQTAgg`) plot
    of any `ResultSet` series, plus a "export all series to CSV" button.
  * `run_worker.py` -- runs `SimulationService` on a background `QThread`
    so propagation never freezes the UI.
  * `main_window.py` / `app.py` -- ties it together: File (New/Open/Save/
    Save As, with an unsaved-changes indicator and close-confirmation) and
    Run (Run Simulation, Check Kernels) menus.
* **`missionstudio/cli.py`** -- the batch/headless CLI, built on exactly
  the same `schema`/`engine` calls the GUI makes (`validate`, `run`,
  `kernels-status`, `spaceweather-resolve`, `gui`) -- see "Running the
  CLI" below.

## What Phase 2 adds

* **`missionstudio/engine/fsw.py`** -- builds the attitude navigation/
  guidance/control/actuation module chain per spacecraft, kept separate
  from `service.py` so that file stays orchestration-only. Every
  `schema.scenario.SpacecraftConfig.fsw_mode` maps to a real Basilisk FSW
  module: `inertial3D`/`hillPoint`/`velocityPoint` (routed through
  `attTrackingError`) and `sunSafePoint`/`locationPointing` (which already
  output an `AttGuidMsg`), all closing on `mrpFeedback` control. Actuation
  is either idealized (`extForceTorque`, the default) or real reaction
  -wheel hardware (`simIncludeRW`/`reactionWheelStateEffector`/
  `rwMotorTorque`) when a spacecraft has `"reaction_wheel"` actuators.
  Sensors (`star_tracker`/`imu`/`coarse_sun_sensor`/`magnetometer`) attach
  independently of `fsw_mode` since they read truth state/SPICE/the
  magnetic-field model directly. `"thruster"`/`"magnetic_torque_rod"`
  actuators and `locationPointing`'s `target_body` option are schema-valid
  but raise a specific, actionable error rather than being silently
  ignored -- see `fsw.py`'s module docstring for the full scoping list and
  exactly which example script each call sequence was copied from.
* **`missionstudio/engine/vizard.py`** -- the "no embedded 3D viewer, but
  good Vizard visualization with valuable live simulation data"
  requirement: wraps `vizSupport.enableUnityVisualization()` (live-stream
  or `.bin` playback file), passes reaction-wheel effectors through so
  Vizard draws its native per-wheel speed bars, and draws every ground
  station via `vizSupport.addLocation()` (lat/lon/alt + elevation-mask
  cone) so `locationPointing`'s target geometry is actually visible.
* **`ResultSet` now carries Phase 2 series** for any spacecraft that has
  them configured: `{name}.attitude_sigma_BN`, `{name}.body_rate_omega_BN_B`,
  `{name}.sun_heading_body`, `{name}.control_torque`, `{name}.rw_speeds`,
  and one `{name}.sensor.{sensor_name}` series per attached sensor --
  always in addition to, never instead of, the Phase 0 position/velocity
  series.
* **GUI**: `spacecraft_editor.py` gained a tabbed dialog (Orbit/mass,
  Sensors/actuators, Attitude control) backed by the new
  `gui/sensor_actuator_editor.py` (a generic Add/Edit/Remove list widget
  shared by sensors and actuators, since their shape is identical --
  `params` is edited as raw JSON text rather than a bespoke form per kind,
  since the schema deliberately keeps `params` an open dict). A real bug
  was fixed along the way: editing an existing spacecraft used to silently
  DROP its `sensors`/`actuators`/`fsw_mode`/`fsw_params`/`control_params`
  (the dialog built a brand new `SpacecraftConfig` without passing them
  through) -- harmless while nothing set them, a real data-loss bug the
  moment this phase's own editors did; fixed with a regression test. The
  Run menu gained a **Vizard...** action (`gui/vizard_dialog.py`) to pick
  disabled / save-a-playback-file / live-stream for the next run, plumbed
  through `RunWorker` into `SimulationService`.
* **CLI**: `missionstudio run` gained `--vizard-save-file`/
  `--vizard-live-stream` (mutually exclusive).

## Repository layout

```
missionStudio/
  README.md                          -- this file
  pyproject.toml                     -- packaging metadata, pytest config, CLI entry point
  missionstudio/
    cli.py                           -- batch/headless CLI + GUI launcher
    schema/
      scenario.py                    -- Scenario and friends, validation, save/load
      migrations.py                  -- schema-version migration registry
    engine/
      time_system.py                 -- UTC/TAI/TT/ET, single source of truth (needs Basilisk)
      kernels.py                     -- SPICE kernel fetch/status (needs Basilisk)
      spaceweather.py                -- CelesTrak fetch/validate/fallback (no Basilisk needed)
      results.py                     -- TimeSeries/ResultSet, CSV export (no Basilisk needed)
      service.py                     -- SimulationService (needs Basilisk)
      fsw.py                         -- Phase 2: attitude nav/guidance/control/actuation chain (needs Basilisk)
      vizard.py                      -- Phase 2: Vizard integration (needs Basilisk, imported lazily)
    gui/
      app.py                         -- QApplication entry point
      main_window.py                 -- MainWindow: File/Run menus, ties everything together
      scenario_editor.py             -- the full scenario form + live validation
      spacecraft_editor.py           -- spacecraft list + add/edit/remove dialog (tabbed: orbit, sensors/actuators, FSW)
      sensor_actuator_editor.py      -- Phase 2: generic sensor/actuator list + add/edit/remove dialog
      vizard_dialog.py               -- Phase 2: "enable Vizard for the next run" dialog
      ground_station_editor.py       -- ground station list + add/edit/remove dialog
      orbit_ic_widget.py             -- classical-elements/Cartesian/TLE orbit editor
      kernel_status_widget.py        -- SPICE kernel status panel
      results_widget.py              -- matplotlib results plot + CSV export
      run_worker.py                  -- SimulationService on a background QThread
    scenarios/
      two_body_validation.json       -- the Phase 0 validation scenario
  tests/
    conftest.py                      -- requires_basilisk / requires_gui auto-skip markers
    test_scenario_schema.py
    test_spaceweather.py
    test_results.py
    test_cli.py
    test_two_body_validation.py      -- requires_basilisk
    gui/
      test_orbit_ic_widget.py
      test_spacecraft_editor.py
      test_sensor_actuator_editor.py
      test_vizard_dialog.py
      test_ground_station_editor.py
      test_scenario_editor.py
      test_results_widget.py
      test_kernel_status_widget.py
      test_run_worker.py
      test_main_window.py
```

## Running the tests

```bash
cd missionStudio
python3 -m pip install -e ".[dev,gui]"
python3 -m pytest tests/ -v
```

Without a Basilisk build on `PYTHONPATH`, this runs 124 tests (schema,
space weather, results, CLI, and the full PySide6 GUI, run headless) and
skips the 2 in `test_two_body_validation.py` with a clear reason, per
`tests/conftest.py`. With Basilisk built (see `../docs/source/Build.rst`,
and `../missionAnalysis/README.md`'s own notes on making sure you're on
the right build), the same command runs all 126, including the analytical
validation.

If PySide6 fails to import with `ImportError: libEGL.so.1: cannot open
shared object file` (a minimal Linux install, or a container like the one
this session used), install the missing system libraries first --
Debian/Ubuntu: `apt-get install libegl1 libopengl0 libxcb-cursor0` (this
session also needed `libgl1`/`libxkbcommon0`, but those were already
present on the base image; a truly minimal system may need them too).

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

To also get attitude control and a Vizard playback file, set a
spacecraft's `fsw_mode`/`sensors`/`actuators` (see `engine/fsw.py`) and
pass a `VizardRequest`:

```python
from missionstudio.engine.vizard import VizardRequest

service = SimulationService(scenario, vizard_request=VizardRequest(save_file="out/viz.bin"))
result = service.run()
```

## Running the CLI

The `missionstudio` command (installed by `pip install -e .`; `python3 -m
missionstudio.cli` works identically without installing) is the
batch/headless entry point, built on exactly the calls above -- see
`cli.py`'s own docstring.

```bash
# no Basilisk needed:
missionstudio validate missionstudio/scenarios/two_body_validation.json
missionstudio spaceweather-resolve missionstudio/scenarios/two_body_validation.json

# needs a Basilisk build:
missionstudio run missionstudio/scenarios/two_body_validation.json --out-dir results/
missionstudio run scenario_with_fsw.json --out-dir results/ --vizard-save-file results/viz.bin
missionstudio kernels-status

# launches the PySide6 GUI (needs the 'gui' extra; does NOT need Basilisk
# to open -- only Run/Check Kernels need it, and report clearly if it's
# missing rather than crashing):
missionstudio gui
```

Without Basilisk, `run` and `kernels-status` print a specific "Basilisk is
not installed/built" message and exit with status 2 -- genuinely verified
in this development sandbox (see the honesty note above), not just
designed to behave that way.

## Running the GUI

```bash
python3 -m pip install -e ".[gui]"
missionstudio gui
# or: python3 -m missionstudio.gui.app
```

The GUI opens with a blank scenario. File > New/Open/Save/Save As work
against the same `schema.Scenario`/`load_scenario()`/`.save()` the CLI
uses; the scenario form's validation status label updates live as you
type. Run > Run Simulation runs `SimulationService` on a background
thread (the UI stays responsive) and switches to the Results tab when
done, with a plot per result series and a CSV export button. Run > Check
Kernels shows SPICE kernel fetch/cache status. Both Run actions report a
clear error (not a crash) if Basilisk isn't installed/built.

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
* **Spherical-harmonics gravity is Earth-only in `service.py`**
  (GGM03S, the same file `../missionAnalysis` uses). Other central bodies
  are limited to point-mass gravity (`central_body_degree=0`) until a
  later phase adds their gravity-field files.
* **Magnetometer sensors are Earth-only** (`magneticFieldWMM`, same
  reasoning as spherical-harmonics gravity) -- `engine.fsw` raises a clear
  error for a magnetometer on any other central body rather than silently
  producing a sensor with no field to read.
* **`locationPointing`'s `target_body` option (point at a celestial body
  directly, not a ground station) is schema-valid but not wired up** --
  it needs an `EphemerisMsg`, which this checkout only produces via
  `ephemerisConverter` from a `SpicePlanetStateMsg`, not yet built here.
* **`"thruster"`/`"magnetic_torque_rod"` actuator kinds are schema-valid
  but not wired up** -- `engine.fsw`/`engine.service` raise a specific
  error if either is actually configured, rather than silently doing
  nothing.
* **Ground-station ACCESS analysis (as opposed to using a station as a
  `locationPointing` target) is Phase 3 scope**, matching this project's
  original roadmap boundary ("Phase 3: Monte Carlo + access analysis +
  packaging") -- `engine.fsw.build_ground_location()` is already capable
  of it (it just needs a non-empty spacecraft list), `engine.service`
  deliberately doesn't call it that way yet.
* **The attitude control loop closes on truth spacecraft state.**
  `simpleNav` is in the loop (not raw `scStateOutMsg`), but its
  error-model matrices are left at Basilisk's own zero defaults -- there
  is no GUI/schema field yet to configure realistic navigation error.

## Next: Phase 3

Per the roadmap: Monte Carlo (`Basilisk.utilities.MonteCarlo`, a real,
already-confirmed-usable batch-execution framework with dispersion
generators), ground-station ACCESS analysis (`groundLocation.accessOutMsgs`
-- the `GroundLocation` objects Phase 2's `locationPointing` targeting
already builds are a running start), and packaging (the vendored-wheel
decision flagged below).
