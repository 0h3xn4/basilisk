#
#  ISC License
#
#  Copyright (c) 2026, Autonomous Vehicle Systems Lab, University of Colorado at Boulder
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
#  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
#  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
#  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
#  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
#  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
#  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#

"""One-off generator for missionstudio/scenarios/templates/*.json -- run
directly (``python3 scripts/_generate_templates.py``) whenever a template
needs regenerating after a schema change. Not part of the installed
package and not imported by anything else; building the templates through
``schema.scenario`` dataclasses + ``Scenario.validate()`` (rather than
hand-writing JSON) is what guarantees they're actually schema-valid --
this script is the source of truth for that construction logic, kept
around instead of thrown away so future schema/field changes have a clear
place to regenerate from.
"""

from __future__ import annotations

from pathlib import Path

from missionstudio.engine.constellation import WalkerConstellationRequest, generate_walker_constellation
from missionstudio.schema.scenario import (
    DispersionConfig,
    GravityConfig,
    GroundStationConfig,
    MonteCarloConfig,
    OrbitIC,
    PhasingKeepingConfig,
    PowerConfig,
    Scenario,
    SensorConfig,
    ActuatorConfig,
    SimSettings,
    SpacecraftConfig,
    StationKeepingConfig,
)

OUT_DIR = Path(__file__).resolve().parent.parent / "missionstudio" / "scenarios" / "templates"

_INERTIA_SMALL = [5.0, 0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 5.0]
_INERTIA_MEDIUM = [12.5, 0.0, 0.0, 0.0, 12.5, 0.0, 0.0, 0.0, 7.5]


def _save(scenario: Scenario, filename: str) -> None:
    scenario.validate()  # fail loudly here, not for whoever opens the file later
    path = OUT_DIR / filename
    scenario.save(path)
    print(f"wrote {path}")


def build_01_two_body_circular_orbit() -> Scenario:
    return Scenario(
        name="01 - Two-body circular orbit",
        description=(
            "The simplest possible orbit: a single spacecraft in a circular low-Earth orbit around a "
            "point-mass Earth (no J2, no drag, no third-body gravity, no attitude dynamics -- "
            "simulation_mode is 'orbit_only'). This is the orbital-mechanics equivalent of a 'hello "
            "world' -- a clean two-body Keplerian orbit with nothing else going on.\n\n"
            "What to look at: plot 'sat-1.position_N' after running -- it traces a perfect circle in "
            "the orbit plane. The orbital period should match Kepler's third law, "
            "T = 2*pi*sqrt(a^3/mu), for a = 6778 km and Earth's mu (~398600.4418 km^3/s^2): about "
            "5554 s (~92.6 minutes), so a 1-day run completes about 15.5 orbits.\n\n"
            "Try changing: the semi_major_axis_km (higher = slower, longer period), the "
            "inclination_deg (watch the ground track in Vizard change), or the eccentricity (still "
            "0 here -- see '02 - Elliptical orbit with perturbations' for a non-circular example)."
        ),
        epoch_utc="2030-01-01T00:00:00",
        simulation_mode="orbit_only",
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        sim_settings=SimSettings(duration_days=1.0, dynamics_task_rate_s=30.0, integrator="rkf78"),
        spacecraft=[
            SpacecraftConfig(
                name="sat-1",
                orbit=OrbitIC(type="classical_elements", semi_major_axis_km=6778.0, eccentricity=0.0,
                               inclination_deg=51.6, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0),
                dry_mass_kg=500.0,
            ),
        ],
    )


