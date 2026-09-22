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

r"""
Interactive setup wizard for the constellation mission -- an alternative to
hand-editing ``mission_config.py`` or using ``configure_mission.py``'s CLI
flags. Prompts (Enter accepts the default shown in ``[brackets]``) for:

* Epoch and mission duration
* Spacecraft bus (mass, Cd, Cr, drag/SRP areas) and electric propulsion
  (a free-text system/thruster description, thrust, Isp, propellant mass,
  and the sunlit shadow-factor threshold that gates both thrust-enable and
  the EO instrument's duty cycle)
* The SSO constellation plane: altitude, inclination, eccentricity, AOP,
  local time of descending node, and satellite COUNT (each gets independent
  altitude station-keeping, and for count > 1, in-plane phasing against a
  chief satellite); each follower additionally gets its own separation
  schedule -- a list of target distances from the chief [km] stepped every
  few months, so followers can sit at different, time-varying separations
* Any number of additional standalone satellites, each with its own orbit
* Any number of ground stations (with a couple of real-world presets, or
  fully custom lat/lon/altitude/elevation-mask)
* Power budget (solar panel area/efficiency, bus/instrument/downlink power
  draws, battery capacity and initial state of charge)
* RF / downlink link budget (data rate, TX power, antenna gains, system
  noise temperature, implementation loss, required Eb/N0 -- see
  mission_config.py's RF section for what feeds the simulation vs. the
  reported link-margin estimate only)
* Attitude control (antenna-boresight and solar-panel-normal body-fixed
  vectors, and the pointing controller's gains/torque clamp)
* Station-keeping deadband, phasing tolerance (as a fraction of the current
  target separation), Earth gravity fidelity

Run it with no arguments::

    python3 setup_wizard.py

It writes ``constellation_setup.json`` (the satellite/ground-station
structure -- see ``mission_config.py``'s module docstring) and applies the
scalar settings through ``configure_mission.py`` (reusing its validation,
file-patching, import-check, and space-weather regeneration -- see that
script if you want to change just one of those values later without
rerunning the whole wizard). At the end it offers to run a quick smoke test.
"""

import sys
import json
import subprocess
from pathlib import Path

import configure_mission
import mission_config as mc

SCRIPT_DIR = Path(__file__).resolve().parent
CONSTELLATION_SETUP_PATH = SCRIPT_DIR / "constellation_setup.json"
# True only when constellation_setup.json already exists, i.e. this is a
# re-run to tweak a previous wizard session's actual answers -- as opposed
# to a first run, where mc.SSO_PLANE/CUSTOM_SATELLITES/GROUND_STATIONS are
# just this module's built-in fallback defaults, not anyone's real answers,
# and showing them as if they were (e.g. "custom" instead of the nicer
# preset-number shortcuts) would be worse UX, not better.
IS_REEDIT = CONSTELLATION_SETUP_PATH.exists()

PRESET_GROUND_STATIONS = {
    "1": dict(name="Svalbard", lat_deg=78.2300, lon_deg=15.3894, alt_m=0.0, min_elevation_deg=5.0),
    "2": dict(name="Boulder", lat_deg=40.009971, lon_deg=-105.243895, alt_m=1624.0, min_elevation_deg=10.0),
}


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------
def section(title: str) -> None:
    print(f"\n=== {title} ===")


