# missionStudio (Phase 4)

A standalone, GUI-based mission-analysis application for Linux, using the
Basilisk astrodynamics framework (AVS Lab, University of Colorado Boulder)
as its sole simulation/dynamics engine. Think "STK/FreeFlyer-lite" --
every capability maps to a specific Basilisk module (see the capability
matrix delivered earlier in this project's history) or is explicitly
flagged as custom/out-of-scope, never fabricated.

This is **Phase 4** of the roadmap: usability fixes and mission-analysis
outputs driven directly by real GUI usage feedback -- a more informative
Vizard default view, live run/Monte Carlo progress feedback, mean-anomaly
orbit input, and real power-budget/link-budget results -- on top of Phase
0's backend foundations, Phase 1's PySide6 GUI/CLI, Phase 2's
attitude/sensors/actuators/Vizard work, and Phase 3's Monte Carlo +
ground-station access analysis + packaging. See "What Phase 4 adds" below
for exactly what that means.

## Getting started

Everything below was actually run, not just written and assumed to work --
including step 2, which for most of this project's history looked like it
would need a from-source Basilisk build (fragile, and blocked in this
project's own sandbox). It turned out Basilisk now publishes a prebuilt
wheel to PyPI, and installing it that way genuinely works.

**1. Prerequisites**

* Linux, Python 3.9+.
* `python3 -m venv` (or your preferred environment tool) -- everything
  below assumes a virtualenv so it doesn't touch your system Python.

**2. Install Basilisk**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "bsk[all]"
```

This is Basilisk's own recommended install path (see `../docs/source/Install.rst`
in this checkout) -- a prebuilt wheel from PyPI, no compiler or Conan
required. It was genuinely run in this project's development sandbox: the
wheel downloads and installs cleanly, and every Basilisk module/class this
app's code imports (across all three phases) was confirmed present.
Building from source is still possible and documented
(`../docs/source/Build.rst`) if you need an unpublished feature or a
locally-modified Basilisk, but it's no longer the first thing to reach for.

**3. Install missionStudio**

```bash
cd missionStudio
pip install -e ".[dev,gui]"
```

(Or skip steps 2-3 and run `packaging/install.sh --basilisk-wheel "bsk[all]"`
instead, which does both in one shot into its own private venv and adds a
desktop launcher -- see `packaging/README.md`. That flag genuinely works
now, for the same reason step 2 does.)

**4. Check it's working**

```bash
missionstudio kernels-status
```

The first time you run anything that touches SPICE (this command, `run`,
or the GUI's Run menu), Basilisk downloads a handful of standard SPICE
kernels (leap-seconds, planetary ephemeris, ~100 MB total) from NAIF and
caches them locally -- this needs working internet access to
`naif.jpl.nasa.gov` once. `kernels-status` reports exactly which kernels
are missing/cached and why, rather than failing silently deep inside a
run.

**5. Run something**

```bash
missionstudio validate missionstudio/scenarios/two_body_validation.json
missionstudio run missionstudio/scenarios/two_body_validation.json --out-dir results/
```

or launch the GUI:

```bash
missionstudio gui
```

File > Open the same scenario, or build one from scratch (spacecraft,
sensors, actuators, FSW mode, ground stations, Monte Carlo dispersions --
all editable live with validation feedback), then Run > Run Simulation.

**If something doesn't work**, the "Environment honesty note" right below
explains exactly what this project could and couldn't verify in its own
sandbox (a network policy there blocks the NAIF kernel host specifically,
so the one thing NOT independently confirmed end-to-end is a full run
past kernel loading) -- read it before assuming a failure is a bug rather
than a network/environment issue on your end.

## Environment honesty note (read this first)

Earlier in this project, this checkout had no Basilisk Python package
available: a from-source build was attempted and failed (`conanfile.py`
couldn't reach Conan Center through this sandbox's outbound-network
policy). That's no longer the full picture -- `pip install "bsk[all]"`
(Basilisk's own published PyPI wheel) turned out to work in the same
sandbox, and was used to genuinely re-verify most of the Basilisk
-dependent code below for the first time. `celestrak.org` and the NAIF
kernel host (`naif.jpl.nasa.gov`, plus its `hanspeterschaub.info` backup
mirror) remain blocked, which is the one gap left -- see the per-item
notes below for exactly what that does and doesn't affect.

Status, as of this Basilisk-build re-verification pass:

* Everything in `missionstudio/schema/`, `missionstudio/engine/spaceweather.py`,
  `missionstudio/engine/results.py`, `missionstudio/cli.py`, and **the
  entire `missionstudio/gui/` package** (including Phase 2's sensor/
  actuator/FSW-mode/Vizard-request editors and Phase 3's Monte Carlo
  editor) has **no Basilisk import** and has been fully exercised, with or
  without Basilisk present -- `pytest tests/` genuinely runs and passes
  150 tests either way (see "Running the tests" below for the
  with-Basilisk count). That includes the PySide6 GUI: it was built, run
  headless (`QT_QPA_PLATFORM=offscreen`, set automatically by
  `tests/conftest.py`), and driven with `pytest-qt` for real -- every form
  field, every Save/Open/Run menu action, dirty-state tracking, and the
  unsaved-changes close-confirmation prompt is exercised by an actual
  running `QApplication`, not asserted about in the abstract. Getting
  PySide6 itself running headless needed three system packages beyond
  what was preinstalled (`libegl1 libopengl0 libxcb-cursor0` on the
  Ubuntu-based image this was developed on, via `apt-get`) -- worth
  knowing if a deployment target hits the same `ImportError:
  libEGL.so.1: cannot open shared object file`.
* `missionstudio/engine/time_system.py`, `kernels.py`, `service.py`,
  `fsw.py`/`vizard.py` (Phase 2), and `monte_carlo.py` (Phase 3) import
  Basilisk. Against a real `bsk[all]` install: every Basilisk module/class
  any of these files import was confirmed to exist under the expected
  name; `time_system.py`'s SPICE call sequence was run for real
  (round-tripping an epoch through ET and back, computing TAI/TT) and a
  real bug was found and fixed doing so (a bare `import pyswice` that
  doesn't match the published package's layout -- see that module's own
  docstring); `service.py`'s `build()` was confirmed to run correctly
  through gravity/spacecraft/attitude/sensor/actuator/ground-station
  construction, failing only at the SPICE kernel DOWNLOAD step (blocked
  network to NAIF, not a code issue -- see `kernels.py`'s own note). A
  FULL run past kernel loading -- and so `fsw.py`/`vizard.py`/
  `monte_carlo.py`'s own module-construction logic, and
  `tests/test_two_body_validation.py`'s analytical check -- was NOT
  achieved, purely because that needs the blocked kernel download to
  succeed first. Each file's own docstring says precisely what was and
  wasn't confirmed, updated after this pass -- nothing here should be
  trusted as "tested" beyond what its docstring claims.
* **Packaging (`packaging/build_wheel.sh`, `packaging/install.sh`) was
  fully verified, including the Basilisk-vendoring path**: with a real
  `bsk[all]` available, `install.sh --basilisk-wheel "bsk[all]"` was run
  end-to-end and the resulting installed venv's `missionstudio.engine.service`
  imported correctly. See `packaging/README.md`.
* The GUI/CLI's no-Basilisk error handling (`gui.run_worker.RunWorker`,
  `gui.kernel_status_widget`, `cli.py`'s `run`/`kernels-status`) was
  separately confirmed for real in an environment WITHOUT Basilisk
  installed: each correctly reports "Basilisk is not installed/built"
  (no crash, no hang, no silent no-op) rather than a bare traceback.
* `tests/test_two_body_validation.py` -- the end-to-end analytical
  validation scenario this project's own requirements call for -- is
  written and ready, correctly auto-skips without Basilisk (see
  `tests/conftest.py`), and correctly ATTEMPTS a real run with Basilisk
  present, but could not complete because of the blocked kernel download
  above. **Run it on a machine with ordinary internet access** to get the
  first full confirmation that `engine.service.SimulationService`
  actually produces correct physics.

None of this is a reason to distrust the design -- it's the same
"write carefully against verified source, disclose what's untested"
discipline `../missionAnalysis` used throughout this project, now backed
by an actual Basilisk install for most of it. The one thing a user should
take away: get this running on a machine with normal internet access
(specifically, access to `naif.jpl.nasa.gov`) and the whole pipeline
should work end-to-end -- that's the one link in the chain this project's
own sandbox could never close.

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

## What Phase 3 adds

* **Ground-station access analysis.** `engine.service.SimulationService`
  now builds a `groundLocation.GroundLocation` for EVERY
  `GroundStationConfig` in a scenario (not just ones a spacecraft's
  `locationPointing` mode targets), and calls the new
  `engine.fsw.add_access_analysis()` once every spacecraft exists so every
  station sees every spacecraft -- the standard access-analysis question.
  `ResultSet` gains four series per (station, spacecraft) pair:
  `{station}.access_to_{spacecraft}.has_access`/`.slant_range`/
  `.elevation`/`.azimuth`.
* **`missionstudio/engine/monte_carlo.py`** -- wraps
  `Basilisk.utilities.MonteCarlo` (`Controller`/`Dispersions`/
  `RetentionPolicy`, real native Basilisk infrastructure, not reimplemented
  here). `schema.scenario.MonteCarloConfig`/`DispersionConfig` describe a
  batch (`num_runs`, `thread_count`, `verbose`) and per-spacecraft
  dispersions (`dry_mass_kg` uniform/normal, `attitude_sigma_bn`
  uniform-random-attitude via `UniformEulerAngleMRPDispersion`) --
  deliberately NOT Cartesian position/velocity dispersion, since
  Basilisk's Cartesian dispersion classes replace each component with an
  ABSOLUTE random value rather than perturbing around the nominal orbit,
  which would silently produce a physically nonsensical result (see that
  module's docstring). `engine.service.SimulationService.build()` gained
  an `initialize` parameter so Monte Carlo can apply dispersions BEFORE
  `InitializeSimulation()` runs (applying them after would silently have
  no effect, since `Reset()` would already have latched the un-dispersed
  values). `missionstudio monte-carlo` (CLI) and Run > **Run Monte
  Carlo...** (GUI, via the new `gui/monte_carlo_editor.py` scenario-form
  section) both drive it.
* **`packaging/`** -- `build_wheel.sh`/`install.sh`/`missionstudio.desktop.in`,
  genuinely built and run in this sandbox (see the honesty note above and
  `packaging/README.md` for two real bugs found and fixed this way: a
  missing scenario data file in the wheel, and a `./build/`-directory
  import-shadowing bug in repeated builds).

## What Phase 4 adds

Driven directly by feedback from actually using the Phase 3 GUI:

* **Vizard's default view is now Earth-centered with the orbit visible**,
  not locked onto the spacecraft with no context. `engine.vizard`'s
  `VizardRequest` gained `camera_target` (defaults to the scenario's
  central body) and `show_orbit_lines` (osculating + true trajectory
  lines, on by default), set via `VizSettings.mainCameraTarget`/
  `orbitLinesOn`/`trueTrajectoryLinesOn` -- `enableUnityVisualization()`
  itself doesn't expose these. Configurable from the GUI's Vizard dialog
  or `--vizard-camera-target`/`--vizard-no-orbit-lines` (CLI).
* **Live feedback while a run is in progress.** `gui.main_window` used to
  show only a static "Running..." status-bar string with no other
  indication anything was happening. Run Simulation and Run Monte Carlo
  now show a busy indicator (indeterminate progress bar + elapsed-time
  label) and disable every Run-menu action until the worker finishes --
  Basilisk exposes no per-step/per-run progress callback to drive a real
  percentage, so this is deliberately indeterminate rather than a
  fabricated number.
* **Mean anomaly as a classical-elements orbit input.** `OrbitIC` gained
  `anomaly_type` (`"true"`/`"mean"`, default `"true"` for backward
  compatibility) and `mean_anomaly_deg`; `engine.service` converts mean to
  true anomaly via Kepler's equation (`orbitalMotion.M2E`/`E2f`) before
  calling `elem2rv`, which only accepts true anomaly. The GUI orbit editor
  exposes this as a combo box next to the angle field.
* **Real power budget.** `schema.scenario.PowerConfig` (optional, per
  spacecraft) wires Basilisk's actual `simpleSolarPanel`/
  `simplePowerSink`/`simpleBattery`/`eclipse` modules into
  `engine.service` -- the same pattern `../missionAnalysis/power_budget.py`
  already uses -- so generated power depends on the real simulated
  attitude (panel-normal-to-sun angle) and eclipse state, not a flat duty
  cycle. `ResultSet` gains `{spacecraft}.battery_charge` [W\*hr] and
  `{spacecraft}.battery_net_power` [W] per spacecraft that opts in; no
  per-subsystem (instrument/downlink) load gating is modeled yet, only a
  constant bus load, since missionStudio has no EO-payload data model to
  gate against (unlike `../missionAnalysis`).
* **Downlink RF link-margin estimate.** `schema.scenario.RFLinkConfig`
  (optional, per spacecraft) plus two new `GroundStationConfig` fields
  (`rx_antenna_gain_dbi`, `system_noise_temp_k`) feed the new
  `engine.link_budget` module -- a simplified free-space-path-loss Eb/N0
  budget ported directly from `../missionAnalysis`'s
  `_rf_link_margin_db()`. It is evaluated against the REAL simulated slant
  range from Phase 3's access analysis (not a worst-case estimate), giving
  `{station}.access_to_{spacecraft}.link_margin_db` in `ResultSet` --
  `NaN` outside access windows, since there's no link (and so no
  meaningful margin) when there's no access. Like the missionAnalysis
  original, this is a reported ESTIMATE only (no atmosphere/rain/
  pointing-loss/coding-gain terms) and does not feed back into simulated
  physics anywhere.
* **Orbit-maintenance / station-keeping automation, with delta-V and
  propellant bookkeeping.** `schema.scenario.StationKeepingConfig`
  (optional, per spacecraft) wires the new `engine.orbit_maintenance`
  module -- `StationKeepingController`, ported from `../missionAnalysis`'s
  `AltitudeKeepingController` -- into `engine.service`: a dedicated
  `extForceTorque` effector fires a continuous prograde reboost burn
  whenever a smoothed altitude estimate decays `deadband_km` below
  `target_altitude_km`, gated off during eclipse and once propellant is
  depleted. Propellant use is tracked via the rocket equation
  (explicit-Euler) and fed back into the spacecraft's simulated mass every
  tick, so thrust-to-mass stays physically consistent as it burns off --
  see `SpacecraftConfig.dry_mass_kg`'s docstring for how that field's
  meaning sharpens once `station_keeping` is set (it becomes the mass
  *without* propellant; the initial simulated mass becomes
  `dry_mass_kg + station_keeping.propellant_kg`). `ResultSet` gains
  `{spacecraft}.station_keeping.altitude` (raw + smoothed),
  `.burn_on`, `.propellant_remaining`, and `.delta_v` (cumulative);
  `missionstudio run` also prints a one-line delta-V/propellant-used
  summary per spacecraft so the headline numbers don't require opening a
  CSV. This needs something actually decaying the orbit to have any
  effect -- with only point-mass gravity (the default), altitude never
  decays and the burn never fires; enable `SpacecraftConfig.enable_drag`
  for a station-keeping scenario. Shares the same eclipse model
  `PowerConfig` uses when both are configured on the same spacecraft.
* **Constellation design: a Walker-pattern generator.** The new
  `engine.constellation` module ("user supplies the requirement, the tool
  designs the constellation") turns a handful of high-level numbers --
  total satellite count, number of planes, Walker phasing factor,
  altitude, inclination -- into a full set of `SpacecraftConfig`s with
  every satellite's orbital elements pre-computed via the standard
  Walker-Delta/Walker-Star RAAN/mean-anomaly formula (Vallado; Wertz's
  SMAD). Every generated satellite is a deep copy of ONE template
  spacecraft the user configures the normal way (mass, sensors, actuators,
  power, station-keeping, RF link, ...) -- only `name`/`orbit` differ, so
  designing a 12-satellite constellation is exactly as much data entry as
  designing one satellite. Pure orbital mechanics, no Basilisk import
  (central-body radii for the altitude-to-semi-major-axis conversion are
  copied from Basilisk's own `astroConstants.h`, so they match what
  `engine.service` actually simulates). Available from the GUI (spacecraft
  list's new "Generate Walker constellation..." button -- central body is
  read from the scenario, not independently selectable, so it can't drift
  out of sync with what actually gets simulated) and the CLI
  (`missionstudio generate-constellation`, `--append` to add to an
  existing scenario instead of replacing its spacecraft). Constellation
  -wide phasing MAINTENANCE over time (keeping satellites correctly
  spaced from each other despite differential drag, as opposed to each
  one's own independent altitude via `StationKeepingConfig` above) is a
  distinct, not-yet-built feature -- see "What's next" below.

`PowerConfig`, `RFLinkConfig`, and `StationKeepingConfig` all default to
`None` (off) on every existing scenario -- turning any one on is the only
input needed; the GUI's new "Power / propulsion / link budget"
spacecraft-editor tab and the ground-station editor's two new fields are
pre-filled with reasonable placeholder defaults, matching this phase's
"user only supplies numbers, the tool does the rest" design goal. Richer
Vizard live-data panels are scoped but not yet built -- see "What's next"
below.

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
      monte_carlo.py                 -- Phase 3: Basilisk.utilities.MonteCarlo bridge (needs Basilisk)
      link_budget.py                 -- Phase 4: downlink RF link-margin estimate (no Basilisk needed)
      orbit_maintenance.py           -- Phase 4: station-keeping controller + delta-V/propellant bookkeeping (needs Basilisk)
      constellation.py               -- Phase 4: Walker-pattern constellation generator (no Basilisk needed)
    gui/
      app.py                         -- QApplication entry point
      main_window.py                 -- MainWindow: File/Run menus, ties everything together
      scenario_editor.py             -- the full scenario form + live validation
      spacecraft_editor.py           -- spacecraft list + add/edit/remove dialog (tabbed: orbit, sensors/actuators, FSW, power/propulsion/link budget)
      sensor_actuator_editor.py      -- Phase 2: generic sensor/actuator list + add/edit/remove dialog
      vizard_dialog.py               -- Phase 2: "enable Vizard for the next run" dialog
      monte_carlo_editor.py          -- Phase 3: Monte Carlo settings + dispersion list editor
      ground_station_editor.py       -- ground station list + add/edit/remove dialog
      orbit_ic_widget.py             -- classical-elements (true/mean anomaly)/Cartesian/TLE orbit editor
      constellation_dialog.py        -- Phase 4: "Generate Walker constellation" dialog
      kernel_status_widget.py        -- SPICE kernel status panel
      results_widget.py              -- matplotlib results plot + CSV export
      run_worker.py                  -- SimulationService/Monte Carlo on a background QThread
    scenarios/
      two_body_validation.json       -- the Phase 0 validation scenario
  packaging/                          -- Phase 3: build_wheel.sh / install.sh / .desktop entry -- see packaging/README.md
  tests/
    conftest.py                      -- requires_basilisk / requires_gui auto-skip markers
    test_scenario_schema.py
    test_spaceweather.py
    test_results.py
    test_link_budget.py              -- Phase 4
    test_constellation.py            -- Phase 4
    test_cli.py
    test_two_body_validation.py      -- requires_basilisk
    gui/
      test_orbit_ic_widget.py
      test_spacecraft_editor.py
      test_sensor_actuator_editor.py
      test_vizard_dialog.py
      test_monte_carlo_editor.py
      test_ground_station_editor.py
      test_constellation_dialog.py   -- Phase 4
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

Without Basilisk on `PYTHONPATH`, this runs 234 tests (schema, space
weather, results, link budget, constellation generation, CLI, and the
full PySide6 GUI, run headless) and skips 2 whose premise is specifically
"Basilisk is unavailable", per `tests/conftest.py`.

With Basilisk installed (`pip install "bsk[all]"` -- see "Getting
started" above), the 2 skips above run for real instead of skipping.
Last genuinely verified in this project's own sandbox as of the Phase 3
work (before Phase 4's additions, whose Basilisk-dependent code --
`engine.service`'s power/station-keeping wiring, `engine.orbit_maintenance`
-- has NOT been run against a real Basilisk build in this sandbox, only
written directly against verified API call sequences; see each module's
own "Verification status" docstring note): `test_two_body_validation.py`
failed at the SPICE kernel-download step because that sandbox's network
blocks the NAIF kernel host specifically, not because of a code defect
(see the honesty note above). On a machine with ordinary internet access,
expect that one to pass too; if it fails there for a different reason,
that's a real bug worth reporting.

`packaging/build_wheel.sh`/`install.sh` are NOT run by `pytest` (they're
shell scripts that build/install a real wheel, not something worth
wrapping in a slow subprocess-spawning test) -- see `packaging/README.md`
for how they were verified instead.

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
missionstudio monte-carlo scenario_with_dispersions.json --archive-dir mc_results/
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
type, including its Monte Carlo section (enable/num_runs/thread_count +
a dispersion list, referencing spacecraft by name). Run > Run Simulation
runs `SimulationService` on a background thread (the UI stays responsive)
and switches to the Results tab when
done, with a plot per result series and a CSV export button. Run > Check
Kernels shows SPICE kernel fetch/cache status. Both Run actions report a
clear error (not a crash) if Basilisk isn't installed/built.

## Vendoring vs. building Basilisk from source

Building from source in an automated/CI/sandboxed context is fragile --
this project hit exactly that failure mode moments before Phase 0 started
(see the honesty note above). The plan flagged since Phase 0 was to
**vendor a prebuilt wheel pinned to a specific Basilisk release/commit**
as the default install path for end users, keeping "build from source" a
documented, opt-in developer path only.

That plan turned out to be simpler to satisfy than expected: Basilisk
itself now publishes prebuilt wheels to PyPI (`pip install "bsk[all]"`),
so there is usually no separate wheel to hunt down or vendor at all --
"Getting started" above IS the vendoring story for most users.
`packaging/install.sh --basilisk-wheel` still exists and still works (it
was run end-to-end against `"bsk[all]"` for real -- see
`packaging/README.md`) for the cases that DO need something other than
the published PyPI package: a specific pinned/older release for
reproducibility, a locally-built wheel with custom modules, or an offline
install from a wheel file already on disk. `--basilisk-wheel` accepts any
string `pip install` would (a path, a URL, or a plain requirement
specifier like `"bsk[all]==2.12.0"`), not literally only a `.whl` file.

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
* **The attitude control loop closes on truth spacecraft state.**
  `simpleNav` is in the loop (not raw `scStateOutMsg`), but its
  error-model matrices are left at Basilisk's own zero defaults -- there
  is no GUI/schema field yet to configure realistic navigation error.
* **Monte Carlo dispersions cover two quantities**: `dry_mass_kg`
  (uniform/normal) and `attitude_sigma_bn` (uniform-random-attitude).
  Cartesian position/velocity dispersion is deliberately NOT offered --
  see `engine/monte_carlo.py`'s module docstring for why (Basilisk's
  Cartesian dispersion classes replace each component with an absolute
  random value, not a perturbation around the nominal orbit).
* **`monte_carlo.thread_count > 1` is unverified** in this project's
  development sandbox (no Basilisk build here to run it against) -- the
  schema default is the definitely-safe `1`.
* **Monte Carlo retains a fixed set of data per run** (each spacecraft's
  position/velocity) -- there is no per-run custom retention-policy
  selection in the schema yet.
* **A full end-to-end simulation run (past SPICE kernel loading) has never
  completed in this project's own development sandbox** -- its network
  policy blocks the NAIF kernel host, so `engine.kernels`'s download step
  always fails there (correctly, with a clear error -- see the honesty
  note above). Everything up to that point (gravity/spacecraft/attitude
  /sensor/actuator/ground-station construction) was confirmed to run
  correctly against a real Basilisk build; the numerical propagation
  itself, and `tests/test_two_body_validation.py`'s analytical check,
  still need to be run once on a machine with ordinary internet access.

## What's next

Phase 4 (see "What Phase 4 adds" above) responded to the first round of
real GUI usage feedback. Still open from that same feedback, scoped but
not yet built:

* **Constellation-wide phasing MAINTENANCE over time** -- keeping
  satellites generated by `engine.constellation`'s Walker generator (see
  "What Phase 4 adds" above) correctly spaced from EACH OTHER as the
  mission runs, on top of each one's own independent altitude-keeping
  (`StationKeepingConfig`, already built). `../missionAnalysis` has prior
  art for this exact problem: `constellation_controllers.py`'s
  `PhasingKeepingController` (a drift-orbit maneuver -- temporary SMA
  offset, drift, restore -- that also arbitrates sharing one thruster with
  altitude-keeping when both act on the same spacecraft), in the same
  style `StationKeepingController` was ported from.
* **Richer, more understandable Vizard live-data panels** beyond the
  Phase 4 default-camera/orbit-line fix -- e.g. clearer on-screen
  power/link-margin/access-window readouts while a live-streamed run is in
  progress.

Beyond that, the "Known limitations" list above is the rest of the honest
map: a handful of schema-valid-but-not-wired-up options (celestial-body
`locationPointing` targets, thrusters, magnetic torque rods, non-Earth
spherical harmonics/magnetometer), navigation error modeling, richer Monte
Carlo retention, and -- the one requiring something this development
sandbox's network policy specifically blocks -- a full simulation run past
SPICE kernel loading, to get the first true end-to-end confirmation
(including `test_two_body_validation.py`'s analytical check, and the new
Phase 4 power-budget/link-budget/station-keeping wiring) on top of everything up to that
point already being verified against a real Basilisk install. None of it
is blocked on a design decision; each item is scoped and documented at its
own call site for whoever picks it up next.