def build_02_elliptical_orbit_with_perturbations() -> Scenario:
    return Scenario(
        name="02 - Elliptical orbit with perturbations",
        description=(
            "A geostationary transfer orbit (GTO)-like eccentric orbit, with Earth's oblateness (J2, "
            "via 8th-degree spherical harmonics) and third-body gravity from the Sun and Moon all "
            "switched on. dynamics_task_rate_s is deliberately fine (1.0 s) here: coarser rates "
            "introduce real truncation error into the spherical-harmonics gravity term itself (see "
            "this project's own README, 'What Phase 6 (Mission Sequence architecture) adds', for the "
            "measured effect of this on a real Basilisk run) -- always use a fine rate together with "
            "central_body_degree > 0, not just for point-mass orbits.\n\n"
            "What to look at: plot 'sat-1.position_N' and watch the orbit visibly precess over the "
            "3-day run -- J2 causes the right ascension of the ascending node (RAAN) to regress and "
            "the argument of periapsis to rotate, effects a pure two-body orbit ('01') never shows. "
            "Compare 'sat-1.velocity_N' magnitude at periapsis vs. apoapsis to see orbital speed vary "
            "with a large eccentricity (0.7) -- much faster near Earth, much slower far away.\n\n"
            "Try changing: central_body_degree back to 0 to see the perturbation-free case for "
            "comparison, or third_body_perturbers to just [\"moon\"] or [\"sun\"] to isolate each "
            "effect."
        ),
        epoch_utc="2030-01-01T00:00:00",
        simulation_mode="orbit_only",
        gravity=GravityConfig(central_body="earth", central_body_degree=8, third_body_perturbers=["sun", "moon"]),
        sim_settings=SimSettings(duration_days=3.0, dynamics_task_rate_s=1.0, integrator="rkf78"),
        spacecraft=[
            SpacecraftConfig(
                name="sat-1",
                orbit=OrbitIC(type="classical_elements", semi_major_axis_km=24396.0, eccentricity=0.7,
                               inclination_deg=28.5, raan_deg=0.0, arg_periapsis_deg=180.0, true_anomaly_deg=0.0),
                dry_mass_kg=1000.0,
            ),
        ],
    )


def build_03_geo_station_keeping() -> Scenario:
    return Scenario(
        name="03 - GEO station-keeping",
        description=(
            "A geostationary communications satellite that actively maintains its altitude against "
            "real perturbations (Sun/Moon third-body gravity and solar radiation pressure -- the "
            "actual drivers of GEO longitude/altitude drift in practice) using a simple deadband "
            "thrust controller: it fires station_keeping's thruster whenever the propagated altitude "
            "drifts more than deadband_km from target_altitude_km, burning propellant tracked in "
            "propellant_kg.\n\n"
            "What to look at: run the CLI ('missionstudio run ... --out-dir out') and check "
            "command_summary/results for the propellant used over the 14-day run (see this project's "
            "README, 'Running the CLI', for the station-keeping summary output) -- a real budget "
            "question a mission designer has to answer: how much propellant does a decade of GEO "
            "station-keeping cost?\n\n"
            "Try changing: deadband_km (tighter = more frequent, smaller burns), thrust_n/isp_s (a "
            "more efficient thruster uses less propellant per correction), or removing "
            "third_body_perturbers/enable_srp to see how much slower the drift becomes without them "
            "(and how rarely the controller then needs to fire)."
        ),
        epoch_utc="2030-01-01T00:00:00",
        simulation_mode="orbit_only",
        gravity=GravityConfig(central_body="earth", central_body_degree=0, third_body_perturbers=["sun", "moon"]),
        sim_settings=SimSettings(duration_days=14.0, dynamics_task_rate_s=30.0, integrator="rkf78"),
        spacecraft=[
            SpacecraftConfig(
                name="geo-sat-1",
                orbit=OrbitIC(type="classical_elements", semi_major_axis_km=42164.0, eccentricity=0.0,
                               inclination_deg=0.0, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0),
                dry_mass_kg=1200.0,
                enable_srp=True, srp_coeff=1.3, srp_area_m2=15.0,
                station_keeping=StationKeepingConfig(
                    target_altitude_km=35786.0, deadband_km=5.0, thrust_n=0.5, isp_s=1600.0,
                    propellant_kg=50.0,
                ),
            ),
        ],
    )