def ask(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else str(default)


def ask_float(prompt: str, default: float, validator=None) -> float:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        raw = raw if raw else str(default)
        try:
            value = float(raw)
        except ValueError:
            print("  please enter a number")
            continue
        if validator is not None:
            ok = validator(value)
            if ok is not True:
                print(f"  {ok}")
                continue
        return value


def ask_int(prompt: str, default: int, validator=None) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        raw = raw if raw else str(default)
        try:
            value = int(raw)
        except ValueError:
            print("  please enter a whole number")
            continue
        if validator is not None:
            ok = validator(value)
            if ok is not True:
                print(f"  {ok}")
                continue
        return value


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  please answer y or n")


def ask_vec3(prompt: str, default: list) -> str:
    """Returns the raw comma-separated STRING (not a parsed list) -- this
    is passed straight through to configure_mission.py's --antenna
    -boresight-b/--panel-normal-b flags, which do the actual parsing and
    (nonzero-magnitude) validation.
    """
    default_str = ",".join(str(c) for c in default)
    while True:
        raw = input(f"{prompt} [{default_str}]: ").strip()
        raw = raw if raw else default_str
        parts = raw.split(",")
        if len(parts) != 3:
            print("  please enter exactly 3 comma-separated numbers, e.g. 0,0,-1")
            continue
        try:
            [float(p) for p in parts]
        except ValueError:
            print("  please enter exactly 3 comma-separated numbers, e.g. 0,0,-1")
            continue
        return raw


def ask_float_list(prompt: str, default: list, validator=None) -> list:
    default_str = ",".join(str(v) for v in default)
    while True:
        raw = input(f"{prompt} [{default_str}]: ").strip()
        raw = raw if raw else default_str
        try:
            values = [float(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            print("  please enter comma-separated numbers, e.g. 1000,500,250,100,50")
            continue
        if not values:
            print("  need at least one value")
            continue
        if validator is not None:
            ok = validator(values)
            if ok is not True:
                print(f"  {ok}")
                continue
        return values


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def ask_epoch_and_duration():
    section("Epoch and mission duration")
    epoch = ask(
        "Mission epoch, UTC (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)",
        mc.EPOCH_UTC.date().isoformat(),
    )
    mission_years = ask_float(
        "Mission duration [years]", mc.MISSION_DURATION_YEARS, lambda v: v > 0 or "must be > 0"
    )
    return epoch, mission_years


def ask_bus_and_propulsion():
    section("Spacecraft bus")
    dry_mass = ask_float("Dry mass [kg]", mc.DRY_MASS_KG, lambda v: v > 0 or "must be > 0")
    drag_coeff = ask_float("Drag coefficient Cd [-]", mc.DRAG_COEFF, lambda v: v > 0 or "must be > 0")
    srp_coeff = ask_float("SRP reflectivity coefficient Cr [-]", mc.SRP_COEFF, lambda v: v > 0 or "must be > 0")
    drag_area = ask_float("Drag cross-sectional area [m^2]", mc.DRAG_AREA_M2, lambda v: v > 0 or "must be > 0")
    srp_area = ask_float("SRP cross-sectional area [m^2]", mc.SRP_AREA_M2, lambda v: v > 0 or "must be > 0")

    section("Electric propulsion")
    propulsion_type = ask(
        "Thruster/propulsion system description (for your own records -- doesn't affect the simulation)",
        mc.PROPULSION_TYPE,
    )
    thrust_mn = ask_float("Thrust [mN]", mc.THRUST_N * 1000.0, lambda v: v > 0 or "must be > 0")
    isp_s = ask_float("Specific impulse Isp [s]", mc.ISP_S, lambda v: v > 0 or "must be > 0")
    propellant = ask_float(
        "Propellant mass, beginning-of-life [kg]", mc.PROPELLANT_MASS_BOL_KG, lambda v: v >= 0 or "must be >= 0"
    )
    eclipse_sunlit_threshold = ask_float(
        "Sunlit shadow-factor threshold [-, 0-1] (gates both thrust-enable and the EO "
        "instrument's duty cycle -- higher means less of a partial-shadow margin before "
        "treating the spacecraft as eclipsed)",
        mc.ECLIPSE_SUNLIT_THRESHOLD, lambda v: 0.0 < v <= 1.0 or "must be in (0, 1]",
    )

    return dict(
        dry_mass=dry_mass, drag_coeff=drag_coeff, srp_coeff=srp_coeff, drag_area=drag_area,
        srp_area=srp_area, propulsion_type=propulsion_type, thrust_mn=thrust_mn, isp_s=isp_s,
        propellant=propellant, eclipse_sunlit_threshold=eclipse_sunlit_threshold,
    )


def ask_follower_schedules(count: int, current: dict) -> list:
    # One schedule per follower (the plane's 2nd..count-th satellite); the
    # first satellite (the chief) is left unmaneuvered for phasing and has
    # no schedule of its own. Each follower's along-track separation from
    # the chief steps through its own list of distances every
    # interval_days, holding at the last one once the list is exhausted --
    # this is how "maneuvers every few months, changing relative distance,
    # order of 1000km to 50km, different [per-follower] relative distances"
    # is modeled (see SeparationSchedule in constellation_controllers.py).
    section("SSO follower separation schedules")
    print("Each follower steps through its own list of target separations from the chief,")
    print("holding `interval_days` at each before stepping to the next (holds at the last")
    print("one for good after the list ends). Separations are along-track, in km.")
    existing = current.get("follower_schedules", []) if IS_REEDIT else []
    fallback_defaults = mc._DEFAULT_FOLLOWER_SCHEDULES
    schedules = []
    for i in range(count - 1):
        print(f"\n-- Follower SSO-{i + 2} (relative to chief SSO-1) --")
        prior = existing[i] if i < len(existing) else None
        fallback = fallback_defaults[i] if i < len(fallback_defaults) else fallback_defaults[-1]
        default_distances = prior["distances_km"] if prior else fallback["distances_km"]
        default_interval = prior["interval_days"] if prior else fallback["interval_days"]
        distances_km = ask_float_list(
            "  Target separation distances, in order [km]", default_distances,
            lambda vs: all(v > 0 for v in vs) or "all distances must be > 0",
        )
        interval_days = ask_float(
            "  Days to hold each distance before stepping to the next", default_interval,
            lambda v: v > 0 or "must be > 0",
        )
        schedules.append(dict(distances_km=distances_km, interval_days=interval_days))
    return schedules


def ask_sso_plane():
    # Defaults come from mc.SSO_PLANE, which already reflects an existing
    # constellation_setup.json if this wizard was run before -- re-running
    # it to tweak one value shows your last answers, not the hardcoded
    # mission defaults.
    # mc.SSO_PLANE already equals these same scalars' defaults when no JSON
    # exists yet, so this is correct either way -- re-editing or not.
    current = mc.SSO_PLANE
    section("Sun-synchronous (SSO) constellation plane")
    print("Satellites in this plane share one orbit (same altitude/inclination/eccentricity/AOP).")
    print("The first satellite is the unmaneuvered phasing chief; each other satellite (follower)")
    print("gets independent altitude station-keeping plus its own in-plane separation schedule,")
    print("so followers can be spaced at different, time-varying distances from the chief.")
    count = ask_int("Number of satellites in this plane (0 for none)", current["count"],
                     lambda v: v >= 0 or "must be >= 0")
    if count == 0:
        return dict(count=0, altitude_km=current["altitude_km"], inclination_deg=current["inclination_deg"],
                    ecc=current["ecc"], aop_deg=current["aop_deg"], ltdn_hours=current["ltdn_hours"],
                    follower_schedules=[])
    altitude_km = ask_float("Altitude [km]", current["altitude_km"], lambda v: v > 100 or "must be > 100 km")
    inclination_deg = ask_float("Inclination [deg]", current["inclination_deg"],
                                 lambda v: 0 <= v <= 180 or "must be in [0, 180]")
    ecc = ask_float("Eccentricity [-]", current["ecc"], lambda v: 0 <= v < 1 or "must be in [0, 1)")
    aop_deg = ask_float("Argument of perigee [deg] (90 or 270 gives a frozen orbit)", current["aop_deg"],
                         lambda v: 0 <= v < 360 or "must be in [0, 360)")
    ltdn_hours = ask_float("Local time of descending node [hr, 0-24]", current["ltdn_hours"],
                            lambda v: 0 <= v < 24 or "must be in [0, 24)")
    follower_schedules = ask_follower_schedules(count, current) if count > 1 else []
    return dict(count=count, altitude_km=altitude_km, inclination_deg=inclination_deg, ecc=ecc,
                aop_deg=aop_deg, ltdn_hours=ltdn_hours, follower_schedules=follower_schedules)


def ask_custom_satellites(sso_count: int):
    # Defaults for satellite i come from mc.CUSTOM_SATELLITES[i] when it
    # exists (same re-editing rationale as ask_sso_plane() above), else
    # from generic fallbacks.
    existing = mc.CUSTOM_SATELLITES
    section("Additional standalone satellites")
    print("Each of these has its own orbit and independent altitude station-keeping,")
    print("but no phasing partner.")
    default_count = len(existing) if existing else (0 if sso_count > 0 else 1)
    count = ask_int("Number of standalone satellites", default_count, lambda v: v >= 0 or "must be >= 0")
    satellites = []
    for i in range(count):
        print(f"\n-- Standalone satellite {i + 1} of {count} --")
        prior = existing[i] if i < len(existing) else None
        default_name = prior["name"] if prior else ("MIDINC-1" if (i == 0 and count == 1) else f"CUSTOM-{i + 1}")
        name = ask("  Name", default_name)
        altitude_km = ask_float("  Altitude [km]", prior["altitude_km"] if prior else mc.ALT_NOMINAL_M / 1000.0,
                                 lambda v: v > 100 or "must be > 100 km")
        inclination_deg = ask_float("  Inclination [deg]",
                                     prior["inclination_deg"] if prior else mc.MIDINC_INCLINATION_DEG,
                                     lambda v: 0 <= v <= 180 or "must be in [0, 180]")
        ecc = ask_float("  Eccentricity [-]", prior["ecc"] if prior else 0.0,
                         lambda v: 0 <= v < 1 or "must be in [0, 1)")
        aop_deg = ask_float("  Argument of perigee [deg]", prior["aop_deg"] if prior else 0.0,
                             lambda v: 0 <= v < 360 or "must be in [0, 360)")
        raan_deg = ask_float("  RAAN [deg]", prior["raan_deg"] if prior else 0.0,
                              lambda v: 0 <= v < 360 or "must be in [0, 360)")
        mean_anom_deg = ask_float("  Initial mean anomaly [deg]", prior["mean_anom_deg"] if prior else 0.0,
                                   lambda v: 0 <= v < 360 or "must be in [0, 360)")
        satellites.append(dict(name=name, altitude_km=altitude_km, inclination_deg=inclination_deg, ecc=ecc,
                                aop_deg=aop_deg, raan_deg=raan_deg, mean_anom_deg=mean_anom_deg))
    return satellites


def ask_ground_stations():
    # On a re-edit (constellation_setup.json already exists), defaults for
    # station i come from mc.GROUND_STATIONS[i]. On a first run, that list
    # is just this module's own fallback defaults (Svalbard, Boulder), not
    # anyone's real answer -- offer the nicer "1"/"2" preset shortcuts
    # instead of pre-filling "custom" with those same values.
    existing = mc.GROUND_STATIONS if IS_REEDIT else []
    section("Ground stations")
    print("Presets: 1) Svalbard (78.23N -- high-latitude, near-every-orbit SSO access)")
    print("         2) Boulder, CO (40.01N -- mid-latitude)")
    print("Enter a preset number, or 'custom' for your own location.")
    count = ask_int("Number of ground stations", len(mc.GROUND_STATIONS), lambda v: v >= 0 or "must be >= 0")
    stations = []
    for i in range(count):
        print(f"\n-- Ground station {i + 1} of {count} --")
        prior = existing[i] if i < len(existing) else None
        default_choice = "1" if (not prior and i == 0) else ("2" if (not prior and i == 1) else "custom")
        choice = ask("  Preset (1, 2) or 'custom'", default_choice)
        if choice in PRESET_GROUND_STATIONS:
            gs = dict(PRESET_GROUND_STATIONS[choice])
            print(f"  Using preset: {gs['name']} ({gs['lat_deg']} deg, {gs['lon_deg']} deg)")
        else:
            name = ask("  Name", prior["name"] if prior else f"Ground Station {i + 1}")
            lat_deg = ask_float("  Latitude [deg, -90 to 90]", prior["lat_deg"] if prior else 0.0,
                                 lambda v: -90 <= v <= 90 or "must be in [-90, 90]")
            lon_deg = ask_float("  Longitude [deg, -180 to 180]", prior["lon_deg"] if prior else 0.0,
                                 lambda v: -180 <= v <= 180 or "must be in [-180, 180]")
            alt_m = ask_float("  Altitude above sea level [m]", prior["alt_m"] if prior else 0.0)
            min_elevation_deg = ask_float("  Minimum elevation mask [deg]",
                                           prior["min_elevation_deg"] if prior else 10.0,
                                           lambda v: 0 <= v < 90 or "must be in [0, 90)")
            gs = dict(name=name, lat_deg=lat_deg, lon_deg=lon_deg, alt_m=alt_m,
                      min_elevation_deg=min_elevation_deg)
        stations.append(gs)
    return stations


def ask_power_and_rf():
    section("Power budget")
    panel_area_m2 = ask_float("Solar panel area [m^2]", mc.SOLAR_PANEL_AREA_M2, lambda v: v > 0 or "must be > 0")
    panel_efficiency = ask_float("Solar cell efficiency [-, 0-1]", mc.SOLAR_PANEL_EFFICIENCY,
                                  lambda v: 0.0 < v <= 1.0 or "must be in (0, 1]")
    bus_idle_power_w = ask_float("Always-on bus power draw (avionics/thermal/ADCS) [W]", mc.BUS_IDLE_POWER_W,
                                  lambda v: v >= 0 or "must be >= 0")
    instrument_power_w = ask_float("EO instrument power draw while imaging [W]", mc.EO_INSTRUMENT_POWER_W,
                                    lambda v: v >= 0 or "must be >= 0")
    battery_capacity_wh = ask_float("Battery capacity [W*hr]", mc.BATTERY_CAPACITY_WH,
                                     lambda v: v > 0 or "must be > 0")
    battery_initial_soc = ask_float("Initial battery state of charge [-, 0-1]", mc.BATTERY_INITIAL_SOC,
                                     lambda v: 0.0 <= v <= 1.0 or "must be in [0, 1]")

    section("RF / downlink link budget")
    print("Downlink rate and TX power feed the simulation (data throughput, power-budget load).")
    print("Everything else here feeds a reported link-margin ESTIMATE only (simplified free-space")
    print("path loss -- no atmosphere/rain/pointing-loss/coding-gain terms) -- it does NOT change")
    print("the simulated downlink data rate/gating. See mission_config.py's RF section.")
    downlink_rate_mbps = ask_float("Downlink data rate [Mbit/s]", mc.DOWNLINK_BAUD_RATE_BPS / 1.0e6,
                                    lambda v: v > 0 or "must be > 0")
    downlink_tx_power_w = ask_float("Downlink transmitter RF output power [W]", mc.DOWNLINK_TX_POWER_W,
                                     lambda v: v > 0 or "must be > 0")
    rf_frequency_ghz = ask_float("Downlink carrier frequency [GHz]", mc.RF_FREQUENCY_HZ / 1.0e9,
                                  lambda v: v > 0 or "must be > 0")
    rf_tx_antenna_gain_dbi = ask_float("Spacecraft downlink antenna gain [dBi]", mc.RF_TX_ANTENNA_GAIN_DBI)
    rf_ground_antenna_gain_dbi = ask_float("Ground station antenna gain [dBi]", mc.RF_GROUND_ANTENNA_GAIN_DBI)
    rf_system_noise_temp_k = ask_float("Ground receiver system noise temperature [K]",
                                        mc.RF_SYSTEM_NOISE_TEMP_K, lambda v: v > 0 or "must be > 0")
    rf_implementation_loss_db = ask_float("Implementation/pointing/polarization loss [dB]",
                                           mc.RF_IMPLEMENTATION_LOSS_DB, lambda v: v >= 0 or "must be >= 0")
    rf_required_ebno_db = ask_float("Required Eb/N0 for the assumed modulation/coding [dB]",
                                     mc.RF_REQUIRED_EBNO_DB)

    return dict(
        panel_area_m2=panel_area_m2, panel_efficiency=panel_efficiency,
        bus_idle_power_w=bus_idle_power_w, instrument_power_w=instrument_power_w,
        battery_capacity_wh=battery_capacity_wh, battery_initial_soc=battery_initial_soc,
        downlink_rate_mbps=downlink_rate_mbps, downlink_tx_power_w=downlink_tx_power_w,
        rf_frequency_ghz=rf_frequency_ghz, rf_tx_antenna_gain_dbi=rf_tx_antenna_gain_dbi,
        rf_ground_antenna_gain_dbi=rf_ground_antenna_gain_dbi, rf_system_noise_temp_k=rf_system_noise_temp_k,
        rf_implementation_loss_db=rf_implementation_loss_db, rf_required_ebno_db=rf_required_ebno_db,
    )


def ask_attitude():
    section("Attitude control")
    print("Points the antenna boresight at the best in-range ground station whenever one is in")
    print("contact, else points the solar panel normal at the sun -- both body-fixed vectors (no")
    print("gimbal is modeled, so only one target can be satisfied at a time; see README.md).")
    antenna_boresight_b = ask_vec3("Antenna boresight body vector", mc.ANTENNA_BORESIGHT_B)
    panel_normal_b = ask_vec3("Solar panel normal body vector", mc.PANEL_NORMAL_B)
    attitude_k = ask_float("Attitude control proportional gain K [N*m]", mc.ATTITUDE_CONTROL_K,
                            lambda v: v > 0 or "must be > 0")
    attitude_p = ask_float("Attitude control rate-damping gain P [N*m*s]", mc.ATTITUDE_CONTROL_P,
                            lambda v: v > 0 or "must be > 0")
    attitude_max_torque_nm = ask_float("Per-axis commanded-torque clamp [N*m]", mc.ATTITUDE_CONTROL_MAX_TORQUE_NM,
                                        lambda v: v > 0 or "must be > 0")
    return dict(
        antenna_boresight_b=antenna_boresight_b, panel_normal_b=panel_normal_b,
        attitude_k=attitude_k, attitude_p=attitude_p, attitude_max_torque_nm=attitude_max_torque_nm,
    )


def ask_advanced():
    section("Station-keeping and mission fidelity")
    alt_deadband_km = ask_float("Altitude station-keeping deadband [km]", mc.ALT_DEADBAND_M / 1000.0,
                                 lambda v: v > 0 or "must be > 0")
    phasing_tolerance_fraction = ask_float(
        "Phasing trigger tolerance, as a fraction of the current target separation [-, e.g. 0.10 = 10%]",
        mc.PHASING_TOLERANCE_FRACTION, lambda v: 0.0 < v <= 1.0 or "must be in (0, 1]",
    )
    grav_degree = ask_int("Earth gravity spherical-harmonics degree/order", mc.EARTH_GRAV_DEGREE,
                           lambda v: 0 <= v <= 360 or "must be a plausible degree")
    return alt_deadband_km, phasing_tolerance_fraction, grav_degree


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print(__doc__)
    print("Answer the prompts below; press Enter to accept the default shown in [brackets].")

    epoch, mission_years = ask_epoch_and_duration()
    bus = ask_bus_and_propulsion()
    sso_plane = ask_sso_plane()
    custom_satellites = ask_custom_satellites(sso_plane["count"])

    if sso_plane["count"] == 0 and not custom_satellites:
        print("\nerror: the constellation has zero satellites (SSO plane count is 0 and no "
              "standalone satellites were added). Run this wizard again and add at least one.",
              file=sys.stderr)
        return 1

    ground_stations = ask_ground_stations()
    power_rf = ask_power_and_rf()
    attitude = ask_attitude()
    alt_deadband_km, phasing_tolerance_fraction, grav_degree = ask_advanced()

    # --- Write the structural config ---
    setup = dict(sso_plane=sso_plane, custom_satellites=custom_satellites, ground_stations=ground_stations)
    CONSTELLATION_SETUP_PATH.write_text(json.dumps(setup, indent=2) + "\n")
    nSat = sso_plane["count"] + len(custom_satellites)
    print(f"\nWrote {CONSTELLATION_SETUP_PATH.name} "
          f"({nSat} satellite{'s' if nSat != 1 else ''}, {len(ground_stations)} ground station"
          f"{'s' if len(ground_stations) != 1 else ''}).")

    # --- Apply the scalar settings via configure_mission.py (reuses its
    # validation, file-patching, import-check, and space-weather regen) ---
    argv = [
        "--epoch", epoch,
        "--mission-years", str(mission_years),
        "--dry-mass-kg", str(bus["dry_mass"]),
        "--drag-coeff", str(bus["drag_coeff"]),
        "--srp-coeff", str(bus["srp_coeff"]),
        "--drag-area-m2", str(bus["drag_area"]),
        "--srp-area-m2", str(bus["srp_area"]),
        "--propulsion-type", bus["propulsion_type"],
        "--thrust-mn", str(bus["thrust_mn"]),
        "--isp-s", str(bus["isp_s"]),
        "--propellant-kg", str(bus["propellant"]),
        "--eclipse-sunlit-threshold", str(bus["eclipse_sunlit_threshold"]),
        "--panel-area-m2", str(power_rf["panel_area_m2"]),
        "--panel-efficiency", str(power_rf["panel_efficiency"]),
        "--bus-idle-power-w", str(power_rf["bus_idle_power_w"]),
        "--instrument-power-w", str(power_rf["instrument_power_w"]),
        "--downlink-tx-power-w", str(power_rf["downlink_tx_power_w"]),
        "--battery-capacity-wh", str(power_rf["battery_capacity_wh"]),
        "--battery-initial-soc", str(power_rf["battery_initial_soc"]),
        "--rf-frequency-ghz", str(power_rf["rf_frequency_ghz"]),
        "--downlink-rate-mbps", str(power_rf["downlink_rate_mbps"]),
        "--rf-tx-antenna-gain-dbi", str(power_rf["rf_tx_antenna_gain_dbi"]),
        "--rf-ground-antenna-gain-dbi", str(power_rf["rf_ground_antenna_gain_dbi"]),
        "--rf-system-noise-temp-k", str(power_rf["rf_system_noise_temp_k"]),
        "--rf-implementation-loss-db", str(power_rf["rf_implementation_loss_db"]),
        "--rf-required-ebno-db", str(power_rf["rf_required_ebno_db"]),
        "--antenna-boresight-b", attitude["antenna_boresight_b"],
        "--panel-normal-b", attitude["panel_normal_b"],
        "--attitude-k", str(attitude["attitude_k"]),
        "--attitude-p", str(attitude["attitude_p"]),
        "--attitude-max-torque-nm", str(attitude["attitude_max_torque_nm"]),
        "--alt-deadband-km", str(alt_deadband_km),
        "--phasing-tolerance-fraction", str(phasing_tolerance_fraction),
        "--earth-grav-degree", str(grav_degree),
    ]
    print("\nApplying scalar settings via configure_mission.py...")
    rc = configure_mission.main(argv)
    if rc != 0:
        print("\nconstellation_setup.json was written, but applying the scalar settings above "
              "failed (see the error) -- fix mission_config.py or re-run this wizard.",
              file=sys.stderr)
        return rc

    print("\nSetup complete. Run python3 run_constellation_mission.py to use it.")
    if ask_yes_no("\nRun a quick --years 0.05 smoke test now?", default=True):
        subprocess.run(
            [sys.executable, "run_constellation_mission.py", "--years", "0.05", "--no-plots"],
            cwd=SCRIPT_DIR,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
