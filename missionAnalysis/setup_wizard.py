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
* Spacecraft bus (mass, Cd, Cr, drag/SRP areas, propellant) and electric
  propulsion (thrust, Isp)
* The SSO constellation plane: altitude, inclination, eccentricity, AOP,
  local time of descending node, and satellite COUNT (evenly phased in
  mean anomaly; each gets independent altitude station-keeping, and for
  count > 1, in-plane phasing against a chief satellite)
* Any number of additional standalone satellites, each with its own orbit
* Any number of ground stations (with a couple of real-world presets, or
  fully custom lat/lon/altitude/elevation-mask)
* Station-keeping deadband, phasing tolerance, Earth gravity fidelity

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
    propellant = ask_float(
        "Propellant mass, beginning-of-life [kg]", mc.PROPELLANT_MASS_BOL_KG, lambda v: v >= 0 or "must be >= 0"
    )

    section("Electric propulsion")
    thrust_mn = ask_float("Thrust [mN]", mc.THRUST_N * 1000.0, lambda v: v > 0 or "must be > 0")
    isp_s = ask_float("Specific impulse Isp [s]", mc.ISP_S, lambda v: v > 0 or "must be > 0")

    return dict(
        dry_mass=dry_mass, drag_coeff=drag_coeff, srp_coeff=srp_coeff, drag_area=drag_area,
        srp_area=srp_area, propellant=propellant, thrust_mn=thrust_mn, isp_s=isp_s,
    )


def ask_sso_plane():
    # Defaults come from mc.SSO_PLANE, which already reflects an existing
    # constellation_setup.json if this wizard was run before -- re-running
    # it to tweak one value shows your last answers, not the hardcoded
    # mission defaults.
    # mc.SSO_PLANE already equals these same scalars' defaults when no JSON
    # exists yet, so this is correct either way -- re-editing or not.
    current = mc.SSO_PLANE
    section("Sun-synchronous (SSO) constellation plane")
    print("Satellites in this plane share one orbit, evenly spaced in mean anomaly.")
    print("Each gets independent altitude station-keeping; with more than one satellite,")
    print("each also gets in-plane phasing against the first satellite (the chief).")
    count = ask_int("Number of satellites in this plane (0 for none)", current["count"],
                     lambda v: v >= 0 or "must be >= 0")
    if count == 0:
        return dict(count=0, altitude_km=current["altitude_km"], inclination_deg=current["inclination_deg"],
                    ecc=current["ecc"], aop_deg=current["aop_deg"], ltdn_hours=current["ltdn_hours"])
    altitude_km = ask_float("Altitude [km]", current["altitude_km"], lambda v: v > 100 or "must be > 100 km")
    inclination_deg = ask_float("Inclination [deg]", current["inclination_deg"],
                                 lambda v: 0 <= v <= 180 or "must be in [0, 180]")
    ecc = ask_float("Eccentricity [-]", current["ecc"], lambda v: 0 <= v < 1 or "must be in [0, 1)")
    aop_deg = ask_float("Argument of perigee [deg] (90 or 270 gives a frozen orbit)", current["aop_deg"],
                         lambda v: 0 <= v < 360 or "must be in [0, 360)")
    ltdn_hours = ask_float("Local time of descending node [hr, 0-24]", current["ltdn_hours"],
                            lambda v: 0 <= v < 24 or "must be in [0, 24)")
    return dict(count=count, altitude_km=altitude_km, inclination_deg=inclination_deg, ecc=ecc,
                aop_deg=aop_deg, ltdn_hours=ltdn_hours)


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


def ask_advanced():
    section("Station-keeping and mission fidelity")
    alt_deadband_km = ask_float("Altitude station-keeping deadband [km]", mc.ALT_DEADBAND_M / 1000.0,
                                 lambda v: v > 0 or "must be > 0")
    phasing_tolerance_deg = ask_float("Phasing trigger tolerance [deg]", mc.PHASING_TOLERANCE_DEG,
                                       lambda v: v > 0 or "must be > 0")
    grav_degree = ask_int("Earth gravity spherical-harmonics degree/order", mc.EARTH_GRAV_DEGREE,
                           lambda v: 0 <= v <= 360 or "must be a plausible degree")
    return alt_deadband_km, phasing_tolerance_deg, grav_degree


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
    alt_deadband_km, phasing_tolerance_deg, grav_degree = ask_advanced()

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
        "--propellant-kg", str(bus["propellant"]),
        "--thrust-mn", str(bus["thrust_mn"]),
        "--isp-s", str(bus["isp_s"]),
        "--alt-deadband-km", str(alt_deadband_km),
        "--phasing-tolerance-deg", str(phasing_tolerance_deg),
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