def build_04_walker_constellation() -> Scenario:
    template = SpacecraftConfig(
        name="placeholder",  # replaced per-satellite by generate_walker_constellation()
        orbit=OrbitIC(type="classical_elements", semi_major_axis_km=1.0, eccentricity=0.0,
                       inclination_deg=0.0, raan_deg=0.0, arg_periapsis_deg=0.0, mean_anomaly_deg=0.0,
                       anomaly_type="mean"),
        dry_mass_kg=180.0,
    )
    request = WalkerConstellationRequest(
        total_satellites=6, num_planes=2, phasing_factor=1, altitude_km=700.0, inclination_deg=53.0,
        pattern="delta", name_prefix="leo",
    )
    spacecraft = generate_walker_constellation(request, template)
    return Scenario(
        name="04 - Walker delta constellation",
        description=(
            "A small 6-satellite Walker delta constellation (2 orbital planes, 3 satellites per "
            "plane, phasing factor 1) at 700 km altitude / 53 deg inclination -- generated "
            "programmatically via engine.constellation.generate_walker_constellation() rather than "
            "hand-written, exactly how the GUI's 'Generate Walker constellation...' dialog "
            "(gui/constellation_dialog.py, off the spacecraft list's own button) and "
            "'missionstudio generate-constellation' CLI subcommand build one.\n\n"
            "What to look at: open this in the GUI and look at Vizard's ground track (or plot each "
            "satellite's 'position_N' series) -- the 2 planes are spread 180 deg apart in RAAN "
            "('delta' pattern; a 'star' pattern spreads them over 360 deg total instead), and "
            "satellites within a plane are evenly spaced by mean anomaly, offset between planes by "
            "the phasing factor. This is the standard way real LEO broadband/imaging constellations "
            "(the thing 'Starlink-shell-like' parameters like these are modeled after) achieve "
            "repeatable global coverage with a minimal satellite count.\n\n"
            "Try changing: total_satellites/num_planes (regenerate via the CLI/GUI, not by hand "
            "-editing this file's spacecraft list) to see how coverage geometry changes, or "
            "phasing_factor to change how planes interleave relative to each other."
        ),
        epoch_utc="2030-01-01T00:00:00",
        simulation_mode="orbit_only",
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        sim_settings=SimSettings(duration_days=1.0, dynamics_task_rate_s=30.0, integrator="rkf78"),
        spacecraft=spacecraft,
    )


def build_05_formation_flying_phasing() -> Scenario:
    return Scenario(
        name="05 - Formation flying (phasing control)",
        description=(
            "Two spacecraft in near-identical orbits, 'follower-1' actively holding a fixed in-track "
            "separation behind chief 'chief-1' using phasing_keeping -- a closed-loop controller that "
            "measures the along-track separation and fires small along-track burns to correct drift, "
            "on top of its OWN station_keeping (phasing_keeping always needs station_keeping "
            "configured on the same spacecraft -- see PhasingKeepingConfig's own docstring for why: "
            "phasing needs altitude held steady first, or a semi-major-axis mismatch would make "
            "along-track drift and true phasing error indistinguishable).\n\n"
            "What to look at: after running, compare 'follower-1.position_N' and 'chief-1.position_N' "
            "-- the along-track (velocity-direction) separation should stay near "
            "target_separation_km despite neither orbit being perfectly matched to start, a basic "
            "model of formation-flying/rendezvous-proximity-operations control (e.g. trailing "
            "satellite formations, or a servicer holding station behind a target). "
            "'missionstudio run' also prints a phasing delta-V breakdown in its station-keeping "
            "summary (see README, 'Running the CLI').\n\n"
            "Try changing: target_separation_km (a schedule -- see PhasingKeepingConfig; a single "
            "-element list holds one separation for the whole run, more elements step through a "
            "schedule), or chief-1's own orbit to start with a larger initial mismatch and watch "
            "follower-1 correct it."
        ),
        epoch_utc="2030-01-01T00:00:00",
        simulation_mode="orbit_only",
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        sim_settings=SimSettings(duration_days=7.0, dynamics_task_rate_s=30.0, integrator="rkf78"),
        spacecraft=[
            SpacecraftConfig(
                name="chief-1",
                orbit=OrbitIC(type="classical_elements", semi_major_axis_km=6928.0, eccentricity=0.0,
                               inclination_deg=45.0, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0),
                dry_mass_kg=400.0,
            ),
            SpacecraftConfig(
                name="follower-1",
                orbit=OrbitIC(type="classical_elements", semi_major_axis_km=6928.0, eccentricity=0.0,
                               inclination_deg=45.0, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=-0.5),
                dry_mass_kg=400.0,
                station_keeping=StationKeepingConfig(
                    target_altitude_km=550.0, deadband_km=2.0, thrust_n=0.05, isp_s=1500.0, propellant_kg=5.0,
                ),
                phasing_keeping=PhasingKeepingConfig(
                    chief_spacecraft="chief-1", target_separation_km=[50.0],
                ),
            ),
        ],
    )


