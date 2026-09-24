# missionStudio (Phase 4)

A standalone, GUI-based mission-analysis application for Linux, using the
Basilisk astrodynamics framework (AVS Lab, University of Colorado Boulder)
as its sole simulation/dynamics engine. Think "STK/FreeFlyer-lite" --
every capability maps to a specific Basilisk module (see the capability
matrix delivered earlier in this project's history) or is explicitly
flagged as custom/out-of-scope, never fabricated.

This is **Phase 4** of the roadmap: usability fixes and mission-analysis
outputs driven directly by real GUI usage feedback -- a more informative
Vizard default view (including live data panels), live run/Monte Carlo
progress feedback, mean-anomaly orbit input, real power-budget/link
-budget/station-keeping/phasing-keeping results, and a Walker-pattern
constellation generator -- on top of Phase 0's backend foundations, Phase
1's PySide6 GUI/CLI, Phase 2's attitude/sensors/actuators/Vizard work, and
Phase 3's Monte Carlo + ground-station access analysis + packaging. See
"What Phase 4 adds" below for exactly what that means.

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
  existing scenario instead of replacing its spacecraft).
* **Constellation-wide phasing maintenance, with its own delta-V and
  propellant bookkeeping.** `schema.scenario.PhasingKeepingConfig`
  (optional, per follower spacecraft) wires
  `engine.orbit_maintenance.PhasingKeepingController` -- ported from
  `../missionAnalysis`'s controller of the same name -- to hold a
  follower's along-track separation from a `chief_spacecraft` at a target
  value (optionally stepped through a schedule of several values over the
  mission, e.g. tightening a formation from 1000 km to 100 km every few
  months) via a drift-orbit maneuver: a small temporary semi-major-axis
  offset, natural drift, then a restoring burn -- the same technique a
  differential corrector (GMAT's Target/Vary/Achieve) would normally
  automate, done here as a direct two-body calculation re-evaluated every
  tick. REQUIRES `station_keeping` to also be set on the same spacecraft:
  phasing and altitude-keeping share ONE physical thruster and propellant
  tank (this config deliberately has no `thrust_n`/`isp_s`/`propellant_kg`
  fields of its own -- `engine.service` reads those off `station_keeping`
  instead), with altitude-keeping taking priority whenever both want to
  fire on the same tick. `ResultSet` gains
  `{spacecraft}.phasing_keeping.separation_error`/`.state`/`.delta_v`
  (its own delta-V, tracked separately from -- but drawing from the same
  shared tank as -- `station_keeping`'s); `missionstudio run`'s
  delta-V/propellant summary line now includes a breakdown when both are
  configured. Not yet wired into `engine.constellation`'s Walker generator
  automatically (each follower's chief/target-separation still needs
  setting up by hand in the spacecraft editor after generating the
  constellation) -- a natural follow-on if that manual step turns out to
  be tedious in practice.
* **Live Vizard data panels**, responding directly to "the live-stream of
  the simulation with Vizard is not really understandable, improve" --
  three real, already-simulated data feeds now drive native Vizard HUD
  elements (`engine.vizard`, extended), not a static snapshot or an
  analytical estimate:
  * **Battery state of charge**, for any spacecraft with `PowerConfig` --
    a `GenericStorage` bar panel wired straight to that spacecraft's
    `simpleBattery.SimpleBattery.batPowerOutMsg`.
  * **Station-keeping propellant remaining**, for any spacecraft with
    `StationKeepingConfig` -- a second `GenericStorage` panel, fed by a
    new `FuelTankMsgPayload` output
    `engine.orbit_maintenance.StationKeepingController` now publishes
    specifically for this (that controller still doesn't use a Basilisk
    `fuelTank` state effector for the actual physics -- see its own
    docstring).
  * **Ground-station access windows** -- one `GenericSensor` marker per
    (station, spacecraft) pair Phase 3's access analysis tracks, changing
    color live between "no access"/"access" as the real, already
    -simulated `hasAccess` flag changes, via a small bridge module this
    phase adds (`GenericSensor` takes an integer mode, not a boolean, so
    something has to republish `hasAccess` as one -- see `engine.vizard`'s
    docstring for exactly how and why 0/2, not 0/1, are the two values
    used).

  The battery/propellant panel pattern is copied line-for-line from a
  real, shipped Basilisk example
  (`examples/MultiSatBskSim/scenariosMultiSat/scenario_StationKeepingMultiSat.py`);
  the access-window bridge composes verified pieces
  (`examples/scenarioGroundLocationImaging.py`'s `GenericSensor`/
  `DeviceCmdMsgPayload` wiring, `../missionAnalysis/attitude_controllers.py`'s
  `AccessMsgReader` usage) in a way that's this module's own, not copied
  from one example -- like the Phase 4 camera/orbit-line work, none of
  this has been checked against a real running Vizard display (no display
  in this development sandbox). A live **link-margin** panel was
  considered and deliberately NOT built: Vizard's `GenericStorage` only
  accepts Battery/DataStorage/FuelTank-shaped messages, and forcing a dB
  margin value through the DataStorage shape would need a fabricated
  adapter message with no natural floor/ceiling -- the link-margin numbers
  stay exactly where they already were (the plotted/exported
  `.link_margin_db` series from `engine.link_budget`), which is the
  honest choice over a misleading gauge.

`PowerConfig`, `RFLinkConfig`, `StationKeepingConfig`, and
`PhasingKeepingConfig` all default to `None` (off) on every existing
scenario -- turning any one on is the only input needed; the GUI's new
"Power / propulsion / link budget" spacecraft-editor tab (its "Phasing
keeping" group reads the chief-spacecraft choice from the OTHER
spacecraft already in the scenario, not a free-text field, so it can't
name one that doesn't exist) and the ground-station editor's two new
fields are pre-filled with reasonable placeholder defaults, matching this
phase's "user only supplies numbers, the tool does the rest" design goal.

Four real bugs were found by a full codebase audit after this phase
shipped, and fixed (all visible in `git log` for the files below, not
swept under the rug):

* **`SpacecraftConfig.enable_drag`/`enable_srp` were schema-valid and
  documented above as functional (see the station-keeping bullet's
  "enable `enable_drag`" instruction) but were never actually wired into
  `engine.service` -- station-keeping's reboost burn could never fire on
  any scenario, since nothing ever decayed the orbit.** Fixed: `enable_drag`
  now wires `engine.spaceweather`'s resolver into `spaceWeatherData` ->
  `msisAtmosphere` -> `zeroWindModel` -> a per-spacecraft
  `dragDynamicEffector`, ported from
  `../missionAnalysis/run_constellation_mission.py`'s verified chain;
  `enable_srp` wires a per-spacecraft `radiationPressure` effector off the
  same eclipse model `PowerConfig`/`StationKeepingConfig` already share.
  Both are Earth-only (NRLMSISE-00 has no other-body atmosphere model
  here), matching the spherical-harmonics-gravity precedent.
* **`_AccessIndicatorBridge` (the Live Vizard access-window indicator
  above) could be garbage-collected while still registered on the
  Basilisk sim task** -- a SWIG-director use-after-free (the Python side
  of a custom `SysModel` must outlive its C++ task registration, same
  requirement `StationKeepingController`/`PhasingKeepingController`
  already followed), surfacing as a `basic_string::_M_create` crash deep
  in an unrelated libstdc++ call, well after the actual corruption.
  Fixed: `engine.vizard`/`engine.service` now retain it the same way.
* **Editing an existing spacecraft with `enable_drag`/`enable_srp` already
  set silently reset them to the schema defaults** -- the spacecraft-editor
  dialog has no UI for these fields (by design, per above) but also never
  carried them through from the original config in `to_dataclass()`, unlike
  every other not-yet-editable field. Fixed.
* **The phasing-keeping chief-spacecraft combo, and the Monte Carlo
  dispersion spacecraft combo, silently fell back to whichever spacecraft
  happened to be first** whenever the stored name didn't match a current
  spacecraft (e.g. renamed after the config was saved) -- re-targeting a
  controller or dispersion at the wrong spacecraft with no visible
  indication. Fixed: the stale name is now surfaced as its own selectable
  entry and round-tripped as-is instead.

## What Phase 5 adds

Driven directly by feedback from actually using the Phase 4 GUI + engine
(this phase is in progress; bullets are added as pieces land):

* **Result plots/CSV export now include osculating Keplerian elements**,
  not just inertial position/velocity. `engine.service` computes semi-major
  axis, eccentricity, inclination, RAAN, argument of periapsis, and true
  anomaly at every recorded sample (`orbitalMotion.rv2elem`, the exact
  inverse of the classical-elements orbit-IC conversion already used
  elsewhere in this file) and adds them to `ResultSet` as
  `{spacecraft}.orbit_elements.{semi_major_axis,eccentricity,inclination,
  raan,arg_periapsis,true_anomaly}` -- one series per element (mixed units:
  m/-/rad), matching the existing convention for e.g.
  `station_keeping.burn_on`/`.delta_v`. `gui.results_widget`/the CLI's CSV
  export need no changes for these to show up -- both are already driven
  generically by whatever `ResultSet.series` contains. Near-circular
  and/or near-equatorial orbits have an inherent singularity in RAAN/
  argument of periapsis/true anomaly (see
  `engine.service._osculating_elements`'s docstring) -- not a bug, just
  how classical elements behave at those limits.
* **Sensor/actuator/FSW-mode setup is no longer a blank JSON box with zero
  guidance.** User feedback: configuring a spacecraft's sensors, actuators,
  and attitude-control mode was "confusing and not beginner friendly" --
  each dialog offered only a Kind/mode combo and an empty `{}` params box,
  so a user had to already know (by reading `engine/fsw.py`'s source)
  which JSON keys a given kind needs, their units, and which are required.
  A missing required key (e.g. `coarse_sun_sensor`'s `nHat_B`,
  `reaction_wheel`'s `gsHat_B`, `locationPointing`'s
  `target_ground_station`) wasn't caught there either -- only much later,
  decontextualized, when the whole spacecraft dialog's
  `SpacecraftConfig.validate()` ran (sensors/actuators) or not at all
  until `Run Simulation` actually failed deep inside `engine.fsw`
  (FSW mode). Fixed in both `gui.sensor_actuator_editor` and
  `gui.spacecraft_editor`'s FSW tab: a per-kind/per-mode help label (key
  name, required/optional, units, one-line description) that updates live
  as the Kind/FSW-mode combo changes; a new spacecraft/sensor/actuator
  starts pre-filled with a working example instead of `{}`; a "Reset to
  template" button refills the params box for the CURRENTLY selected
  kind/mode on demand (switching kind never silently overwrites what's
  already typed, to avoid destroying in-progress edits); and both dialogs
  now check required keys themselves and raise an immediate, specific
  error naming exactly what's missing, right where the params box is.
  `SUPPORTED_ACTUATOR_KINDS`'s `"thruster"`/`"magnetic_torque_rod"`
  (schema-valid but not wired up -- see the Phase 0 section above) and
  `locationPointing`'s `fsw_params["target_body"]` option now show an
  explicit in-dialog warning instead of silently accepting a
  configuration that fails only when the simulation actually runs.
* **Sensor/actuator body-frame direction vectors get dedicated X/Y/Z spin
  boxes**, not a bare 3-element array inside the params JSON box -- see
  `gui.sensor_actuator_editor`'s module docstring for exactly why
  DIRECTION (not position) is the one thing about sensor/actuator
  "placement" that actually affects the physics these Basilisk modules
  simulate here, plus a Normalize button since Basilisk does not
  renormalize a non-unit vector itself.
* **Reusable spacecraft "bus" templates.** A brand-new spacecraft used to
  start from `SpacecraftConfig()`'s bare dataclass defaults (100 kg, flat
  10 kg*m^2 inertia, no sensors/actuators/power/attitude control) -- a
  placeholder, not anything resembling a real vehicle. The new
  `engine.spacecraft_templates` module (pure schema data, no Basilisk
  import, same split as `engine.constellation`) ships three starting
  points -- a passive 3U CubeSat (drag/SRP enabled, no ADCS, good for
  orbit-only delta-V/lifetime studies), a 3-axis-stabilized 3U CubeSat
  (coarse sun sensor + 3 reaction wheels + `sunSafePoint` + a small power
  budget), and a 100 kg ESPA-class smallsat (star tracker + coarse sun
  sensor + 3 reaction wheels + `inertial3D` + a ~1 m-class power budget) --
  each internally consistent and validated, with rounded,
  order-of-magnitude-reasonable numbers (never a fabricated-precision
  datasheet figure; see that module's docstring). The spacecraft list's
  new "New from template..." button (next to "Add...") opens a small
  picker, then the ordinary `SpacecraftEditorDialog` pre-filled with the
  chosen template so the user still sets the actual name/orbit/anything
  else themselves, exactly like editing any other spacecraft.
* **Custom 3D models in Vizard.** The last piece of "adequately represent
  the correct placement" feedback: `SpacecraftConfig.vizard_model_path`
  (plus `vizard_model_offset_m`/`_rotation_deg`/`_scale`) wires
  `Basilisk.utilities.vizSupport.createCustomModel()` in, replacing a
  spacecraft's default cube icon with a real `.obj` mesh (or Vizard's
  `CUBE`/`CYLINDER`/`SPHERE` primitives) at a chosen body-frame offset/
  rotation/scale. PURELY COSMETIC -- it changes nothing about simulated
  physics (mass, drag/SRP area, etc. are unaffected either way); the
  spacecraft editor's new "Vizard model (cosmetic)" tab says so up front,
  same "don't offer a control that looks like it does something it
  doesn't" discipline as everywhere else in this app.
* **Orbit-only simulation mode, plus a constant-frame thrust maneuver.**
  `Scenario.simulation_mode` ("full_attitude", the default and everything
  this schema always supported, or "orbit_only") is the first field in
  the scenario editor's form, chosen before anything else per the
  feature request this responds to. "Orbit only" is a stricter,
  beginner-friendly mode for pure orbit-propagation questions (delta-V
  budgets, orbit lifetime, station-keeping cadence, ...): no spacecraft
  may have `fsw_mode`/`sensors`/`actuators`/`power` set (`Scenario.
  validate()` rejects it with a specific per-field error), so the
  spacecraft editor hides the Sensors/actuators and FSW tabs and the
  Power budget group while it's selected -- the spacecraft is simulated
  as a cannonball with `drag_area_m2`/`srp_area_m2` (which finally got a
  real editor too, on the Orbit/mass tab -- previously round-tripped only,
  with no UI to actually SET them anywhere) as its average cross-section.
  `station_keeping`/`phasing_keeping`/the new `constant_thrust` remain
  available in EITHER mode, since none of them need attitude knowledge.

  `SpacecraftConfig.constant_thrust` is new: a continuous (always-on),
  constant-magnitude thrust with a fixed direction in a ROTATING orbit
  frame -- VNB (velocity/orbit-normal/binormal) or RTN (radial/
  transverse/orbit-normal), re-evaluated every simulation tick from the
  spacecraft's current state (`engine.orbit_maintenance._vnb_basis`/
  `_rtn_basis`) -- rather than a direction fixed in the inertial frame,
  which would drift relative to the orbit as the spacecraft moves. Delta
  -V/propellant bookkeeping mirrors `StationKeepingConfig`'s own rocket
  -equation approach (station-keeping's burn model itself is UNCHANGED --
  still a fixed prograde reboost -- this is a separate, independent
  mechanism with its own propellant tank, addable alongside station
  -keeping on the same spacecraft). `missionstudio run` prints a
  "Constant-thrust summary" line per spacecraft, same idea as the
  existing station-keeping summary.
* **A real visual theme, an app icon, a toolbar, and assorted UI polish.**
  Direct user feedback: "looks very unfinished... not very intuitive and
  comfortable". The app previously ran on whatever the platform's native
  Qt style happened to render, with no icon and no toolbar. Now:
  * `gui/theme.py` -- one QSS stylesheet + palette (`apply_theme()`,
    called once from `gui/app.py`), on top of Qt's "Fusion" base style
    (the one built-in style that renders identically, and predictably
    styleable via QSS, across Linux/macOS/Windows). A small, consistent
    color system (one neutral slate scale + one accent blue, reused
    everywhere -- focus rings, selection highlight, the primary action
    button, progress bars) rather than per-widget rules picked ad hoc.
    Pure presentation layer: no widget's behavior, signals, or layout
    structure changed because of it.
  * `gui/icons.py` -- the app icon, drawn procedurally with `QPainter`
    (a central body + an inclined orbit ellipse + a satellite dot) rather
    than shipped as a bitmap asset, so there's no binary file to keep in
    sync with the theme's colors. Used as the window/taskbar icon
    (`app.py`) and, rendered to a real PNG under the standard XDG
    hicolor icon theme location, the Linux desktop entry's icon
    (`packaging/install.sh`, closing a gap that `Icon=missionstudio` was
    falling back to a generic icon).
  * `MainWindow` gained a toolbar (New/Open/Save, Run Simulation/Monte
    Carlo/Vizard/Check Kernels) using the SAME `QAction` instances the
    menu bar already had -- one signal connection each, so toolbar and
    menu always agree, including which actions are disabled while a run
    is in flight. "Run Simulation" is visually the primary action
    (accent-colored), the same "one obvious main button" convention a
    web app would use.
  * The results panel used to be a blank white plot with no explanation
    before any run -- now shows "Run a simulation to see results here".
  * `SpacecraftEditorDialog`'s five tabs used to share ONE height (a
    `QTabWidget` sizes every tab to fit whichever page is tallest, a
    real, easy-to-miss Qt behavior -- the "Power / propulsion / link
    budget" tab's five stacked groups forced "Orbit / mass", a third the
    height, to render with a large dead-space gap, and pushed the whole
    dialog's natural size to over 1000px tall). Caught by actually
    rendering the dialog and looking at it, not from reading the layout
    code. Fixed: each tab now scrolls independently (`_scrollable()`),
    same pattern `gui.scenario_editor.ScenarioEditorWidget`'s own
    top-level form already used.
  * The Monte Carlo group box was labeled "Monte Carlo (Phase 3)" --
    internal development-phase numbering with no meaning to an end user,
    now just "Monte Carlo".
* **Fixed a silent mass-bookkeeping bug found by a full-codebase audit.**
  `StationKeepingController`/`PhasingKeepingController`/
  `ConstantFrameThrustController` each used to recompute an ABSOLUTE
  `scObject.hub.mHub = dryMass + propellant` every tick, from their own
  construction-time-captured belief about the spacecraft's mass. That's
  fine in isolation, but two real, previously-silent failure modes fall out
  of it: (1) `station_keeping` and the new `constant_thrust` are an
  explicitly supported combination on the same spacecraft, and whichever
  controller's `UpdateState` happened to run last each tick would overwrite
  `hub.mHub`, discarding the other controller's propellant burn entirely;
  (2) a Monte Carlo `dry_mass_kg` dispersion writes directly to `hub.mHub`
  before any controller's first tick (see `engine.monte_carlo`'s "why
  `SimulationService.build(initialize=False)`" docstring section) -- the
  very first `UpdateState` call would then silently reset that dispersed
  mass back to the nominal, undispersed value, quietly defeating the
  dispersion for the rest of the run. Fixed at the root: all three
  controllers now read the spacecraft's CURRENT total mass at the top of
  each tick and subtract only what THIS tank burns THIS tick -- a
  self-contained delta, order-independent no matter how many other
  controllers or a prior dispersion already touched the same mass. The
  shared fix lives in a new `engine.propellant_bookkeeping.
  apply_propellant_burn()` (pure math, no Basilisk import -- same "pure
  math, no Basilisk" split as `engine.constellation`/
  `engine.spacecraft_templates`, and for the same reason:
  `engine.orbit_maintenance` itself can never be unit-tested in a sandbox
  without a Basilisk build, so factoring the actual arithmetic out is what
  makes `tests/test_propellant_bookkeeping.py`'s regression coverage for
  this bug possible at all).
* **A live-updating Results plot.** Previously the plot stayed on "Run a
  simulation to see results here" for the entire duration of a run, then
  jumped straight to the finished result -- no feedback beyond the
  indeterminate busy bar for however long the run took. `engine.service.
  SimulationService` gained `run_live(on_progress, live_step_s=None)`: a
  variant of `run()` that executes the simulation in small time chunks
  (repeated `ConfigureStopTime()`/`ExecuteSimulation()` pairs -- a
  documented, supported Basilisk pattern, since `ExecuteSimulation()`
  always resumes from wherever it last stopped rather than restarting)
  instead of one uninterrupted call, calling `on_progress(partial_result,
  fraction_complete)` after each chunk. Recorders keep accumulating
  samples across chunks exactly as they would across one call, so each
  chunk's result is genuinely "whatever has been logged so far", not a
  separate/approximate bookkeeping path from `run()` -- confirmed by
  `tests/test_service_run_live.py`, which checks a chunked `run_live()`
  run reproduces a plain `run()` run's final position/velocity exactly.
  The new "Live Plot" toggle (Run menu and toolbar, on by default)
  controls whether `gui.run_worker.RunWorker` drives the run through
  `run_live()` (emitting a new `progress` Qt signal per chunk, connected
  to `gui.results_widget.ResultsWidget.set_live_result()`) or the
  original one-shot `run()`; the status bar's busy indicator also becomes
  a real 0-100% progress bar instead of the indeterminate one whenever
  Live Plot is on, since `run_live()` is the one case where a genuine
  completion fraction exists. `set_live_result()` deliberately never
  rebuilds the series dropdown once it already holds the running result's
  series names (which are fixed from the first chunk -- only the amount
  of data grows), so watching a live run doesn't keep resetting whichever
  series the user is currently looking at.
* **Another full-codebase audit, this time with real fan-out coverage.**
  A single-pass review of the live-plot/mass-bookkeeping commits found
  and fixed two issues in `engine.service.run_live()`: a scenario whose
  `duration_days` is small enough to round to 0 ns via `macros.sec2nano()`
  (schema-valid -- `sim_settings.validate()` only requires `> 0`) used to
  raise a bare `ZeroDivisionError` computing `fraction_complete` instead
  of a clear error; and `_LIVE_DEFAULT_FRAMES` was lowered from 200 to 60,
  since each live callback's `_extract_results()` redoes O(samples-so-far)
  work from the FULL recorder history rather than just the new samples,
  so total extraction cost scaled with frame count. A follow-up pass
  fanned out across the rest of the codebase (GUI layer, remaining engine
  modules, schema/CLI/packaging) and found six more real, independently
  -verified bugs:
  * `gui.main_window._on_run_finished` called `ResultsWidget.set_result()`
    instead of `set_live_result()` -- so the moment a live-watched run
    actually finished, whichever series the user had selected to watch
    snapped back to the first one, undoing the whole point of
    `set_live_result()`'s selection-preserving design at the one moment
    the final data matters most.
  * `gui.kernel_status_widget.KernelStatusWidget.refresh()` had no
    re-entrancy guard: `MainWindow`'s "Check Kernels" menu/toolbar action
    calls it directly, independent of `refresh_button`'s own disabled
    -while-fetching state, so triggering it again mid-fetch reassigned
    `self._worker`, dropping the only Python reference to the
    still-running (unparented) `QThread` -- a real Qt crash risk ("QThread:
    Destroyed while thread is still running"). Now a no-op while a fetch
    is already in flight.
  * `gui.main_window.MainWindow.closeEvent` never checked whether
    `_run_worker`/`_mc_worker` was still running before accepting the
    close -- starting a run doesn't mark the scenario dirty, so closing
    the window mid-run (no cooperative-cancellation hook exists for a
    synchronous `SimulationService.run()`/`run_live()`/`run_monte_carlo()`
    call) could tear down the process out from under a live `QThread`.
    Now refuses to close (with a clear message) while either worker is
    running.
  * `engine.spaceweather.validate_file()`'s `covers_range` check compared
    a date-only (midnight) timestamp parsed from the CSV's last row
    against a full `end_utc` datetime that can carry a non-zero
    time-of-day (`scenario.epoch_utc` isn't required to be midnight) --
    so a CelesTrak file that genuinely covered the scenario's end date
    was often misclassified as not covering it, forcing an unnecessary
    fallback to synthetic (fabricated) space weather. Fixed to compare
    calendar dates.
  * `engine.time_system.utc_iso_to_spice_string()` hardcoded a literal
    `.000` milliseconds field instead of deriving it from `epoch_utc`,
    silently discarding any sub-second precision a user specified.
  * `cli.py`'s `cmd_spaceweather_resolve` had no exception handling
    around `sw.resolve()` (every other command in the file does), and
    `engine.monte_carlo.run_monte_carlo()`'s `archive_dir.mkdir(...)`
    sat outside its own `try`/`except` -- both let a real, reachable
    failure (a missing `local_file_path`; `--archive-dir` already
    existing as a plain file) surface as a raw traceback instead of this
    project's "ERROR: ..." + specific exit code convention. Both now
    report cleanly.
  * `packaging/install.sh` picked the just-built wheel with
    `ls | tail -n1` (lexicographic order) -- since `build_wheel.sh` never
    cleans its output directory, re-running `install.sh` against the same
    `--prefix` after a version bump left old and new wheels side by side,
    and `"...-1.10.0..."` sorts BEFORE `"...-1.9.0..."` as a string,
    silently installing the OLDER version. Fixed to pick by modification
    time (`ls -t`) instead, so the wheel `build_wheel.sh` just built is
    always the one selected.
* **A dedicated "Propagation setup" window, and an explicit on/off switch
  for every perturbation.** Direct feedback: gravity/integrator/space
  -weather settings were three separate, always-visible group boxes
  buried in the middle of the main scenario form, and spherical-harmonics
  gravity had no explicit enable control -- unchecking it meant zeroing
  out (and losing) whatever degree/order the user had typed. Fixed:
  * New `gui.propagation_setup_dialog.PropagationSetupDialog` -- one
    window for everything that governs how a scenario's orbits
    propagate: central body, gravity model, the numerical integrator/
    step/duration, and the space-weather source atmospheric drag reads.
    `gui.scenario_editor.ScenarioEditorWidget`'s main form now shows a
    compact read-only summary of the current settings plus a single
    "Edit Propagation Setup..." button that opens it, replacing the three
    scattered group boxes.
  * Every perturbation this app actually wires up in `engine.service` now
    has its own explicit on/off control: a new "Enable spherical
    -harmonics gravity" checkbox (GUI-only concept -- `schema.scenario.
    GravityConfig` still has just the one `central_body_degree` field,
    `0` still means point-mass; the checkbox folds back into it on OK,
    but the spin box's value is never reset by unchecking it, so
    re-checking it brings the same degree/order right back); third-body
    point-mass perturbers (already a per-body checkbox list, moved into
    the new dialog unchanged); atmospheric drag and solar radiation
    pressure (`enable_drag`/`enable_srp`, already per-spacecraft -- see
    below for why). The harmonics checkbox is also auto-disabled (and
    unchecked) whenever the central body isn't Earth, since
    `engine.service.build()` only has gravity-field data (GGM03S) for
    Earth -- the GUI can no longer construct that invalid combination in
    the first place, rather than letting the user discover it only when
    a run fails.
  * **Cannonball (orbit-only) mode already exposed every spacecraft
    parameter the active perturbations need** -- confirmed, not new:
    `dry_mass_kg`, `drag_coeff`/`drag_area_m2`, and `srp_coeff`/
    `srp_area_m2` all live on `SpacecraftEditorDialog`'s "Orbit / mass"
    tab, which (unlike Sensors/actuators/FSW/Power) is never hidden in
    "orbit_only" mode, from Phase 5's earlier drag/SRP work.
  * Caught while rendering the new dialog and looking at it, not from
    reading the layout code (same discipline as every other UI bug this
    project has found this way): a word-wrapped `QLabel`'s `sizeHint()`
    reports the width needed to lay its text out on ONE line unless
    something else constrains it -- without a cap, the dialog's intro
    label alone stretched the whole window to ~1360px wide.
* **Another audit round, two more real bugs found and fixed.** A
  fan-out re-sweep after the Propagation Setup work landed:
  * `schema.scenario.GravityConfig.validate()` never checked that
    spherical-harmonics gravity (`central_body_degree > 0`) is only wired
    up for Earth -- `engine.service.SimulationService.build()` already
    rejects any other central body with that combination, but only at
    simulation time. Without a matching schema-layer check,
    `missionstudio validate`/`Scenario.save()` (both deliberately
    Basilisk-independent, meant as an early correctness check) gave a
    clean bill of health to a scenario guaranteed to fail the moment it
    was actually run. Now rejected at the schema layer too.
  * `engine.monte_carlo`'s `dry_mass_kg` dispersion wrote its generated
    value ABSOLUTELY to `hub.mHub` (Basilisk's dispersion framework has
    no notion of "add this on top of what's already there") -- but
    `hub.mHub` is `dry_mass_kg + propellant` for any spacecraft with
    `station_keeping`/`constant_thrust` configured, not just
    `dry_mass_kg` (see `SpacecraftConfig.dry_mass_kg`'s own documented
    contract). A `dry_mass_kg` dispersion on such a spacecraft was
    therefore silently dispersing the TOTAL mass under that name --
    bounds picked to disperse just the dry mass actually dispersed dry
    mass + propellant, quietly shrinking the effective dry-mass spread by
    exactly the propellant amount on every run, with the station-keeping
    controller's own (unaffected, independently-tracked) propellant
    belief silently inconsistent with the result from tick zero. Fixed
    with two small dispersion subclasses
    (`_DryMassPlusPropellantUniformDispersion`/
    `_DryMassPlusPropellantNormalDispersion`) that add the target
    spacecraft's configured propellant back on top of the generated
    dry-mass value before it's written to `hub.mHub`, matching
    `service.py`'s own `initial_mass_kg` computation exactly. Also fixed,
    same audit: `migrations.migrate()`'s `schema_version` type check used
    `isinstance(version, int)`, but `bool` is a subclass of `int` in
    Python, so a malformed `"schema_version": true` silently passed
    through instead of raising the same clear error every other malformed
    `schema_version` value gets.

## What Phase 6 (Mission Sequence architecture) adds -- landed

A GMAT/FreeFlyer-inspired **Resources / Mission Sequence / Output**
organization, requested directly: separate "what exists" (spacecraft,
gravity, ground stations, ... -- everything the schema already had) from
"what happens, in time order" (propagate, maneuver, assign, report,
conditionals) and "what a run produced". Explicitly NOT a port of GMAT's
or FreeFlyer's own object model -- the organizing idea (resources vs. a
time-ordered sequence) is what's borrowed; everywhere Basilisk's own
architecture is a better fit than copying either tool's shape (its native
event mechanism, its continuous feedback controllers, its message/recorder
architecture, its own Monte Carlo framework), this keeps using Basilisk's
own mechanism rather than reshaping it to look like GMAT/FreeFlyer.

This phase is landing in reviewable stages, matching its own plan: data
model first (this section), then an execution engine, then file-format/
GUI-sync work, then the GUI itself -- each stage additive, so every
existing scenario file and every existing test keeps passing unchanged at
every step (confirmed after each stage: the full suite's pass count only
ever grows).

**Data model (`schema/command.py`, `schema/references.py`,
`schema/validation.py`) -- landed:**

* `schema.command.Command`: one envelope dataclass (`kind`, optional
  `label`, `params` dict, `children` for `if`/`while` nesting) covering
  the minimum command set this phase scoped: `propagate` (duration/epoch/
  event-based stop conditions -- events deliberately limited to periapsis/
  apoapsis passage for now, meant to be built on Basilisk's own
  `SimulationBaseClass.EventHandlerClass` rather than a hand-rolled
  polling loop), `maneuver` (impulsive delta-V, inertial/VNB/RTN frame --
  VNB/RTN meant to reuse `engine.orbit_maintenance`'s already-written,
  already-tested `_vnb_basis`/`_rtn_basis` helpers), `assignment`,
  `report`, `if`/`while`, `script_block`. One envelope dataclass rather
  than one Python class per kind, matching the exact shape
  `SensorConfig`/`ActuatorConfig`/`fsw_params` already use in this schema
  for the same reason (very different per-kind shapes, no
  discriminated-union (de)serialization mechanism elsewhere in this
  schema to reuse). Targeting/optimization commands are explicitly out of
  scope for now, per this feature's own scoping decision.
* `Command.validate()` is a COLLECTING validator -- returns every problem
  found in a command (and its `children` subtree) as a list, each with an
  item path, rather than raising on the first one. `Scenario.validate()`
  (unchanged, still raise-fast, exactly as before this phase) now also
  walks `mission_sequence`, folding each command's collected errors into
  one combined message per command -- still raise-fast ACROSS commands,
  preserving that method's existing behavior/contract exactly.
  `schema.validation.validate_all(scenario)` is the genuinely
  fully-collecting entry point requested: every command's every problem,
  plus every dangling spacecraft/ground-station reference across the
  whole sequence, all at once -- stated plainly in its own docstring that
  the RESOURCE side of that same call is still at-most-one-message (since
  it delegates to the unchanged, raise-fast `scenario.validate()`
  rather than retrofitting ~15 existing resource validators into
  collecting ones, which was judged out of proportion to this change).
* `Scenario.mission_sequence: list[Command] = []` -- additive, empty by
  default, so it changes nothing about how any existing scenario file
  loads, validates, or runs; `engine.service.SimulationService.run()`/
  `run_live()` are untouched. Round-trips losslessly through the existing
  JSON format (`Command` is a plain dataclass, so `dataclasses.asdict()`
  -- already how `Scenario.to_dict()` works -- recurses through it with
  no extra code; only the read direction needed a hand-written
  `Command.from_dict()`, matching every other nested dataclass in
  `Scenario.from_dict()`). The existing JSON file format itself now
  reads as GMAT's `BeginMissionSequence` split in miniature -- every
  existing top-level field is "resources", the new `mission_sequence` key
  is the sequence -- without inventing a new text format.
* `schema.references`: `find_spacecraft_references()`/
  `find_ground_station_references()` (an empty list means "safe to
  delete" -- GMAT's own "delete refused, listing every referencing item"
  behavior, which this project's spacecraft/ground-station list widgets
  did not have before this: `_on_remove()` deleted unconditionally, with
  no reference check of any kind, confirmed by reading both before
  writing this) and `rename_spacecraft()`/`rename_ground_station()`
  (FreeFlyer's "rename symbol" behavior -- renames the resource AND
  every reference to it, atomically). Every reference site is hand-listed
  (`phasing_keeping.chief_spacecraft`, Monte Carlo `dispersion.
  spacecraft`, `fsw_params['target_ground_station']`, and every command
  kind/nesting depth that can name a resource) rather than found via
  generic reflection, matching this schema's own established style
  (explicit and auditable over generic) at the cost of needing a new
  entry here whenever a new reference site is added elsewhere.

**Verification:** 62 new tests (`tests/test_command.py`,
`tests/test_references.py`, `tests/test_validation.py`, plus additions to
`tests/test_scenario_schema.py`), all Basilisk-independent (this whole
layer has no Basilisk import) -- model round-trip (including through a
real `save()`/`load_scenario()` file round-trip, and an explicit
command-ordering/reordering check), reference-integrity (find/rename,
including references nested inside `if`/`while` and the dotted-path form
`assignment.target` uses), and collecting-validation (multiple bad
commands and multiple dangling references, all reported at once, not just
the first). Full suite after this stage: 430 passed, 22 skipped (was 366
passed/22 skipped before -- the 22 skips are unrelated, pre-existing
`requires_basilisk` tests; zero regressions, zero new skips, since this
stage adds no Basilisk-dependent code).

**Execution engine (`engine/mission_engine.py`) -- landed:**

* `MissionEngine(scenario, service=None).run() -> (ResultSet, CommandSummary)`
  walks `scenario.mission_sequence` against a real `SimulationService`,
  dispatching each `Command` by `kind`. Every Basilisk call sequence is
  copied from an actually-running official example or this checkout's own
  source, not written from memory (see the module's own docstring for the
  full citation list) -- most notably:
  * `propagate` (duration/epoch): repeated `ConfigureStopTime()`/
    `ExecuteSimulation()` pairs, `ConfigureStopTime()` taking an ABSOLUTE
    cumulative time (not a delta) -- `examples/scenarioOrbitManeuver.py`'s
    own comment on this, and already exercised by this project's own
    `SimulationService.run_live()`/`tests/test_service_run_live.py`.
  * `propagate` (event -- periapsis/apoapsis): Basilisk's native
    `SimBaseClass.createNewEvent(name, eventRate, eventActive,
    conditionFunction=..., terminal=True)`, copied from
    `examples/scenarioDragDeorbit.py`'s own terminal-event block. Detected
    as a sign change in radial velocity (`dot(r, v) / |r|`) rather than
    reconstructing true anomaly every check, capped by a generous
    duration-based safety multiplier so a trajectory that never reaches
    the event raises a clear `MissionEngineError` instead of hanging.
  * `maneuver` (impulsive delta-V, inertial/VNB/RTN): `scObject.dynManager.
    getStateObject(scObject.hub.nameOfHubPosition/nameOfHubVelocity)`
    fetched once, `simHelpers.EigenVector3d2np(velRef.getState())` to read
    the current velocity, plain numpy arithmetic (VNB/RTN via
    `engine.orbit_maintenance`'s already-tested `_vnb_basis`/`_rtn_basis`),
    `velRef.setState(...)` to apply it -- the exact pattern
    `examples/scenarioOrbitManeuver.py` itself uses for its two maneuvers.
* `assignment`/`report`/`if`/`while`/`script_block` have no Basilisk-API
  precedent -- this project's own design, deliberately narrow: `assignment`
  only varies a small, hand-listed whitelist of live controller parameters
  (`thrust_n`/`isp_s` on `station_keeping`/`phasing_keeping`/
  `constant_thrust`), not generic attribute access; `report` snapshots the
  CURRENT value of requested series (GMAT `Report`-command semantics, not
  the whole time history the `ResultSet` already carries) into
  `CommandSummary.reports`; `if`/`while` conditions and `script_block` code
  run against a small, explicit namespace (`t_s`, `spacecraft[name].
  {r_BN_N, v_BN_N, altitude_m, mass_kg}`) -- `script_block` runs full,
  unrestricted Python (a deliberate trust boundary matching GMAT/FreeFlyer's
  own script commands and this checkout's own `examples/` scripts: only run
  a mission file you trust). `while` has a 10,000-iteration safety cap so a
  condition that never becomes false fails fast with a clear error rather
  than hanging.
* Every command failure raises `MissionEngineError` naming the specific
  command's path (e.g. `"mission_sequence[2].children[0] (maneuver): ..."`)
  and kind, never a bare exception from inside Basilisk/`eval`/`exec`.

**Verification:** 23 tests (`tests/test_mission_engine.py`,
`requires_basilisk`-marked like every other `engine.*` test -- this layer
imports `engine.service`, which itself needs Basilisk at import time), and
this is the first Phase 6 stage actually RUN against a real Basilisk
build (by the user, who has a working install this project's own sandbox
doesn't) rather than only written against verified-but-unexecuted call
sequences. All 23 pass now, but only after three real bugs the first
real run surfaced and this project's own "no guessing" discipline caught
by actually checking rather than assuming:

* `TimeSeries` crashed on a genuinely zero-sample recorder: a
  `mission_sequence` with no `propagate` command never calls
  `ExecuteSimulation()`, and Basilisk's own recorder accessor returns a
  bare 1-D array (losing the column count) rather than an `(0, ncols)`
  array when nothing was ever logged. Fixed in `engine/results.py`.
* Chaining each `propagate` command's absolute `ConfigureStopTime()`
  target off `scSim.TotalSim.CurrentNanos` read back after the previous
  command compounds rounding loss across segments whenever a requested
  duration isn't an exact multiple of `dynamics_task_rate_s` -- confirmed
  directly against `sim_model.cpp`: `CurrentNanos` is set to
  `NextTaskTime`, i.e. it snaps DOWN to the last task-grid point at or
  before the actual stop time. Three real chained `propagate` commands
  ended up 20 s short of one equivalent single `propagate`. Fixed by
  tracking the cumulative REQUESTED mission time in a separate counter,
  decoupled from the sim's own grid-snapped clock (`propagate`'s `event`
  stop condition is the one exception: it re-syncs to the actual,
  inherently grid-snapped firing time instead, since there's no
  requested target to track there).
* `propagate`'s `event` stop condition checked `scSim.terminate` after
  `ExecuteSimulation()` to tell whether the event fired, always reading
  `False` and raising a bogus "did not occur" error -- confirmed directly
  against `SimulationBaseClass.py` (and with a live diagnostic against a
  real Basilisk build) that `ExecuteSimulation()` unconditionally resets
  `self.terminate = False` as its own last statement before returning,
  whether the loop broke early on a terminal event or ran to completion,
  so that flag can never answer "did a terminal event fire" after the
  fact. The event mechanism itself was correct the whole time (confirmed
  by the same diagnostic: the sim genuinely stopped at the exact
  periapsis crossing, `CurrentNanos` matching the analytically-predicted
  orbital period to the second). Fixed by checking the fired event's own
  `occurCounter` via `scSim.eventMap[event_name]` instead.

A fourth finding was a wrong test assumption, not an engine bug:
`InitializeSimulation()` alone produces ZERO recorder samples (a
recorder only gets one once `ExecuteSimulation()` has actually ticked),
not one as originally assumed -- `_run_report` now raises a specific
`MissionEngineError` naming which series have no samples yet (a
`report` before any `propagate` has run) instead of a bare `IndexError`.

Test coverage itself: multi-segment `propagate` accumulating rather than
restarting (matches a single equivalent-duration `run()` bit-for-bit),
`epoch`/`event` stop conditions, both maneuver frames (checked against
the LIVE state object directly, not the recorder, since a maneuver alone
doesn't trigger a new `scStateOutMsg` write), `assignment` mutating a
live controller, `report` snapshotting the value AT that mission time
(not the final one), `if`/`while` (including nested, including the
iteration-cap safety net), `script_block` (including exception
wrapping), and clear-error cases for every "names something that doesn't
exist" case.

**File-format/CLI sync (`cli.py`, `engine/results.py`) -- landed:**

The mission-sequence JSON round-trip itself was already complete as of
the data-model stage (`Command` is a plain dataclass, so it falls out of
`Scenario.to_dict()`/`from_dict()` for free -- see that stage's own
notes). What was still missing was a way to actually RUN a
`mission_sequence` outside of a Python script calling `MissionEngine`
directly (the tests, in other words) -- there was no CLI or GUI path to
it at all. Since the GUI doesn't exist yet (Phase 6's last stage), this
stage closes that gap on the CLI side, the same "headless-first" order
the rest of this project has followed:

* `missionstudio run` now dispatches on `scenario.mission_sequence`: a
  non-empty one is executed via `MissionEngine` instead of a single
  `SimulationService.run()` call. An empty one (still the default)
  behaves exactly as before -- zero change for every existing scenario
  file, matching this whole phase's additive design.
* `engine.results.CommandSummary.export_csv()`: a Command Summary needs a
  file-format story too, not just an in-memory dataclass -- writes one
  CSV per run, long format (`report_index, t_s, label, series, component,
  value`) rather than one column per series, since different `report`
  commands can request series with different shapes (a position 3-vector
  alongside a scalar mass, say) and there is no single fixed column set a
  wide table could use across every row. `missionstudio run` writes it
  to `<out-dir>/command_summary.csv` alongside the existing per-series
  CSVs, only when at least one `report` command actually ran.
* `ReportEntry`/`CommandSummary` moved from `engine/mission_engine.py`
  (which imports `engine.service` -> Basilisk at module level) to
  `engine/results.py` (deliberately Basilisk-free, exactly like
  `TimeSeries`/`ResultSet` already are) -- a design-consistency fix
  more than new functionality: these are plain data containers with no
  Basilisk dependency of their own, and belonged with this project's
  other Basilisk-independent, synthetic-data-testable result types.

**Verification:** 3 new tests in `tests/test_results.py` (Basilisk-free,
covers the CSV's long-format shape, nested-directory creation, and the
zero-reports/header-only case). `cli.py`'s actual `run` dispatch logic
itself is not independently unit-tested (same as its pre-existing
`SimulationService`-calling code -- this file's tests only cover argument
parsing and Basilisk-free helper functions, see `tests/test_cli.py`'s own
scope).

**GUI (`gui/mission_sequence_editor.py`, `gui/mission_output_widget.py`,
`gui/run_worker.py`, `gui/main_window.py`, `gui/scenario_editor.py`) --
landed:**

The final Phase 6 stage: a `mission_sequence` is now editable and runnable
end-to-end from the GUI, not just from a scenario JSON file or a script
calling `MissionEngine` directly.

* `gui.mission_sequence_editor.MissionSequenceEditorWidget` -- a new
  "Mission sequence" group box in `ScenarioEditorWidget`, right below
  Ground stations. This is the first `QTreeWidget` used anywhere in
  `gui/` (every other list -- spacecraft, sensors/actuators, ground
  stations -- is flat); `Command` is the first schema type that nests
  (`if`/`while` carry `children`), so a tree is the first of its shape
  this app has needed. Add/Edit/Remove mirror
  `gui.sensor_actuator_editor.SensorActuatorListWidget`'s existing
  shape; Add Child (enabled only when the current selection is an
  `if`/`while`) and Move Up/Move Down are new, for nesting and ordering
  a flat list doesn't need. A tree node's `children` are always taken
  from the tree's own nesting, never from a stored `Command`'s own
  `children` field (which is deliberately cleared on every node --
  see the module's docstring) -- editing a child can never leave a
  parent's copy stale.
* `_CommandEditorDialog` -- modeled directly on
  `gui.sensor_actuator_editor._ItemEditorDialog`'s Kind-combo-plus
  -conditional-fields shape, with one page per `Command` kind (`if`/
  `while` share a page -- both are just a `condition` string). Unlike
  that dialog, this one doesn't hand-check each field: it builds a real
  `schema.command.Command` and calls its own `validate()`, so the
  dialog can never drift out of sync with what `Command.validate()`
  actually requires. `script_block.code` gets a `QPlainTextEdit` in a
  monospace font -- this is "the script editor" from the original
  Resources/Mission/Output request. Spacecraft-name fields
  (`propagate`'s event target, `maneuver`'s target, `assignment`'s
  target) are `QComboBox`es fed from a snapshot list taken when the
  dialog opens, via `MissionSequenceEditorWidget.
  set_spacecraft_names_provider()` -- mirrors
  `gui.spacecraft_editor.SpacecraftListWidget.
  set_central_body_provider()`'s existing zero-argument-callable
  convention. `assignment`'s controller/parameter fields are
  `QComboBox`es built from a small whitelist duplicated from (not
  imported from) `engine.mission_engine._ASSIGNMENT_CONTROLLERS`/
  `_ASSIGNMENT_ATTRIBUTES` -- duplicated because
  `engine.mission_engine` imports `engine.service` -> Basilisk at
  module level, and this dialog has to work with no Basilisk installed;
  kept in sync by hand, same as `_KIND_PARAM_SPECS` already documents
  doing for `engine.fsw`.
* `gui.mission_output_widget.MissionOutputWidget` -- the "debug
  console" from the original request: a new read-only "Mission Output"
  tab in `MainWindow.right_tabs` (between Results and Kernel Status)
  that lists every `report` command's `ReportEntry` in execution order
  once a `mission_sequence` run finishes, plus the total
  `commands_executed` count from its `CommandSummary`.
* `gui.run_worker.RunWorker` now dispatches on
  `scenario.mission_sequence` exactly like `cli.py`'s `cmd_run()`
  already did: a non-empty sequence runs through `MissionEngine`
  instead of `SimulationService.run()`/`run_live()` directly, and
  `finished_ok` now always carries `(ResultSet, Optional[
  CommandSummary])` instead of just a `ResultSet` -- `None` for every
  existing (`mission_sequence`-free) scenario, so nothing about the
  non-mission-sequence path changed. `MissionEngine.run()` has no
  `run_live()` equivalent (no per-command progress callback to drive
  one), so `MainWindow.on_run()` ignores the Live Plot toggle whenever
  `mission_sequence` is non-empty rather than silently hanging a
  progress bar at 0%.
* `MainWindow._on_run_finished()` switches `right_tabs` to Mission
  Output instead of Results when a run produced a `CommandSummary`,
  and clears the Mission Output tab on New/Open/Run, matching how
  Results already behaves.

**Verification:** every new/changed GUI file above has direct
`pytest-qt` coverage in `tests/gui/` (`test_mission_sequence_editor.py`,
`test_mission_output_widget.py`, plus additions to
`test_scenario_editor.py`/`test_main_window.py`). Confirmed against a
real Basilisk build (`pytest tests/ -v`): **501 passed, 8 skipped** --
the 8 skips are exclusively the "Basilisk is not installed" error
-path tests, which correctly skip once Basilisk *is* installed; every
other test in the suite ran for real, including all 23
`test_mission_engine.py` tests and this stage's own GUI tests. One
thing that pass doesn't cover: `test_main_window.py`'s
mission-sequence-dispatch tests monkeypatch `RunWorker.start` to avoid
spinning up a real thread, so no automated test yet drives a genuine
GUI click-through (build a `mission_sequence` in the running app,
click Run, watch the "Mission Output" tab populate from a live
`RunWorker` thread executing `MissionEngine.run()`) -- worth doing
once, since every prior Phase 6 stage turned up real bugs only
reachable that way, but no longer the open question this note used to
flag.

## Launching Vizard from the GUI

A **Launch Vizard** action in the Run menu/toolbar starts the external
Vizard application, added in response to a direct request. Previously
the only Vizard-related GUI surface was the Run menu's **Vizard...**
action -- renamed to **Vizard Configuration...** here to keep the two
apart -- which only configures how the *next simulation run* feeds an
already-running Vizard instance (a playback `.bin` file or a live
stream); nothing anywhere actually started the external application
itself. (An earlier version of this feature added a whole extra
"Vizard" status tab next to Results/Mission Output/Kernel Status --
scrapped after user feedback that a plain menu/toolbar action next to
the existing Vizard Configuration one, not a new persistent tab, was
what was actually wanted.)

* `gui/vizard_launcher.py` -- Basilisk-free (launching an external
  process needs no Basilisk build) module with `find_vizard_executable()`,
  `remember_vizard_executable()`, and `launch_vizard()`. Vizard ships as
  a platform `.zip` the user extracts wherever they like (see
  `docs/source/Vizard/VizardDownload.rst`'s "install in the typical
  Applications folder or Desktop") -- there is no single guaranteed
  install path, so finding it is inherently best-effort: a previously
  remembered path (persisted via `QSettings`, under
  `vizard/executable_path`) is tried first, then a shallow search of a
  handful of common per-OS locations (`/Applications`, Desktop,
  Downloads, `Program Files`, ...), and `None` if neither turns up
  anything. `launch_vizard()` resolves a macOS `.app` bundle to its real
  `Contents/MacOS/` binary before calling `subprocess.Popen` (rather
  than shelling out to `open`, which would hand off and exit
  immediately, losing any way to track whether Vizard is still running)
  and returns the live `Popen` handle.
* `main_window.py` -- a new **Launch Vizard** `QAction`
  (`self.vizard_launch_action`, distinct from the renamed
  `self.vizard_action` "Vizard Configuration..."), wired to
  `on_launch_vizard()`: a no-op while Vizard is already running (checked
  via `Popen.poll() is None` on `self._vizard_process`, the last handle
  `launch_vizard()` returned), otherwise looks the executable up via
  `find_vizard_executable()` and launches it -- falling back to a
  `QFileDialog` browse prompt (remembered via
  `remember_vizard_executable()`, so asked at most once) when it can't
  be found automatically.
* `app.py` -- gained `app.setOrganizationName("AVSLab")`, needed for
  `QSettings()` (used above with no explicit org/app name) to resolve to
  a stable per-platform settings location.

**Verification:** `tests/gui/test_vizard_launcher.py` (path search/
persistence, all real filesystem/`QSettings` I/O redirected into
`tmp_path` -- never touches the developer machine's real Vizard
install or settings), plus `test_main_window.py` additions covering
`on_launch_vizard()`'s launch/no-relaunch-while-running/relaunch-after
-exit/browse-fallback/browse-cancelled/launch-failure paths
(`find_vizard_executable`/`launch_vizard` monkeypatched so nothing
spawns a real process). This sandbox has no real Vizard binary to
launch against, so `launch_vizard()`'s actual `subprocess.Popen` call
itself (as opposed to its argument-construction logic, which the
macOS-bundle-resolution tests in `test_vizard_launcher.py` do cover) is
unverified against the real thing -- worth confirming Vizard actually
opens on a real machine with Vizard installed.

## Second round of GUI feedback

Five pieces of direct feedback from a real run against the actual GUI (a
"Simulation failed" dialog referencing `VizInterface` came with it):

* **Vizard live-stream crash, fixed.** `engine/vizard.py`'s
  `enable_vizard()` used to keep every `_AccessIndicatorBridge` alive by
  attaching them to `viz` as `viz._missionstudio_access_indicator_bridges`.
  `viz` is a SWIG proxy for a C++ `VizInterface`, and SWIG-generated
  proxy classes raise on any attribute they don't already know about --
  confirmed against the reported crash, which failed immediately with
  "You tried to add this variable: ... To this class: <...VizInterface
  ...>" before a single simulation step ran, whenever a scenario used
  the Vizard live-stream option. Fixed by having `enable_vizard()` return
  `access_indicator_bridges` alongside `viz` instead of bolting it onto
  `viz`, and having `SimulationService` retain both as plain attributes
  of itself (an ordinary Python object with no such restriction).
* **Plots now show km/km-s, not raw meters** (`results_widget.py`).
  Length/length-rate series (`units in {"m", "m/s"}` -- position,
  velocity, altitude, slant range, delta-V, ...) are converted for
  display only; a LEO position plot's y-axis used to be in the millions.
  Deliberately narrow -- everything else (accelerometer m/s^2, torque
  N*m, angles, ...) is left alone, since km-scale units would be worse
  there, not better. CSV export (`ResultSet.export_csv()`) is unaffected
  -- it keeps writing the raw SI units `TimeSeries` already holds, since
  a CSV handed to another tool should stay unambiguous.
* **A new X-axis combo** (Elapsed time / Epoch (UTC)) on the Results
  plot. `MainWindow.on_run()` captures `scenario.epoch_utc` before
  starting the run (so it reflects the scenario that was actually run,
  not whatever the editor holds by the time the run finishes) and passes
  it through `_on_run_progress()`/`_on_run_finished()` into
  `ResultsWidget.set_live_result()`. `set_result()`/`set_live_result()`
  both take an optional `epoch_utc` (default `None`), so every existing
  caller/test keeps working unchanged; "Epoch (UTC)" with no epoch
  available (or one that fails to parse) falls back to elapsed time
  rather than raising.
* **The Description box in the Scenario Editor is bigger**
  (`scenario_editor.py`'s `description_edit`, `setFixedHeight(60)` ->
  `220`) -- it needed constant scrolling to read a template's full
  description at the old size.
* **Abort a running simulation, without breaking the tool.** See its own
  section below.

**Verification:** `tests/gui/test_results_widget.py` (km conversion +
Epoch axis, including the "no epoch given"/"unparseable epoch" fallback
paths) and `tests/gui/test_main_window.py` (epoch capture/passthrough).
The Vizard crash fix has no dedicated regression test -- there is no
Basilisk-free way to construct a real `VizInterface` SWIG proxy to
assert against -- but it was confirmed against the exact real run that
originally hit it.

## Abort Simulation

Direct user feedback: "there should also be the option to abort a
running simulation, if needed, without breaking the tool." Basilisk's
`SimBaseClass.ExecuteSimulation()` is a single, blocking C++ call with no
hook to interrupt it mid-flight, and `QThread.terminate()` was
deliberately never considered -- it could leave Basilisk's C++
simulation state mid-mutation, exactly the kind of "breaking the tool"
this was asked to avoid. The design is cooperative cancellation instead,
checked between simulation chunks or mission-sequence commands -- never
a forced kill:

* `engine/service.py` -- a new `SimulationCancelled` exception carrying
  whatever partial `ResultSet` had been produced so far
  (`.partial_result`). `run_live()` gained an optional
  `should_cancel: Optional[Callable[[], bool]] = None` parameter, checked
  once after each chunk's `ExecuteSimulation()` call; when it returns
  `True`, `run_live()` raises `SimulationCancelled` with that chunk's
  results rather than silently discarding them. `should_cancel=None` (the
  default, matching every pre-existing caller) leaves behavior unchanged.
* `engine/mission_engine.py` -- the mission-sequence equivalent:
  `MissionEngineCancelled` (carrying both `.partial_result` and
  `.summary`), and `MissionEngine.__init__` gained the same
  `should_cancel` parameter, checked once per top-level command in
  `_run_commands()` -- which also naturally covers `while`-loop
  iterations, since `_run_while()` re-enters `_run_commands()` once per
  iteration -- AND, since then (see "Abort during a single long
  propagate command, fixed" below), mid-command too: a single
  `propagate` command's own `ExecuteSimulation()` call is chunked via
  `_advance_to()`/the chunked branch of `_run_propagate_event()`, not
  just between top-level commands.
* `gui/run_worker.py` -- `RunWorker` gained `request_cancel()` (sets a
  `threading.Event`, safe to call from the GUI thread while `run()` is
  executing on its own thread) and a new `cancelled` Qt signal
  (`Signal(object, object)`: partial `ResultSet`, optional
  `CommandSummary`). The non-`mission_sequence` path now ALWAYS runs
  through `run_live()` (never the plain, non-chunked `run()`)
  specifically so it's always cancellable regardless of the Live Plot
  toggle -- `self.live` now only controls whether the `progress` signal
  is actually emitted (i.e. whether the plot redraws as the run
  proceeds), not whether the run is chunked at all;
  `run_live()`'s own `_LIVE_DEFAULT_FRAMES` (60) bounds this to a small,
  fixed number of extra `ExecuteSimulation()` calls regardless of run
  length, negligible next to the actual simulated work either way.
* `main_window.py` -- a new **Abort Run** `QAction` (Run menu and
  toolbar, between Run Simulation and Live Plot), disabled except while a
  single (non-Monte-Carlo) run is actually in flight -- `on_run()`
  enables it right after starting `RunWorker`, `_stop_busy()` disables it
  again on any of finished/failed/cancelled. Monte Carlo batches are
  deliberately out of scope: `engine/monte_carlo.py`'s
  `Controller.executeSimulations()` uses a different, single-call
  execution model with no exposed chunking/cancellation hook in this
  checkout, and adding one would be unverifiable against a real Basilisk
  build in this development sandbox anyway. `on_abort_run()` calls
  `RunWorker.request_cancel()` and immediately disables the action (so
  there's nothing to double-click while waiting for the next
  checkpoint -- cancellation is cooperative, not instant); a new
  `_on_run_cancelled()` slot (connected to `RunWorker.cancelled`) shows
  whatever partial results/command summary had been produced, with
  "Run cancelled by user." status-bar messaging instead of "Run
  complete", exactly like a normal finish otherwise.

**Verification:** `tests/test_service_run_live.py` and
`tests/test_mission_engine.py` gained `should_cancel` tests
(`requires_basilisk`, auto-skipped in this development sandbox -- see
the honesty note above); `tests/gui/test_run_worker.py` covers the
dispatch/cancellation plumbing Basilisk-free by faking
`engine.service`/`engine.mission_engine` in `sys.modules` (works
regardless of whether a real Basilisk build is present); and
`tests/gui/test_main_window.py` covers the `abort_action`
enable/disable wiring plus an end-to-end real-`QThread` test proving the
`cancelled` signal is actually connected through to
`_on_run_cancelled()`. All of it (except the `requires_basilisk`-marked
engine-level checkpoint tests) was run and confirmed passing in this
sandbox; the `requires_basilisk` tests were then run for real, on an
actual Basilisk build, which caught one genuine bug:
`_run_command()` wrapped every non-`MissionEngineError` exception a
handler raised into a `MissionEngineError`, including a
`MissionEngineCancelled` bubbling up from several levels down the
command tree (e.g. cancelling mid-`while`-loop, where the cancellation
is raised inside the loop body's own nested `_run_commands()` call,
inside `_run_while()`, inside the enclosing `_run_command()`'s `try`
block) -- masking a clean, user-requested abort as a simulation
failure. Fixed by re-raising `MissionEngineCancelled` unchanged before
the generic `except Exception` clause runs (see its own comment in
`mission_engine.py`): `612 passed, 8 skipped, 1 failed` on that real
build before the fix (only `test_should_cancel_checked_between_while_
loop_iterations` failing), `613 passed, 8 skipped` on the same real
build after it -- the whole Abort Simulation feature, cancellation
inside a `while` loop included, is now confirmed against a real
Basilisk build, not just this sandbox's Basilisk-free suite.

### Abort during a single long propagate command, fixed

More direct user feedback, on the real build: clicking Abort mid-run
showed "Aborting... this takes effect at the next checkpoint, not
instantly" and then simply never finished -- minutes of waiting, no
effect. Root cause: a single `propagate` command's own
`ExecuteSimulation()` call ran straight through to its requested target
in ONE unchunked call, so `should_cancel` (only checked BETWEEN
top-level commands, per `run()`'s own docstring at the time) had no
opportunity to fire at all until that one command finished on its own --
for a mission sequence with one long `propagate` (duration/epoch/event),
that's the entire run.

Fixed the same way `engine.service.run_live()` already fixes it for the
non-mission_sequence path: chunk it.

* `_advance_to()` (new) -- runs the simulation from `self._elapsed_ns`
  to a target time, in one unchunked `ConfigureStopTime()`/
  `ExecuteSimulation()` pair when `should_cancel is None` (unchanged
  behavior, zero extra overhead), or in roughly
  `_PROPAGATE_CANCEL_CHECK_FRAMES` (60, mirroring
  `engine.service._LIVE_DEFAULT_FRAMES`) pieces otherwise, checking
  `should_cancel()` after each one and raising `MissionEngineCancelled`
  if it fires. `_run_propagate`'s `"duration"`/`"epoch"` branches now
  both call it instead of executing straight to their target.
* `_run_propagate_event()`'s safety-capped search (periapsis/apoapsis)
  got the same treatment: chunked when `should_cancel` is set, checking
  both the registered Basilisk event's own `occurCounter` (so a real
  periapsis/apoapsis crossing mid-chunk still stops the search exactly
  as before -- chunking never delays detecting it) and `should_cancel()`
  after each chunk. Its chunk size is deliberately based on the
  scenario's own `duration_days`, not `cap_days` (`duration_days *
  _EVENT_PROPAGATE_SAFETY_MULTIPLIER` -- a rarely-hit upper bound on the
  search, not a meaningful step size): sizing off `cap_days` would make
  each chunk roughly `_EVENT_PROPAGATE_SAFETY_MULTIPLIER` (10x) too
  coarse relative to how soon the event realistically fires in a real
  mission, right back to the same problem.
* `run()`'s own docstring updated to describe the new mid-command
  checkpoint, alongside the existing between-commands one.

**Verification:** two new `tests/test_mission_engine.py` cases
(`test_should_cancel_checked_mid_single_long_propagate_command`,
`test_should_cancel_checked_mid_propagate_event_command`) assert a
cancelled run's partial result is strictly shorter than letting the
same command finish would have produced -- the actual behavior this bug
report was about. The existing
`test_should_cancel_checked_between_while_loop_iterations` and the
renamed `test_should_cancel_stops_before_the_first_command_and_raises_
mission_engine_cancelled` (previously named
"...stops_between_commands..." -- its own duration was short enough
that it used to complete in a single old-style unchunked call, so
"between commands" and "before the first command" were the same thing;
now that a command can itself be chunked, the name says precisely which
checkpoint it exercises) were reworked to keep testing the
between-commands/between-iterations checkpoint specifically, now that a
command can also be interrupted mid-way. **This round has NOT yet been
re-run against a real Basilisk build** -- only this sandbox's
Basilisk-free suite (570 passed, 53 skipped, two more than before for
the two new `requires_basilisk` tests) confirms the plumbing compiles
and the untouched paths still pass; the chunk-timing arithmetic behind
the `while`-loop test's exact `commands_executed == 3` expectation, and
the event test's assumption that its chunk size lands comfortably
inside one ~90-minute orbital period, are worked out by hand in each
test's own docstring/comments, not confirmed by actually running them.

### Vizard live-stream: auto-connect instead of a manual launcher step

Direct user feedback, with a screenshot: running a live-stream scenario
showed Vizard just sitting on its own "Load Data Using One of the
Following" launcher screen doing nothing, while missionStudio itself sat
at 0% progress, elapsed time climbing, with Abort having no effect at
all no matter how long it waited.

Root cause, confirmed against `docs/source/Vizard/vizardAdvanced/
vizardLiveComm.rst` and `vizInterface.cpp` directly: in live-stream mode,
`SimBaseClass.InitializeSimulation()`'s very first step is a **blocking**
ZeroMQ handshake -- Basilisk connects out to `tcp://<vizInterface's
reqComAddress>:<reqPortNumber>` (defaults `0.0.0.0:5556`, i.e.
`localhost:5556` locally -- never overridden anywhere in this checkout)
and sends a PING it waits for Vizard to reply to, before a single
simulation step ever runs. Vizard only replies once its OWN launcher
screen has been told what to connect to (typing the address into
"Socket Address") and "Start Visualization" has actually been clicked --
skip that manual step (as our own "Launch Vizard" button previously
did -- it just started the bare app with no arguments) and that PING
never gets a reply, so `InitializeSimulation()` blocks forever. This is
native C++ with no Python-level hook at all -- not even the Abort
feature's own chunk-boundary checkpoints are reachable yet, since this
happens before the first chunk.

Fixed by never requiring that manual step in the first place: Vizard's
own `-directComm <address>` command-line flag (`docs/source/Vizard/
vizardAdvanced/vizardCommandLine.rst`) makes it connect automatically on
launch, with nothing to type or click.

* `gui/vizard_launcher.py` -- new `DEFAULT_LIVE_STREAM_ADDRESS =
  "tcp://localhost:5556"` (matching vizInterface's own unmodified
  defaults). `launch_vizard()` gained an optional `direct_comm_address`
  parameter, appended as `-directComm <address>` to the launched
  process's arguments when given.
* `main_window.py` -- `on_launch_vizard()` now passes
  `DEFAULT_LIVE_STREAM_ADDRESS` whenever Vizard Configuration is set to
  live-stream (`None`, i.e. no flag at all, otherwise -- a save-file run
  still launches Vizard exactly as before), and returns `True`/`False`
  instead of nothing, so a caller can tell whether Vizard is actually
  confirmed running. `on_run()` calls it FIRST, before starting a
  live-stream run's `RunWorker` at all, refusing to start (with a clear
  explanation, never a silent hang) if Vizard couldn't be confirmed --
  an ordinary (non-live-stream) run never touches Vizard at all, so this
  adds no new behavior there.

**Known residual gap, by design, not fully closed:** if Vizard is
already running (from an earlier, non-`-directComm` launch, or started
by the user outside missionStudio entirely) when a live-stream run
starts, `on_launch_vizard()` -- matching its pre-existing "never
relaunch while already running" behavior -- trusts it and does not
relaunch it with `-directComm`, so the same hang can still happen if
that existing instance was never told to connect. There is no reliable
way to ask Vizard "are you actually connected" from outside it, so this
edge case is accepted rather than guessed around.

**Verification:** `tests/gui/test_vizard_launcher.py` gained two new
`launch_vizard()` tests (the flag is appended when given, omitted when
not); `tests/gui/test_main_window.py` gained five new tests covering
`on_launch_vizard()`'s address selection and `on_run()`'s new
Vizard-confirmation gate (including that an ordinary run never calls
`on_launch_vizard()` at all). All pass in this sandbox (577 passed, 53
skipped). Like the Vizard crash fix earlier in this document, there is
no way to exercise a real Vizard connection handshake without an actual
Vizard binary and display, so the `-directComm` flag's effect on Vizard
itself (as opposed to the argument list missionStudio constructs) is
unverified here -- report back if a live-stream run still doesn't
connect after this.

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
      command.py                     -- Phase 6: Command (Mission Sequence), collecting validate()
      references.py                  -- Phase 6: reference-integrity (find/rename) for resources + commands
      validation.py                  -- Phase 6: validate_all() -- fully-collecting scenario-wide validation
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
      orbit_maintenance.py           -- Phase 4/5: station-keeping + phasing-keeping + constant-frame-thrust controllers, delta-V/propellant bookkeeping (needs Basilisk)
      propellant_bookkeeping.py      -- Phase 5: shared per-tick mass/propellant delta math (no Basilisk needed)
      constellation.py               -- Phase 4: Walker-pattern constellation generator + SeparationSchedule (no Basilisk needed)
      spacecraft_templates.py        -- Phase 5: reusable spacecraft "bus" templates (no Basilisk needed)
      mission_engine.py              -- Phase 6: MissionEngine -- walks mission_sequence against a SimulationService (needs Basilisk)
    gui/
      app.py                         -- QApplication entry point
      theme.py                       -- Phase 5: app-wide QSS stylesheet + palette
      icons.py                       -- Phase 5: procedurally-drawn app icon
      main_window.py                 -- MainWindow: File/Run menus + toolbar, ties everything together
      load_scenario_widget.py        -- "Load Scenario" tab: built-in template picker + browse-for-a-file
      scenario_editor.py             -- the full scenario form + live validation
      mission_sequence_editor.py     -- Phase 6: mission_sequence tree editor (Command Add/Edit/Remove/nesting)
      mission_output_widget.py       -- Phase 6: "Mission Output" debug-console tab (CommandSummary/ReportEntry display)
      propagation_setup_dialog.py    -- Phase 5: gravity/perturbations + integrator + space weather, one dedicated window
      spacecraft_editor.py           -- spacecraft list + add/edit/remove dialog (tabbed: orbit, sensors/actuators, FSW, power/propulsion/link budget)
      sensor_actuator_editor.py      -- Phase 2: generic sensor/actuator list + add/edit/remove dialog
      vizard_dialog.py               -- Phase 2: "enable Vizard for the next run" dialog
      vizard_launcher.py             -- find/launch the external Vizard application (no Basilisk needed)
      monte_carlo_editor.py          -- Phase 3: Monte Carlo settings + dispersion list editor
      ground_station_editor.py       -- ground station list + add/edit/remove dialog
      orbit_ic_widget.py             -- classical-elements (true/mean anomaly)/Cartesian/TLE orbit editor
      constellation_dialog.py        -- Phase 4: "Generate Walker constellation" dialog
      spacecraft_template_dialog.py  -- Phase 5: "New from template" picker dialog
      kernel_status_widget.py        -- SPICE kernel status panel
      results_widget.py              -- matplotlib results plot + CSV export
      run_worker.py                  -- SimulationService/Monte Carlo on a background QThread
    scenarios/
      two_body_validation.json       -- the Phase 0 validation scenario
      templates/                     -- education/starter-template scenarios -- see that directory's own README
        README.md                    -- the template catalog: what each one teaches, how to open/run one
        01_two_body_circular_orbit.json
        02_elliptical_orbit_with_perturbations.json
        03_geo_station_keeping.json
        04_walker_constellation.json
        05_formation_flying_phasing.json
        06_attitude_pointing_basic.json
        07_attitude_pointing_with_adcs_hardware.json
        08_mission_sequence_orbit_raise.json
        09_monte_carlo_dispersion_analysis.json
  scripts/
    _generate_templates.py            -- regenerates scenarios/templates/*.json from schema dataclasses (not installed/imported elsewhere)
  packaging/                          -- Phase 3: build_wheel.sh / install.sh / .desktop entry -- see packaging/README.md
  tests/
    conftest.py                      -- requires_basilisk / requires_gui auto-skip markers
    test_scenario_schema.py
    test_command.py                    -- Phase 6
    test_references.py                 -- Phase 6
    test_validation.py                 -- Phase 6
    test_spaceweather.py
    test_results.py
    test_link_budget.py              -- Phase 4
    test_constellation.py            -- Phase 4
    test_scenario_templates.py       -- load/validate/round-trip every scenarios/templates/*.json
    test_cli.py
    test_two_body_validation.py      -- requires_basilisk
    test_mission_engine.py           -- Phase 6, requires_basilisk
    gui/
      test_scenario_templates_gui.py -- every template round-trips through ScenarioEditorWidget too
      test_orbit_ic_widget.py
      test_spacecraft_editor.py
      test_sensor_actuator_editor.py
      test_vizard_dialog.py
      test_vizard_launcher.py
      test_monte_carlo_editor.py
      test_ground_station_editor.py
      test_constellation_dialog.py   -- Phase 4
      test_scenario_editor.py
      test_propagation_setup_dialog.py
      test_results_widget.py
      test_kernel_status_widget.py
      test_run_worker.py
      test_main_window.py
      test_mission_sequence_editor.py -- Phase 6
      test_mission_output_widget.py  -- Phase 6
      test_load_scenario_widget.py   -- "Load Scenario" tab: built-in template picker + browse
```

## Running the tests

```bash
cd missionStudio
python3 -m pip install -e ".[dev,gui]"
python3 -m pytest tests/ -v
```

Without Basilisk on `PYTHONPATH`, this runs 262 tests (schema, space
weather, results, link budget, constellation generation, CLI, and the
full PySide6 GUI, run headless) and skips 2 whose premise is specifically
"Basilisk is unavailable", per `tests/conftest.py`.

With Basilisk installed (`pip install "bsk[all]"` -- see "Getting
started" above), the 2 skips above run for real instead of skipping.
Last genuinely verified in this project's own sandbox as of the Phase 3
work (before Phase 4's additions, whose Basilisk-dependent code --
`engine.service`'s power/station-keeping/phasing-keeping wiring,
`engine.orbit_maintenance` -- has NOT been run against a real Basilisk
build in this sandbox, only written directly against verified API call
sequences; see each module's own "Verification status" docstring note):
`test_two_body_validation.py`
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

The GUI opens on its **Load Scenario** tab (left pane) -- pick one of the
nine built-in template missions (see "Template missions" below) or
browse for any other scenario file; either one switches you to the
**Scenario Editor** tab next to it with that scenario loaded and ready to
edit. File > New/Open/Save/Save As work against the same
`schema.Scenario`/`load_scenario()`/`.save()` the CLI uses (File > Open
and the Load Scenario tab's own "Browse for a file..." button are two
paths to the same `open_path()`); the scenario form's validation status
label updates live as you type, including its Monte Carlo section
(enable/num_runs/thread_count + a dispersion list, referencing spacecraft
by name). Run > Run Simulation runs `SimulationService` on a background
thread (the UI stays responsive) and switches to the Results tab when
done, with a plot per result series and a CSV export button. Run > Check
Kernels shows SPICE kernel fetch/cache status. Both Run actions report a
clear error (not a crash) if Basilisk isn't installed/built.

## Template missions for learning and for starting your own

`missionstudio/scenarios/templates/` has nine ready-to-run scenario
files, each demonstrating one missionStudio concept in isolation --
two-body orbits, J2/third-body perturbations, GEO station-keeping,
a generated Walker constellation, formation-flying phasing control,
attitude pointing (idealized, then with real ADCS hardware), a Mission
Sequence-based impulsive orbit raise, and a Monte Carlo dispersion
analysis. See that directory's own `README.md` for the full catalog and
what each one teaches -- every file also carries its own extensive
`description` field (visible in the GUI's scenario form, or by opening
the `.json` directly) explaining what to look at after running it and
what to try changing.

They're built through `schema.scenario`'s own dataclasses and
`Scenario.validate()` (via `scripts/_generate_templates.py`, kept in the
repository as the regeneration source of truth), not hand-written JSON,
and every one is covered by `tests/test_scenario_templates.py`
(schema-level load/validate/round-trip, Basilisk-free),
`tests/gui/test_scenario_templates_gui.py` (confirms each one also
round-trips through the actual `ScenarioEditorWidget` form), and
`tests/gui/test_load_scenario_widget.py` (the in-GUI picker described
below) -- 59 tests total, all passing before this was committed. What's
NOT yet verified: an actual Basilisk run of any of them (this sandbox has
none), so treat the physical numbers (propellant use, drift rates,
orbital periods) as reasonable back-of-the-envelope choices, not
independently confirmed results, the same caveat every Basilisk
-dependent module in this project carries until it's been run for real --
see the "Environment honesty note" above.

**Built into the GUI itself** (not just files you'd have to know the path
to): the GUI's **Load Scenario** tab (`gui/load_scenario_widget.py`,
see "Running the GUI" above) lists all nine by name with their
description shown on selection, no file-browsing needed -- "Open
Template" or a double-click loads one and switches straight to the
Scenario Editor tab. The same tab's "Browse for a file..." button covers
everything else, via the same `MainWindow.open_path()` File > Open
already uses. From the CLI:

```bash
missionstudio validate missionstudio/scenarios/templates/01_two_body_circular_orbit.json  # no Basilisk needed
missionstudio run missionstudio/scenarios/templates/01_two_body_circular_orbit.json --out-dir out
```

To use one as a starting point for your own mission: **Save As...** under
a new name before editing (so the original template stays intact for
next time), then layer in whatever additional concepts you need --
templates/README.md's own closing section has concrete suggestions for
combining them (e.g. a comms-relay constellation might start from '04'
and add '07''s ADCS hardware plus a ground station and RF link).

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

* **`engine.constellation`'s Walker generator doesn't auto-wire
  `PhasingKeepingConfig`** for the satellites it produces -- each
  follower's chief/target-separation still needs setting up by hand in
  the spacecraft editor afterward (see "What Phase 4 adds" above). A
  natural, well-scoped follow-on once that manual step is felt to be
  tedious in practice: the generator already knows each plane's
  membership and phase ordering, so it could assign chief = "first
  satellite in the plane" and a sensible default target separation
  automatically.
* **A live link-margin gauge in Vizard** -- deliberately not built this
  phase (see "What Phase 4 adds" above for why forcing it through
  `GenericStorage` would need a fabricated adapter message); if this
  becomes worth doing anyway, the RIGHT path is a real custom Vizard
  protobuf message/panel type, not a reused Battery/DataStorage/FuelTank
  shape.

Beyond that, the "Known limitations" list above is the rest of the honest
map: a handful of schema-valid-but-not-wired-up options (celestial-body
`locationPointing` targets, thrusters, magnetic torque rods, non-Earth
spherical harmonics/magnetometer), navigation error modeling, richer Monte
Carlo retention, and -- the one requiring something this development
sandbox's network policy specifically blocks -- a full simulation run past
SPICE kernel loading, to get the first true end-to-end confirmation
(including `test_two_body_validation.py`'s analytical check, and the new
Phase 4 power-budget/link-budget/station-keeping/phasing-keeping/
Vizard-panel wiring) on top of everything up to that point already being
verified against a real Basilisk install. None of it is blocked on a
design decision; each item is scoped and documented at its own call site
for whoever picks it up next.
