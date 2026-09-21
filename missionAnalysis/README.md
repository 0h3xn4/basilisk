# Constellation mission-analysis simulation (Basilisk)

A 5-year, 3-satellite Earth-observation constellation mission-analysis
simulation built on Basilisk, designed to be comparable to the companion GMAT
script (same mission design: SSO pair + mid-inclination satellite, same bus,
same propulsion, same station-keeping/phasing logic).

## Architecture decisions

This is the "before we lock in the approach" discussion the code follows.

### 1. Orbital dynamics only, not full 6-DOF

Basilisk's `spacecraft.Spacecraft()` hub always integrates both translational
and rotational states -- there is no built-in flag to disable attitude
integration entirely. But nothing requires attaching an attitude
determination/control loop (reaction wheels, star trackers, MRP control,
FSW stack) to it, and this study doesn't need one: none of the four
deliverables (independent SMA station-keeping, in-plane phasing, drag/SRP
accumulation, propellant bookkeeping) depend on attitude.

So the spacecraft's attitude is simply left uncontrolled/unobserved (initial
attitude states default to zero and free-drift for the whole run -- this is
never read or acted on by anything in the script). The real fidelity choice
is in how thrust is applied: rather than pointing a body-fixed thruster
(which would require closing an attitude loop to actually work), each
spacecraft gets an [`extForceTorque`](../src/simulation/dynamics/extForceTorque)
dynamic effector and the station-keeping/phasing controllers write directly
into its `extForce_N` (an inertial-frame force) along the instantaneous
velocity direction. This is exactly the "tangential burn" abstraction a
mission-design tool like GMAT already uses for impulsive/finite maneuvers --
it does not assume or require any particular attitude, and every other
perturbation (gravity, drag, SRP, third-body) is fully physical and
attitude-independent already. This was the single biggest fidelity/runtime
lever available and is why the rest of the architecture is tractable.

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
* **`PhasingKeepingController`** (one instance, governing satellite SSO-2
  relative to SSO-1): a small state machine (`IDLE -> BURN_OUT -> DRIFT ->
  BURN_RESTORE`) implementing the "drift orbit" technique by direct two-body
  (Kepler mean-motion) algebra: solve for the small semimajor-axis offset
  that, given a target correction window, drifts the mean-anomaly error to
  zero; burn to that offset; coast; burn back to nominal SMA. Each
  correction is a single closed-form calculation rather than an iterative
  solve, but because the controller keeps re-evaluating for the rest of the
  5-year run, the *sequence* of corrections is still closed-loop at the
  mission timescale -- residual error from one correction just triggers the
  next.

Both controllers are self-contained, documented, and intentionally simple
enough to retune (deadbands, correction windows, thrust arbitration policy)
without touching the Basilisk wiring in `run_constellation_mission.py`.

**Actuator conflict:** SSO-2 has one thruster shared by two controllers. The
phasing controller checks `altitudeControllerB.burnOn` every tick and stands
down (holding its own state/bookkeeping) whenever altitude keeping is
actively burning -- orbit-safety station-keeping wins, phasing just waits.

### 3. Keeping a 5-year x 3-spacecraft run tractable

The key structural decision is **decoupling the fast numerical integration
from the (comparatively expensive) Python control logic**, via two Basilisk
processes running at two different rates:

* A **fast dynamics process** (default 60 s task rate) holds SPICE, gravity,
  atmosphere/space-weather, drag, SRP, eclipse, and every spacecraft +
  `extForceTorque` effector. All of this executes as compiled C++ during
  `ExecuteSimulation()` with zero Python callbacks per step. Each spacecraft
  also gets its own `svIntegratorRKF78` adaptive-step integrator (rather
  than fixed-step RK4): the 60 s task rate is a message-passing/reporting
  cadence, and RKF78 subdivides further within it only when the local
  dynamics actually demand it (e.g. tighter near a reboost burn), which
  buys back a lot of the accuracy that a strictly fixed step would need a
  much smaller step size to get.
* A **coarse control process** (default 300 s task rate) holds only the two
  Python controllers, i.e. the only code that pays a real per-call Python
  overhead. At 300 s over 5 years that's ~526,000 calls per controller --
  perfectly tractable -- versus tens of millions if control logic ran on the
  fast task.

Everything else that keeps this affordable is really just consequences of
that split:

* Controller telemetry (for the summary plot) is further decimated
  (`log_decimation`, default 12 -> hourly) so 5 years of Python-side lists
  stay at tens of thousands of points instead of ~500K per satellite.
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
5-year run.

### 4. Relativistic correction

Implemented (`_add_relativistic_correction` in `run_constellation_mission.py`,
standard 1PN/Schwarzschild geodesic acceleration term) but **off by
default**. Basilisk has no built-in module for it, so enabling it adds
another per-control-tick Python force computation -- cheap, since it reuses
the existing coarse control cadence, but still: its effect at 570 km LEO
over 5 years is on the order of centimeters to a few meters of secular
drift, dwarfed by the uncertainty already coming from the placeholder drag
coefficient, SRP coefficient, and (especially) the synthetic space-weather
profile. It's included for GMAT-comparability if you want it, not because
it matters at this fidelity level. Pass `enable_relativistic_correction=True`
to `build_simulation()`.

## Files

| File | Purpose |
|---|---|
| `mission_config.py` | All mission constants, orbit design (incl. the RAAN-for-LTDN solve), satellite definitions. Pure `numpy`/stdlib, importable without Basilisk. |
| `generate_space_weather_placeholder.py` | Builds a synthetic multi-year F10.7/Ap table (CelesTrak CSV layout) covering the mission window -- see below for why this has to be synthetic. |
| `constellation_controllers.py` | The two `SysModel` controllers (altitude keeping, phasing keeping). |
| `run_constellation_mission.py` | Builds and runs the full Basilisk simulation; `python3 run_constellation_mission.py` is the entry point. |
| `data/placeholder_space_weather.csv` | Generated output of the space-weather script (regenerate with `python3 generate_space_weather_placeholder.py`). |

## Running

```bash
# from the repo root, with a built Basilisk package on PYTHONPATH:
cd missionAnalysis
python3 generate_space_weather_placeholder.py   # only needed once, or to regenerate
python3 run_constellation_mission.py --years 0.1   # smoke test first
python3 run_constellation_mission.py               # full 5-year run
```

`run_constellation_mission.build_simulation()` returns every Basilisk object
(spacecraft, effectors, controllers, recorders) for interactive
post-processing if the CLI script's summary print + plot isn't enough.

## Assumptions and placeholders to replace

These mirror the placeholders already flagged in the mission statement, plus
a few this implementation had to introduce:

* **Propellant budget (20 kg BOL, all three satellites)** -- not specified in
  the mission statement (only dry mass was). Sized generously for a 5-year
  LEO SSO station-keeping + phasing timeline at 10 mN/1500 s Isp; replace
  once a real propulsion budget/tank sizing exists.
  (`mission_config.PROPELLANT_MASS_BOL_KG`)
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
  placeholder -- irrelevant to every output this study produces (attitude is
  not modeled/controlled) but is a required hub property.
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
- **This script has not been executed** -- see Architecture decision #3.
  It has been checked line-by-line against the actual module source in this
  checkout, but treat the first `--years 0.1` run as the real validation
  step, not this document.