def build_06_attitude_pointing_basic() -> Scenario:
    return Scenario(
        name="06 - Basic attitude pointing (idealized actuation)",
        description=(
            "A spacecraft pointing its body frame to track the local vertical/local horizontal frame "
            "(fsw_mode 'hillPoint' -- nadir-pointing, the natural first attitude-control example: see "
            "engine/fsw.py's own docstring, copied from examples/scenarioAttitudeGuidance.py) with NO "
            "sensors or actuators configured -- with no 'reaction_wheel' actuators present, the "
            "control torque is applied directly to the hub via an idealized ExtForceTorque effector "
            "(see engine/fsw.py's build_idealized_actuation()), skipping real hardware modeling "
            "entirely so this example is only about the pointing CONCEPT. See '07' for the same idea "
            "with real ADCS hardware in the loop.\n\n"
            "The spacecraft starts tipped away from the target attitude (sigma_bn_init is non-zero) "
            "with a small initial body rate -- watch the attitude error converge to zero as the "
            "controller (mrpFeedback, closing the loop on simpleNav's truth attitude) drives it to "
            "track hillPoint's commanded frame.\n\n"
            "What to look at: this scenario's own attitude state isn't in the CSV export series by "
            "default; add a 'report' mission_sequence command (see '08') or inspect "
            "sat-1.omega_BN_B/attitude state directly via the schema/engine layer if you extend this "
            "-- or simplest, watch it converge visually in Vizard's live attitude indicator.\n\n"
            "Try changing: fsw_mode to 'velocityPoint' (tracks the velocity vector instead of nadir) "
            "or 'inertial3D' (points at a fixed inertial attitude, ignoring the orbit entirely) to "
            "compare pointing behaviors."
        ),
        epoch_utc="2030-01-01T00:00:00",
        simulation_mode="full_attitude",
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        sim_settings=SimSettings(duration_days=0.05, dynamics_task_rate_s=1.0, integrator="rkf78"),
        spacecraft=[
            SpacecraftConfig(
                name="sat-1",
                orbit=OrbitIC(type="classical_elements", semi_major_axis_km=6928.0, eccentricity=0.0,
                               inclination_deg=45.0, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0),
                dry_mass_kg=300.0,
                inertia_kg_m2=list(_INERTIA_MEDIUM),
                sigma_bn_init=[0.1, 0.2, -0.15],
                omega_bn_b_init_rad_s=[0.001, -0.001, 0.0005],
                fsw_mode="hillPoint",
            ),
        ],
    )


