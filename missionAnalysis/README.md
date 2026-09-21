# Constellation mission-analysis simulation (Basilisk)

A multi-year Earth-observation constellation mission-analysis simulation
built on Basilisk. Originally designed to be comparable to a companion GMAT
script (same mission design: an SSO pair + a mid-inclination satellite, same
bus, same propulsion, same station-keeping/phasing logic); the default
configuration has since grown to a 3-satellite SSO plane (1 chief + 2
followers, each maneuvering to its own time-varying along-track separation
from the chief -- see **Reconfigurable formation flying** below) per updated
mission requirements. The constellation's satellite count, individual orbits,
and ground-station network are all configurable; see `setup_wizard.py` under
**Changing spacecraft/orbit parameters** below.

On top of the original orbital-dynamics/station-keeping/downlink design,
this now also includes: a single-loop attitude pointing controller (antenna
at the ground station during a downlink pass, else solar panel at the sun --
**Architecture decision #7**), a per-satellite power budget that depends on
that real controlled attitude (**#8**), a reported RF downlink link-margin
estimate (**#9**), a smoother/wider-view Vizard visualization with battery
+ data-storage HUD panels (**Vizard visualization** below), and a fuller
end-of-run report (delta-V broken out by cause, attitude pointing duty
cycle/error, power/battery, and the link-margin estimate).

## Architecture decisions

This is the "before we lock in the approach" discussion the code follows.

### 1. Orbital dynamics fully modeled; attitude is one pointing loop, not a full FSW/GNC stack

Basilisk's `spacecraft.Spacecraft()` hub always integrates both translational
and rotational states -- there is no built-in flag to disable attitude
integration entirely. Originally nothing in this study needed a real
attitude loop (independent SMA station-keeping, in-plane phasing, drag/SRP
accumulation, and propellant bookkeeping are all attitude-independent), so
attitude was simply left uncontrolled/unobserved. That has since changed:
solar-panel sun-pointing and antenna-at-ground-station pointing are now
real, physically meaningful requirements (they gate the power budget and,
conceptually, the downlink), so attitude is now actively controlled -- see
**#7** below and `attitude_controllers.py`.

This is still a deliberately narrow slice of "real" GNC, not a full FSW
stack: one body-fixed vector is pointed at a time (a priority choice between
the antenna and the panel normal, not a two-target/gimbaled solution), there
is no reaction wheel array (control torque is applied directly, the same
idealized-actuator philosophy already used for thrust -- see below), no
sensor models (attitude/rate are read directly off the truth state, not
through a `simpleNav`-style noise model), and no imaging/nadir-pointing mode
(the EO instrument's duty cycle is still gated by eclipse/sunlit state only,
independent of attitude, as before). This is enough to make the power
budget's cosine losses and eclipse dependence physically real without taking
on full 6-DOF FSW fidelity -- see **#7** for the reasoning and its limits.

Station-keeping/phasing thrust is unaffected by any of this and remains
its own separate fidelity choice: rather than pointing a body-fixed
thruster (which would couple every station-keeping burn to a slew maneuver),
each spacecraft's [`extForceTorque`](../src/simulation/dynamics/extForceTorque)
dynamic effector has the station-keeping/phasing controllers write directly
into its `extForce_N` (an inertial-frame force) along the instantaneous
velocity direction -- modeled as if through a gimbaled thruster that holds
that direction regardless of body attitude. This is exactly the "tangential
burn" abstraction a mission-design tool like GMAT already uses for
impulsive/finite maneuvers, and every other perturbation (gravity, drag,
SRP, third-body) is fully physical and attitude-independent already. This
decoupling is why adding attitude control for pointing did not also require
reworking the station-keeping/phasing controllers.

### 2. Custom Python control loop around Basilisk's dynamics modules

Basilisk has no equivalent of GMAT's `Target`/`Vary`/`Achieve` differential
corrector. Both maintenance behaviors are implemented instead as plain
threshold/deadband/finite-state-machine controllers, written as pure-Python
`SysModel` subclasses (`constellation_controllers.py`) that Basilisk calls
like any compiled module:

* **`AltitudeKeepingController`** (one per satellite): a smoothed-altitude
  deadband controller. Reboost turns on when the (orbit-period-averaged)
  altitude falls 5 km below nominal, and off once nominal altitude is
  restored -- classic hysteresis, no iteration needed.
* **`PhasingKeepingController`** (one instance per follower satellite in a
  multi-satellite plane, each referenced to that plane's first satellite as
  chief -- see `run_constellation_mission.py`): a small state machine
  (`IDLE -> BURN_OUT -> DRIFT -> BURN_RESTORE`) implementing the "drift
  orbit" technique by direct two-body (Kepler mean-motion) algebra: solve
  for the small semimajor-axis offset that, given a target correction
  window, drifts the mean-anomaly error to its assigned target separation;
  burn to that offset; coast; burn back to nominal SMA. Each correction is a
  single closed-form calculation rather than an iterative solve, but because
  the controller keeps re-evaluating for the rest of the run, the *sequence*
  of corrections is still closed-loop at the mission timescale -- residual
  error from one correction just triggers the next. The *target* separation
  is not fixed for the whole mission: it comes from a `SeparationSchedule`
  (also in `constellation_controllers.py`) that steps through a list of
  distances every few months and holds at the last one, so a follower can be
  commanded to a new relative distance mid-mission without restarting the
  controller. The trigger/restore thresholds are likewise a *fraction* of
  the current target separation rather than a fixed angle, since a fixed
  threshold that's sensible at 1000 km of separation is absurdly loose at 50
  km (see **Reconfigurable formation flying** below).

Both controllers are self-contained, documented, and intentionally simple
enough to retune (deadbands, correction windows, thrust arbitration policy)
without touching the Basilisk wiring in `run_constellation_mission.py`.

**Actuator conflict:** a follower satellite has one thruster shared by two
controllers. The phasing controller checks `altitudeControllerB.burnOn`
every tick and stands down (holding its own state/bookkeeping) whenever
altitude keeping is actively burning -- orbit-safety station-keeping wins,
phasing just waits.

### 3. Keeping a 3-year x 4-spacecraft run tractable

The key structural decision is **decoupling the fast numerical integration
from the (comparatively expensive) Python control logic**, via several
Basilisk processes/tasks running at different rates:

* A **fast dynamics process** (default 60 s task rate) holds SPICE, gravity,
  atmosphere/space-weather, drag, SRP, eclipse, every spacecraft +
  `extForceTorque` effector, and the power-budget objects (solar panel,
  battery, load sinks -- see **#8**; these are also compiled C++ with no
  per-call Python overhead). All of this executes as compiled C++ during
  `ExecuteSimulation()` with zero Python callbacks per step. Each spacecraft
  also gets its own `svIntegratorRKF78` adaptive-step integrator (rather
  than fixed-step RK4): the 60 s task rate is a message-passing/reporting
  cadence, and RKF78 subdivides further within it only when the local
  dynamics actually demand it (e.g. tighter near a reboost burn), which
  buys back a lot of the accuracy that a strictly fixed step would need a
  much smaller step size to get.
* A **coarse control process** (default 300 s task rate) holds the
  station-keeping/phasing Python controllers and the power-budget load gate,
  i.e. the code that pays a real per-call Python overhead but does not need
  to react faster than an orbital timescale. At 300 s over 3 years that's
  ~316,000 calls per controller -- perfectly tractable -- versus tens of
  millions if control logic ran on the fast task.
* A **separate, finer attitude-control task** (default 30 s, same process,
  see `mission_config.ATTITUDE_CONTROL_TASK_RATE_S`) holds only
  `AttitudePointingController` (**#7**). Attitude dynamics settle much
  faster than orbital station-keeping/phasing corrections do, so reusing the
  300 s cadence above would under-sample the attitude loop; a dedicated
  finer task keeps that loop responsive without forcing every other
  controller onto the same (much more expensive, over a whole mission)
  cadence.

Everything else that keeps this affordable is really just consequences of
that split:

* Controller telemetry (for the summary plot) is further decimated
  (`log_decimation`, default 12 -> hourly) so 3 years of Python-side lists
  stay at tens of thousands of points instead of ~300K per satellite.
* Trajectory state recorders run on their own even-coarser task (hourly) for
  the same reason -- they're for post-run plots/exports, not control.
* Earth gravity defaults to degree/order 10 (mission statement's low end of
  10-20) specifically for run-time headroom; see `mission_config.EARTH_GRAV_DEGREE`
  to raise it once you've characterized run time on your hardware.
* Eclipse/thrust gating resolves at the 300 s control cadence, not
  continuously. That's a real approximation (a 30-40 min eclipse pass gets
  ~6-8 samples), acceptable for mission-design-level Δv/propellant
  bookkeeping but not for precise duty-cycle telemetry.

None of this was validated against an actual run time on real hardware in
this environment -- **this Basilisk checkout is not built here** (no
`Basilisk` Python package; building it is a full Conan/CMake/SWIG C++ build,
well outside this session's scope), so the script has been checked carefully
against the actual installed-module source (grep'd APIs, matched against
existing `examples/*.py` usage patterns) but not executed end to end. Build
Basilisk (`pip install .` from the repo root, or use the project's Docker
image) and run a short `--years 0.1` smoke test before trusting a full
3-year run.

### 4. Relativistic correction

Implemented (`_add_relativistic_correction` in `run_constellation_mission.py`,
standard 1PN/Schwarzschild geodesic acceleration term) but **off by
default**. Basilisk has no built-in module for it, so enabling it adds
another per-control-tick Python force computation -- cheap, since it reuses
the existing coarse control cadence, but still: its effect at 570 km LEO
over 3 years is on the order of centimeters to a few meters of secular
drift, dwarfed by the uncertainty already coming from the placeholder drag
coefficient, SRP coefficient, and (especially) the synthetic space-weather
profile. It's included for GMAT-comparability if you want it, not because
it matters at this fidelity level. Pass `enable_relativistic_correction=True`
to `build_simulation()`.

### 5. Communications / data downlink (Vizard comm rings)

Added on top of the original design: each satellite gets an EO instrument
(`simpleInstrument`, data generation gated on/off by the existing eclipse
module -- an EO payload only images sunlit ground), an on-board storage
unit (`partitionedStorageUnit`), and a downlink transmitter
(`spaceToGroundTransmitter`) with access to a small placeholder ground
network (`GroundLocation`), following the same wiring as Basilisk's own
`scenarioGroundDownlink` example. This is standard onboard-data-handling
infrastructure and needs no attitude model itself (the transmitter's
data throughput/access gating is a range/elevation check on `GroundLocation`,
not a pointing constraint) -- attitude only enters the picture via the
*separate* antenna-pointing controller in decision #7, which does not
change anything here.

When `--vizard`/`--vizard-save` is enabled, each satellite's antenna is
rendered as a `vizInterface.Transceiver` fed by *both* the instrument's and
the transmitter's data-node messages. Basilisk's own convention (see
`vizInterface.cpp`) is: a data node reporting a positive baud rate ("data
provided") shows as receiving (purple rings), negative ("data consumed")
shows as sending (green rings). The EO instrument is always positive when
active and the transmitter is always negative, so this reproduces exactly
the two-color behavior described in the feature request, plus a
`GenericStorage` HUD panel per satellite tracking the storage level those
two events raise and lower. See `communications.py`'s module docstring for
the full mechanism.

### 6. Reconfigurable formation flying (time-varying separation, fractional tolerance)

Added per updated mission requirements ("maintain roughly the same orbit, not
super tight; different relative distances per satellite; reconfigure every
few months, order of 1000 km down to 50 km; a slow, low-thrust reconfiguration
is fine; no payload-activity conflict"):

* **`SeparationSchedule`** (`constellation_controllers.py`) replaces the old
  single fixed target separation per follower with a list of target distances
  [km] plus a hold interval [days]: `value_at(t)` steps through the list as
  mission-elapsed time advances, holding at the last entry once the list runs
  out (or looping, if `loop=True`). `PhasingKeepingController` reads its
  target from a `SeparationSchedule` every tick rather than from a constant,
  so a follower drifts to a new commanded distance on its own schedule with
  no code change or restart needed mid-mission. Each follower in the SSO
  plane gets its own independent `SeparationSchedule`, which is how
  "different relative distances" (plural, per-satellite) is represented --
  see `mission_config._build_satellites()` and
  `constellation_setup.json`'s `sso_plane.follower_schedules`.
* **Fractional, not fixed-angle, tolerance**: `PHASING_TOLERANCE_FRACTION`/
  `PHASING_RESTORE_TOLERANCE_FRACTION` scale with the *current* target
  separation instead of being a fixed degree value -- see the rationale in
  **Assumptions and placeholders to replace** below. This is also the "not
  super tight, a bit of offset is better for maintenance" requirement in
  practice: a 10%-of-target trigger threshold is deliberately loose, and the
  same closed-form drift-orbit maneuver used for ordinary station-keeping
  (Architecture decision #2) handles a 1000 km -> 50 km reconfiguration the
  same way it handles a small correction, just with a larger semimajor-axis
  offset and (per `PHASING_CORRECTION_WINDOW_DAYS`) a longer, low-thrust
  drift -- consistent with "it's ok if it takes weeks, not required high
  thrust."
* **No payload-activity conflict by construction**: the EO instrument's duty
  cycle (`communications.InstrumentEclipseGate`) is gated only by eclipse/
  sunlit state, never by thruster state, and the phasing/altitude
  controllers' thrust arbitration (Architecture decision #2's "actuator
  conflict" note) is likewise independent of instrument activity. "We can do
  maneuvers without PL activity" required no code change -- the two were
  already decoupled.

### 7. Attitude pointing (antenna vs. sun, one target at a time)

Added per updated requirements: point the antenna at the ground station
whenever a downlink pass is possible, else point the solar panel at the sun.
`AttitudePointingController` (`attitude_controllers.py`, one instance per
satellite) decides between the two and drives toward whichever is active:

* **Target selection**: every tick, it checks each configured ground
  station's `GroundLocation.accessOutMsgs` for this satellite; if one or
  more report `hasAccess`, it picks the highest-elevation one and targets
  the antenna boresight (`mission_config.ANTENNA_BORESIGHT_B`) at it (via
  that station's `currentGroundStateOutMsg` position). Otherwise it targets
  the solar panel normal (`PANEL_NORMAL_B`) at the sun (from the SPICE sun
  ephemeris already used for SRP/eclipse). This priority is why the
  requirement reads "sun-pointing whenever possible" rather than "always":
  a downlink pass is short, scheduled, and valuable enough to interrupt
  sun-pointing for; the panels get the rest of the time.
* **Guidance math**: the same eigen-axis / `-tan(phi/4)` MRP tracking-error
  construction Basilisk's own [`locationPointing`](../src/fswAlgorithms/attGuidance/locationPointing)
  module documents, reimplemented directly in Python (`_mrp_to_dcm` +
  the eigen-axis computation in `AttitudePointingController.UpdateState`)
  rather than wiring that C module plus a second instance for the sun plus
  a message-level mode-arbitration router -- one controller owns the whole
  antenna-vs-sun decision directly, keeping the same "custom Python control
  loop" pattern already used for station-keeping/phasing (decision #2).
  Verified against hand-computed cases (aligned/orthogonal/anti-parallel
  pointing vectors) since Basilisk isn't built in this environment -- see
  the "not executed end to end" note in decision #3.
* **Control law**: the textbook simple MRP regulator,
  `torque = -K*sigma_BR - P*omega_BR_B`, the same law Basilisk's own
  [`mrpFeedback`](../src/fswAlgorithms/attControl/mrpFeedback) reduces to
  with no reaction wheels, no reference angular rate, and no integral term.
  Applied as an idealized external torque
  (`extForceTorque.extTorquePntB_B`, direct assignment, clamped to
  `ATTITUDE_CONTROL_MAX_TORQUE_NM`) on the SAME effector object the
  station-keeping/phasing controllers already use for thrust -- force and
  torque are independent fields on that effector, so there is no conflict,
  and no second dynamic effector is needed per satellite.
* **No reaction wheels, no sensor noise, no imaging mode**: this is a
  deliberately narrow slice of real GNC -- see decision #1 for the full
  scope/limits discussion (one target at a time, idealized torque actuator,
  truth-state attitude/rate rather than a `simpleNav`-style noisy estimate,
  no nadir-pointing imaging mode).

### 8. Power budget (solar panel + battery + loads, attitude/eclipse -dependent)

Added per updated requirements ("compute the power budget as well"). Uses
Basilisk's `simplePower*` subsystem (`simpleSolarPanel`, `simpleBattery`,
`simplePowerSink` -- the same modules and wiring as
`examples/scenarioPowerDemo.py`), one full set per satellite, in
`power_budget.py`:

* **Generation**: `simpleSolarPanel` computes generated power from the
  panel area/efficiency (`mission_config.SOLAR_PANEL_AREA_M2`/
  `SOLAR_PANEL_EFFICIENCY`), the real cosine loss between `PANEL_NORMAL_B`
  and the sun direction (driven by the *actual controlled* attitude from
  decision #7, not a flat average), and the same eclipse shadow factor
  everything else in this script uses -- so a satellite genuinely generates
  less power while sun-pointing is being interrupted for a downlink pass,
  or while eclipsed.
* **Loads**: three separate `simplePowerSink` instances per satellite so
  each shows up independently in the reported budget -- a static always-on
  bus load (`BUS_IDLE_POWER_W`), the EO instrument
  (`EO_INSTRUMENT_POWER_W`, gated on exactly when
  `communications.InstrumentEclipseGate` has the instrument actually
  collecting data), and the downlink transmitter (`DOWNLINK_TX_POWER_W`,
  gated on exactly when `AttitudePointingController` reports it is
  antenna-pointing -- see `power_budget.PowerLoadGate`).
* **Storage**: one `simpleBattery` per satellite (`BATTERY_CAPACITY_WH`,
  initial state of charge `BATTERY_INITIAL_SOC`) nets all four power nodes
  and tracks stored energy over the mission; the end-of-run report and
  summary plot both show state of charge, and flag if a satellite's battery
  was ever fully depleted.
* **No attitude power draw is modeled** (e.g. reaction-wheel/torque-rod
  power) -- consistent with decision #7 not modeling reaction wheels at
  all; the idealized torque actuator is treated as free, folded into the
  flat bus idle load if you want to account for it.

### 9. RF downlink link-margin estimate (reported only, does not affect the simulated downlink)

Added per updated requirements ("accept inputs for RF parameters"). A
simplified free-space-path-loss link budget
(`run_constellation_mission._rf_link_margin_db`), computed once per
satellite at the end of a run from its own altitude and the loosest
configured ground-station elevation mask (worst-case slant range via the
standard spherical-Earth elevation-range relation,
`_worst_case_slant_range_m`):

```
EIRP = TX power + TX antenna gain - implementation loss
FSPL = 20*log10(4*pi*range*frequency / c)
Eb/N0 = EIRP - FSPL + ground antenna gain - 10*log10(k*T_noise) - 10*log10(data rate)
margin = Eb/N0 - required Eb/N0
```

This is a genuine, if simplified, link budget (no atmosphere/rain,
pointing-loss beyond the flat `RF_IMPLEMENTATION_LOSS_DB` term, or
coding-gain modeling) -- with the placeholder RF parameters this ships
with, it reports a slightly *negative* margin at worst-case range, which is
a real and useful finding: 150 Mbps X-band at 15 W / 6 dBi against a 45 dBi
/ 500 K ground station does not actually close at ~2200 km slant range, and
either the data rate needs to drop, the TX power/antenna gain needs to go
up, or the ground segment needs a bigger/quieter receiver. It is reported
only -- it does **not** affect `DOWNLINK_BAUD_RATE_BPS`, the simulated
downlink data flow, or any access gating anywhere else in this script; the
downlink transmitter has no concept of link margin.

## Files

| File | Purpose |
|---|---|
| `mission_config.py` | All mission constants, orbit design (incl. the RAAN-for-LTDN solve), satellite/ground-station definitions. Pure `numpy`/stdlib, importable without Basilisk. |
| `setup_wizard.py` | **Interactive** setup wizard -- constellation size, per-satellite orbits, ground stations, bus/propulsion/epoch/etc. Writes `constellation_setup.json` + applies scalar settings via `configure_mission.py`. See below. |
| `configure_mission.py` | Non-interactive CLI to edit *scalar* spacecraft/orbit parameters in `mission_config.py` one at a time -- see below. Doesn't touch satellite count or ground stations; use the wizard for that. |
| `constellation_setup.json` | Generated by `setup_wizard.py` (git-ignored, not committed): the SSO plane + standalone satellites + ground stations actually used, overriding `mission_config.py`'s hardcoded defaults when present. |
| `generate_space_weather_placeholder.py` | Builds a synthetic multi-year F10.7/Ap table (CelesTrak CSV layout) covering the mission window -- see below for why this has to be synthetic. |
| `constellation_controllers.py` | The two orbital `SysModel` controllers (altitude keeping, phasing keeping) plus `SeparationSchedule`. |
| `attitude_controllers.py` | `AttitudePointingController` -- antenna-at-ground-station-else-sun-pointing attitude control (see Architecture decision #7). |
| `power_budget.py` | Per-satellite solar panel + battery + load power budget, and the load-gating `PowerLoadGate` (see Architecture decision #8). |
| `communications.py` | Per-satellite EO data generation, on-board storage, ground downlink, and the eclipse-gated instrument duty cycle -- drives the Vizard comm-rings visualization. |
| `run_constellation_mission.py` | Builds and runs the full Basilisk simulation; `python3 run_constellation_mission.py` is the entry point. |
| `data/placeholder_space_weather.csv` | Generated output of the space-weather script (regenerate with `python3 generate_space_weather_placeholder.py`). |

## Running

```bash
# from the repo root, with a built Basilisk package on PYTHONPATH:
cd missionAnalysis

# optional: configure your constellation interactively first (satellite
# count, orbits, ground stations, bus/propulsion/epoch/etc.) -- see
# "Changing spacecraft/orbit parameters" below. Skip this to use the
# hardcoded default constellation.
python3 setup_wizard.py

python3 generate_space_weather_placeholder.py   # only needed once, or to regenerate
python3 run_constellation_mission.py --years 0.1   # smoke test first
python3 run_constellation_mission.py               # full run

# Vizard visualization (requires a Vizard-enabled Basilisk build):
python3 run_constellation_mission.py --years 0.05 --vizard-save mission_playback
```

**"Built Basilisk package" means a build of *this checkout*.** This script
uses a few modules that are new/fork-specific here (`simHelpers`,
`spaceWeatherData`), so a Basilisk build from a different, older checkout on
the same machine will fail with import errors like
`ImportError: cannot import name 'simHelpers' from 'Basilisk.utilities'`. If
that happens, check which package Python is actually resolving:

```bash
python3 -c "import Basilisk; print(Basilisk.__file__)"
```

If that path isn't under *this* checkout's `dist3/` (e.g. it points at a
different clone you built previously), build from this checkout instead
(`python3 conanfile.py` from the repo root -- see `docs/source/Build.rst`)
and make sure that build, not the older one, is what's on your `PYTHONPATH`
or active virtualenv.

`run_constellation_mission.build_simulation()` returns every Basilisk object
(spacecraft, effectors, controllers, recorders, and the `viz` handle when
Vizard is enabled) for interactive post-processing if the CLI script's
summary print + plot isn't enough.

### Vizard visualization

`--vizard` wires up `vizSupport.enableUnityVisualization()`; `--vizard-save
PATH` does the same and also writes a `<PATH>_UnityViz.bin` playback file
(under `_VizFiles/`) you can open in the Vizard app afterwards. It's off by
default. A few things worth knowing about how it's set up:

* **Attitude is now shown** (`viz.settings.spacecraftCSon = 1`): since
  Architecture decision #7 added a real, actively-controlled attitude, the
  body frame drawn on each spacecraft is now physically meaningful -- watch
  it swing to track the ground station during a pass and back to sun
  -pointing afterward. There is still no thruster-plume effector list (this
  script commands station-keeping/phasing thrust as a direct inertial-frame
  force, not through a body-mounted `thrusterDynamicEffector`, so there is
  no thruster geometry for Vizard to render) and no reaction-wheel geometry
  (none is modeled -- see decision #7).
* **The whole constellation is shown by default, not a close-up of one
  satellite**: `viz.settings.mainCameraTarget` is set to Earth's display
  name. Without this, Vizard's own default startup camera locks onto a
  close-up view of the first spacecraft added, which is the "why is it
  zoomed in on one satellite" behavior this fixes -- zoom/pan freely from
  there in the Vizard app itself.
* **Playback is smooth, not choppy/fast-looking**: the vizInterface module
  now runs on its own dedicated task at `--vizard-rate-s` (default
  `mission_config.VIZARD_RECORD_RATE_S`, 60 s), not the hourly `logTask`
  the trajectory/storage/power recorders use. Hourly frames used to mean
  each spacecraft only advanced through the visualization ~1.6 times per
  orbit between recorded points -- at a 570 km SSO altitude that is a
  ~28,000 km jump between frames, which is what actually caused the
  "sped up, laggy, jumping around" playback this replaces: Vizard had
  nothing smooth to interpolate between. A finer dedicated task fixes that,
  at the cost of a bigger output file for a long run, which is why a short
  `--years` window (e.g. `0.05`, about 18 days) is still recommended for
  Vizard rather than the full mission -- use `--vizard-rate-s` to trade
  smoothness against file size.
* **Live data on screen**: each satellite gets two `GenericStorage` HUD
  panels -- "Data Storage" (on-board data, from decision #5) and "Battery"
  (state of charge, from decision #8's power budget, via a small message
  -shape adapter, `_BatteryVizAdapter` in `run_constellation_mission.py`,
  since Vizard's storage-panel type only understands the data-storage
  message shape). Both update live as the playback runs.
* `liveStream` is exposed (`--vizard-live`) but is of limited use here: the
  whole run executes as one blocking call into compiled Basilisk code (see
  Architecture decision #3), so there's no wall-clock-paced moment for a
  live viewer to watch frame by frame. The saved-file path is the intended
  way to inspect this mission in Vizard.

**Vizard itself is a separate application, not part of the Basilisk Python
package.** Download and install it once for your platform -- see
`docs/source/Vizard/VizardDownload.rst` in this repo for the current direct
download links (macOS/Linux/Windows).

To actually watch a run:

```bash
python3 run_constellation_mission.py --years 0.05 --vizard-save mission_playback
```

This writes `_VizFiles/mission_playback_UnityViz.bin` next to the script
(the run's final message prints the exact path). Then:

1. Open the Vizard app.
2. Its startup panel has a **Select** button -- click it and navigate to
   that `.bin` file.
3. Click **Start Visualization**.
4. Use the slider at the bottom to scrub through the run, the play/pause
   button to run it, and the +/- buttons to change playback speed. It opens
   in a planet-centric view showing the full constellation and its ground
   tracks around Earth (see the "whole constellation is shown by default"
   note above); double-click a spacecraft to switch to a close-up
   spacecraft-centric view of it instead.

On macOS you can skip steps 1-2 and launch straight into a file from the
terminal:

```bash
open /Applications/Vizard.app --args -loadFile "$PWD/_VizFiles/mission_playback_UnityViz.bin"
```

(Linux/Windows Vizard builds accept the same `-loadFile <path>` argument;
launch the extracted binary/`.exe` directly with it instead of `open`.)

A version note (only used because it's what's committed here): a bare
filename like `--vizard-save mission_playback` used to resolve to an
absolute path at the filesystem root inside `vizSupport` (`/_VizFiles/...`,
which fails to write with a permission error) -- `build_simulation()` now
anchors a bare name to the current directory automatically, so the command
above just works. If you're on an older pull of this script, either update
or pass a path with a directory component (`./mission_playback`).

### Changing spacecraft/orbit parameters

`mission_config.py` is the single source of truth for every spacecraft,
orbit, and ground-station parameter -- `run_constellation_mission.py`,
`constellation_controllers.py`, and `communications.py` all read their
constants from it, so changing what it produces (by hand, or with either
tool below) is the only place you need to touch. There are two tools,
covering two different kinds of change:

#### `setup_wizard.py` -- interactive, covers everything including structure

Use this for anything that changes the *shape* of the constellation: how
many satellites, their individual orbits, how many ground stations and
where. It also asks for the same scalar settings `configure_mission.py`
covers (bus, propulsion, epoch, duration, power budget, RF/downlink link
budget, attitude control, deadband, phasing tolerance, gravity degree),
applying them through that script so both tools stay consistent.

```bash
python3 setup_wizard.py
```

Answer the prompts (Enter accepts the default shown in `[brackets]`). It
writes `constellation_setup.json`, which -- once it exists -- is what
actually defines the constellation's satellite count and every satellite's
orbit, overriding `mission_config.py`'s hardcoded 2-SSO-satellites-plus-1
-standalone default (see that module's docstring). Re-running the wizard
shows your previous answers as the new defaults, so tweaking just one
setting later is still just Enter-through-the-rest. Delete
`constellation_setup.json` to go back to the hardcoded default constellation.

At the end it offers to run a quick `--years 0.05` smoke test so you can
confirm the new setup actually builds and runs.

#### `configure_mission.py` -- non-interactive, scalars only

For quickly changing one or two *scalar* values (bus mass, Cd/Cr/areas,
propulsion, epoch, mission duration, power budget, RF/downlink link budget,
attitude control, altitude deadband, phasing tolerance, gravity degree)
without going through every wizard prompt:

```bash
# preview changes without writing anything
python3 configure_mission.py --dry-run --propellant-kg 50

# bump propellant budget and shorten the mission for a quick study
python3 configure_mission.py --propellant-kg 50 --epoch 2030-01-01 --mission-years 2
```

Run with `--help` for the full list. It only rewrites the specific
`NAME = <value>` line(s) you pass a flag for -- every comment, docstring,
and the derived-value formulas (`A_NOMINAL_M`, `SSO_RAAN_DEG`,
`ORBIT_PERIOD_S`, ...) are left as Python expressions in the file and
recompute correctly the next time it's imported; you never set those
directly. It prints the old value, the new value, and the field's current
inline comment for each change so you can spot a comment that now reads as
stale (e.g. one that names the old value in words) and fix it by hand --
comments are not rewritten, only the value is.

Note: this script also still has `--altitude-km`/`--sso-*`/`--midinc-*`
flags for the same scalars `setup_wizard.py` asks about, but **these are
inert once `constellation_setup.json` exists** (that file is what's
actually used for the constellation's structure at that point) -- use the
wizard for the constellation itself, and reserve these flags for editing
the *fallback defaults* used if you later delete that file.

## Assumptions and placeholders to replace

These mirror the placeholders already flagged in the mission statement, plus
a few this implementation had to introduce:

* **Propellant budget (20 kg BOL, all four satellites)** -- not specified in
  the mission statement (only dry mass was). Sized generously for a 3-year
  LEO SSO station-keeping + phasing timeline at 10 mN/1500 s Isp, including
  the reconfiguration maneuvers described below; replace once a real
  propulsion budget/tank sizing exists.
  (`mission_config.PROPELLANT_MASS_BOL_KG`)
* **`PROPULSION_TYPE`** ("Hall-effect thruster (placeholder pending hardware
  selection)") is a free-text label you can set via `setup_wizard.py` or
  `configure_mission.py --propulsion-type`, carried only into
  `mission_config.py`'s own text -- it documents which hardware assumption
  `THRUST_N`/`ISP_S`/`PROPELLANT_MASS_BOL_KG` correspond to but does not
  itself affect the simulation.
- **Mid-inclination satellite orbit** -- RAAN, eccentricity, and AOP are all
  placeholders (`0`, `0`, `0`) per the mission statement's own "currently a
  placeholder" / "coverage-driven" framing. (`mission_config.MIDINC_*`)
- **RAAN-for-LTDN solve** uses a low-precision Sun-position algorithm
  (~0.01 deg, ~±16 min equation-of-time error), fine for "~10:30 LTDN" but
  not launch-epoch-final. Swap in a SPICE-based Sun ephemeris lookup at the
  real epoch once it's fixed. (`mission_config.raan_for_ltdn_deg`)
- **Multi-year space-weather profile is synthetic**, not real observed/
  forecast data -- see the long comment at the top of
  `generate_space_weather_placeholder.py` for why (CelesTrak data doesn't
  reach 5+ years into the future). It's shaped like a real solar cycle
  (smooth ~11-year modulation, day-to-day persistence, occasional storms)
  but the actual numbers are not a forecast of anything. Replace with a real
  CelesTrak extract as launch approaches.
- **Earth gravity model**: GGM03S spherical harmonics, degree/order 10 by
  default (mission statement's 10-20 range, low end for run-time headroom).
  (`mission_config.EARTH_GRAV_DEGREE`)
- **Spacecraft inertia** (`IHubPntBc_B`) is an arbitrary generic small-sat
  placeholder -- no real bus layout exists in this study. Unlike before, it
  IS now physically exercised: `attitude_controllers.py` actively controls
  attitude against this inertia, and its gains
  (`ATTITUDE_CONTROL_K`/`ATTITUDE_CONTROL_P`) are tuned against this
  specific placeholder value. Retune those gains (or re-derive them from
  the standard MRP-regulator natural-frequency/damping relations) if this
  inertia is ever replaced with real values.
- **Propellant-mass bookkeeping** is an explicit-Euler rocket-equation
  integration done in the Python controllers (updating `hub.mHub` directly),
  not Basilisk's `fuelTank` state effector. That effector is normally driven
  through a body-frame `thrusterDynamicEffector`, which would reintroduce
  the attitude-geometry modeling this study deliberately avoids (see
  Architecture decision #1). Fine for Δv/mass-budget-level mission analysis;
  not flight-software-grade mass property propagation.
- **Eclipse/thrust gating resolution** is tied to the 300 s control cadence,
  not continuous -- see Architecture decision #3.
- **Altitude smoothing window** is one nominal orbital period (~96 min),
  chosen to reject J2 short-period oscillation without unduly delaying
  reboost trigger; not independently tuned/validated.
- **Phasing controller correction window** (21 days) and **max drift safety
  cap** (90 days) are reasonable-guess tuning parameters, not derived from a
  requirement; adjust in `mission_config.py` if the real ops concept has a
  target response time.
- **`_DEFAULT_FOLLOWER_SCHEDULES`** (the two followers' default separation
  schedules: 1000/500/250/100/50 km every 90 days, and 500/200/750/100 km
  every 120 days) is a made-up example to demonstrate different, independently
  time-varying relative distances per follower -- it is not a real ops plan.
  Set the real schedule per follower via `setup_wizard.py` (prompted right
  after the SSO plane's orbital elements) or by hand-editing
  `constellation_setup.json`'s `sso_plane.follower_schedules`.
  (`mission_config._DEFAULT_FOLLOWER_SCHEDULES`)
- **`PHASING_TOLERANCE_FRACTION`** (0.10) and **`PHASING_RESTORE_TOLERANCE_FRACTION`**
  (0.02) are reasonable-guess tuning parameters, not derived from a
  requirement. They're expressed as a *fraction of the current target
  separation* rather than a fixed angle/distance specifically because the
  mission now spans a 1000 km-50 km range of target separations: a fixed
  threshold sized for 1000 km (e.g. ~1 deg, ~82 km at 570 km altitude) would
  never be tight enough to trigger a correction once a follower is holding
  50 km, while one sized for 50 km would fire constantly at 1000 km. A
  fractional threshold scales with whatever the current target happens to
  be, which is also a reasonable proxy for "not super tight, a bit of offset
  is better for maintenance" -- tighten/loosen per satellite, or replace with
  a real dV-vs-tightness optimum, once the ops concept is final.
- **First real `--years 0.1` run surfaced a phasing-controller bug, now
  fixed**: the phasing error was computed from *osculating* mean anomaly,
  which carries J2 short-period oscillation that two satellites 180 deg
  apart sample very differently at any given instant even when their mean
  elements match exactly. That noise was large enough to spuriously cross
  the 1 deg trigger threshold roughly once per orbit, so the controller was
  "correcting" phasing error that wasn't secularly real -- ~31.89 m/s of
  phasing dV in 36.5 days for a pair that started exactly 180 deg apart on
  identical orbits, versus a few cm/s expected. `PhasingKeepingController`
  now smooths its error signal over one orbital period (circular mean, to
  handle the +/-180 deg wrap correctly), the same fix already applied to
  `AltitudeKeepingController`'s altitude signal for the same reason. Fixing
  this also surfaced a second issue: SSO-2's altitude and phasing
  controllers were each keeping an independent belief about how much
  propellant was left in its one physical tank; they now share a single
  tracker (see `PhasingKeepingController._propellant_tracker()`). Re-run
  `--years 0.1` after pulling this fix and compare the phasing dV -- it
  should now be orders of magnitude smaller. This script has otherwise only
  been run this once; treat every number here as provisional until you've
  run your own validation.
- **Communications/data-handling values are all placeholders**: EO payload
  data rate (50 Mbps), downlink rate (150 Mbps), on-board storage capacity
  (~32 GB), and the two-station ground network (Svalbard + Boulder) are all
  guesses for plausibility, not a real link budget or ground-segment plan.
  (`mission_config.GROUND_STATIONS`, `EO_INSTRUMENT_BAUD_RATE_BPS`,
  `DOWNLINK_BAUD_RATE_BPS`, `DATA_STORAGE_CAPACITY_BITS`)
- **Instrument antenna placement/geometry for Vizard** (`transceiver.r_SB_B`,
  `fieldOfView` in `run_constellation_mission.py`) is a placeholder -- there
  is no bus layout in this study. `normalVector` is now set from
  `mission_config.ANTENNA_BORESIGHT_B`, so the drawn antenna direction *is*
  now consistent with what `AttitudePointingController` is actually
  pointing (unlike before); the ring color/timing itself still comes from
  the data-node baud sign, unaffected by any of this.
- **Power budget** (panel area/efficiency, bus/instrument/downlink power
  draws, battery capacity/initial state of charge) is entirely placeholder
  -- no EPS design was given in the mission statement. Set real values via
  `setup_wizard.py`'s "Power budget" section or `configure_mission.py`'s
  `--panel-*`/`--bus-idle-power-w`/`--instrument-power-w`/
  `--downlink-tx-power-w`/`--battery-*` flags.
  (`mission_config.SOLAR_PANEL_AREA_M2` and neighbors)
- **RF link budget parameters** (antenna gains, system noise temperature,
  implementation loss, required Eb/N0, carrier frequency) are placeholders
  feeding the *reported* link-margin estimate only (Architecture decision
  #9) -- they do not affect the simulated downlink. With the shipped
  defaults the estimate comes out slightly negative at worst-case range;
  see decision #9 for why that is a legitimate finding, not a bug, and set
  real values via `setup_wizard.py`'s "RF / downlink link budget" section
  or `configure_mission.py`'s `--rf-*`/`--downlink-*` flags once a real link
  budget exists. (`mission_config.RF_FREQUENCY_HZ` and neighbors)
- **Attitude control axes/gains** (`ANTENNA_BORESIGHT_B`, `PANEL_NORMAL_B`,
  `ATTITUDE_CONTROL_K`/`_P`/`_MAX_TORQUE_NM`) are placeholders -- no bus
  layout or ADCS hardware selection exists in this study. The gains are
  tuned (see Architecture decision #7) against the placeholder inertia
  above for a settling time well inside the 30 s attitude-control cadence;
  set real values via `setup_wizard.py`'s "Attitude control" section or
  `configure_mission.py`'s `--antenna-boresight-b`/`--panel-normal-b`/
  `--attitude-*` flags.