def build_07_attitude_pointing_with_adcs_hardware() -> Scenario:
    return Scenario(
        name="07 - Attitude pointing with real ADCS hardware",
        description=(
            "The realistic counterpart to '06': the same pointing problem, but with an actual ADCS "
            "hardware suite modeled -- a star tracker and IMU for attitude/rate sensing, a coarse sun "
            "sensor, and three reaction wheels (orthogonal spin axes) providing the real control "
            "torque instead of an idealized effector, plus a solar array + battery power budget "
            "(power draw from the sensors/wheels isn't modeled per-component here, but this shows how "
            "a full spacecraft config -- attitude AND power -- fits together). fsw_mode 'sunSafePoint' "
            "is a safe-mode-style controller that points a body axis at the Sun using simpleNav's own "
            "Sun-direction output (see engine/fsw.py's docstring for why no separate sensor message "
            "is strictly required even though a coarse_sun_sensor is configured here for realism).\n\n"
            "What to look at: this is the shape a real small-sat's SpacecraftConfig looks like in "
            "practice -- compare it side-by-side with '06' to see exactly what real hardware adds "
            "(sensors/actuators/power blocks) on top of the bare pointing-mode concept.\n\n"
            "Try changing: the reaction wheels' Js/u_max/maxMomentum (see the GUI's sensor/actuator "
            "editor for the full per-kind parameter list and units), or swap fsw_mode to "
            "'locationPointing' with fsw_params={'target_ground_station': '<name>'} once a "
            "ground_stations entry exists in this scenario."
        ),
        epoch_utc="2030-01-01T00:00:00",
        simulation_mode="full_attitude",
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        sim_settings=SimSettings(duration_days=0.05, dynamics_task_rate_s=1.0, integrator="rkf78"),
        spacecraft=[
            SpacecraftConfig(
                name="sat-1",
                orbit=OrbitIC(type="classical_elements", semi_major_axis_km=6928.0, eccentricity=0.0,
                               inclination_deg=45.0, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0),
                dry_mass_kg=50.0,
                inertia_kg_m2=list(_INERTIA_SMALL),
                sigma_bn_init=[0.1, 0.2, -0.15],
                omega_bn_b_init_rad_s=[0.001, -0.001, 0.0005],
                sensors=[
                    SensorConfig(kind="star_tracker", name="st-1", params={"noise_arcsec": 5.0}),
                    SensorConfig(kind="imu", name="imu-1", params={"gyro_noise_rad_s": 1e-5}),
                    SensorConfig(kind="coarse_sun_sensor", name="css-1", params={"nHat_B": [1.0, 0.0, 0.0]}),
                ],
                actuators=[
                    ActuatorConfig(kind="reaction_wheel", name="rw-1", params={"gsHat_B": [1.0, 0.0, 0.0]}),
                    ActuatorConfig(kind="reaction_wheel", name="rw-2", params={"gsHat_B": [0.0, 1.0, 0.0]}),
                    ActuatorConfig(kind="reaction_wheel", name="rw-3", params={"gsHat_B": [0.0, 0.0, 1.0]}),
                ],
                fsw_mode="sunSafePoint",
                power=PowerConfig(panel_area_m2=0.3, panel_efficiency=0.28, battery_capacity_wh=80.0),
            ),
        ],
    )


def build_08_mission_sequence_orbit_raise() -> Scenario:
    from missionstudio.schema.command import Command

    return Scenario(
        name="08 - Mission sequence: impulsive orbit raise",
        description=(
            "Introduces the Mission Sequence layer (Resources/Mission Sequence/Output -- see this "
            "project's README, 'What Phase 6 (Mission Sequence architecture) adds'): rather than one "
            "single propagate-to-duration run, this scenario is a time-ordered list of commands, "
            "editable as a tree in the GUI's 'Mission sequence' panel: coast, snapshot the orbit "
            "state, apply a single prograde impulsive delta-V, coast again, snapshot again. The "
            "maneuver command applies delta_v_m_s in the 'vnb' frame (velocity/normal/binormal -- "
            "'inertial' applies it directly in the N frame instead, useful when you already know the "
            "exact inertial-frame vector you want), so [50, 0, 0] here means '+50 m/s prograde', the "
            "simplest kind of orbit-raising burn.\n\n"
            "What to look at: run it and check the 'Mission Output' tab (or, from the CLI, "
            "command_summary.csv) -- the two 'report' commands snapshot sat-1.position_N/velocity_N "
            "before and after the burn. A prograde burn on a circular orbit raises the OPPOSITE side "
            "of the orbit into an ellipse -- the orbit is no longer circular after the burn, with a "
            "higher apoapsis where the spacecraft now moves slower and a periapsis back at the "
            "original altitude.\n\n"
            "Try changing: delta_v_m_s's magnitude (bigger burn = bigger apoapsis raise) or sign "
            "(negative = retrograde, LOWERS the opposite side of the orbit instead), or add a second "
            "maneuver command half an orbit later to circularize at the new higher altitude -- a "
            "genuine two-burn Hohmann transfer, built entirely from this project's own mission "
            "-sequence commands."
        ),
        epoch_utc="2030-01-01T00:00:00",
        simulation_mode="orbit_only",
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        sim_settings=SimSettings(duration_days=1.0, dynamics_task_rate_s=10.0, integrator="rkf78"),
        spacecraft=[
            SpacecraftConfig(
                name="sat-1",
                orbit=OrbitIC(type="classical_elements", semi_major_axis_km=6778.0, eccentricity=0.0,
                               inclination_deg=28.5, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0),
                dry_mass_kg=500.0,
            ),
        ],
        mission_sequence=[
            Command(kind="propagate", label="Coast before burn",
                    params={"stop_condition": "duration", "duration_days": 0.1}),
            Command(kind="report", label="Before burn", params={"series": []}),
            Command(kind="maneuver", label="Prograde raise burn",
                    params={"spacecraft": "sat-1", "delta_v_m_s": [50.0, 0.0, 0.0], "frame": "vnb"}),
            Command(kind="propagate", label="Coast after burn",
                    params={"stop_condition": "duration", "duration_days": 0.5}),
            Command(kind="report", label="After burn", params={"series": []}),
        ],
    )


def build_09_monte_carlo_dispersion_analysis() -> Scenario:
    return Scenario(
        name="09 - Monte Carlo dispersion analysis",
        description=(
            "The same circular LEO orbit as '01', but run as a Monte Carlo batch of 20 cases instead "
            "of a single deterministic run: each case's dry_mass_kg is independently redrawn from a "
            "normal distribution (mean 500 kg, std deviation 25 kg -- a stand-in for, e.g., propellant "
            "-loading or manufacturing-tolerance uncertainty). This is the basic pattern behind real "
            "uncertainty-quantification questions: 'given that I don't know this spacecraft's exact "
            "mass to the kilogram, how much does that affect the outcome I care about?'\n\n"
            "What to look at: run via the GUI's 'Run Monte Carlo...' action (or "
            "'missionstudio monte-carlo') and pick an archive directory -- each of the 20 runs is "
            "archived separately, so you can compare e.g. final position across cases to see how much "
            "(or how little) an 5% mass uncertainty actually perturbs the resulting orbit over a "
            "1-day propagation (physically: not much, for pure two-body motion -- mass doesn't affect "
            "trajectory at all, only propellant-consuming maneuvers/drag/SRP would show sensitivity; "
            "try enabling one of those, or add an 'attitude_sigma_bn' dispersion, to see a case where "
            "it does matter).\n\n"
            "Try changing: num_runs (more runs = a smoother distribution of outcomes, at proportional "
            "runtime cost), std_deviation (a wider spread), or add a second DispersionConfig with "
            "quantity='attitude_sigma_bn'/kind='uniform_euler_mrp' for an initial-attitude dispersion "
            "instead (needs simulation_mode='full_attitude')."
        ),
        epoch_utc="2030-01-01T00:00:00",
        simulation_mode="orbit_only",
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        sim_settings=SimSettings(duration_days=1.0, dynamics_task_rate_s=30.0, integrator="rkf78"),
        spacecraft=[
            SpacecraftConfig(
                name="sat-1",
                orbit=OrbitIC(type="classical_elements", semi_major_axis_km=6778.0, eccentricity=0.0,
                               inclination_deg=51.6, raan_deg=0.0, arg_periapsis_deg=0.0, true_anomaly_deg=0.0),
                dry_mass_kg=500.0,
            ),
        ],
        monte_carlo=MonteCarloConfig(
            enabled=True, num_runs=20, thread_count=1,
            dispersions=[
                DispersionConfig(spacecraft="sat-1", quantity="dry_mass_kg", kind="normal",
                                   mean=500.0, std_deviation=25.0),
            ],
        ),
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _save(build_01_two_body_circular_orbit(), "01_two_body_circular_orbit.json")
    _save(build_02_elliptical_orbit_with_perturbations(), "02_elliptical_orbit_with_perturbations.json")
    _save(build_03_geo_station_keeping(), "03_geo_station_keeping.json")
    _save(build_04_walker_constellation(), "04_walker_constellation.json")
    _save(build_05_formation_flying_phasing(), "05_formation_flying_phasing.json")
    _save(build_06_attitude_pointing_basic(), "06_attitude_pointing_basic.json")
    _save(build_07_attitude_pointing_with_adcs_hardware(), "07_attitude_pointing_with_adcs_hardware.json")
    _save(build_08_mission_sequence_orbit_raise(), "08_mission_sequence_orbit_raise.json")
    _save(build_09_monte_carlo_dispersion_analysis(), "09_monte_carlo_dispersion_analysis.json")


if __name__ == "__main__":
    main()
