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
Command-line front end for editing this mission's spacecraft/orbit
parameters, without hand-editing ``mission_config.py``.

This tool only edits single scalar values (bus, propulsion, epoch,
duration, altitude deadband, phasing tolerance, gravity degree) -- it does
NOT change how many satellites or ground stations there are, or give
individual satellites their own orbits. For that, use ``setup_wizard.py``
instead, which is interactive and covers everything this script does plus
the constellation's structure (satellite count, per-satellite orbits,
ground station locations), written to ``constellation_setup.json``.

Why editing ``mission_config.py`` *is* "updating all the relevant scripts"
----------------------------------------------------------------------------
``mission_config.py`` is the single source of truth for every spacecraft and
orbit parameter used across this toolkit: ``run_constellation_mission.py``,
``constellation_controllers.py``, and ``communications.py`` all import their
constants from it and hold no values of their own. So changing a value there
and re-running ``run_constellation_mission.py`` already picks it up
everywhere it is used -- there is nothing else in this folder that needs
separate updating. The one derived artifact this script also regenerates
for you is ``data/placeholder_space_weather.csv``, whose date range depends
on the epoch and mission duration.

How this script edits the file
-------------------------------
This does NOT regenerate ``mission_config.py`` from scratch. It only
replaces the right-hand side of the specific ``NAME = <value>`` assignments
you pass a flag for, preserving every comment, docstring, and derived-value
formula untouched. Constants that are *derived* from the ones below
(``A_NOMINAL_M``, ``SSO_RAAN_DEG``, ``ORBIT_PERIOD_S``, the ``SATELLITES``
list, ...) are computed automatically the next time ``mission_config.py``
is imported or run -- do not (and cannot) set those directly here.

A few inline comments mention the specific old value in words (e.g. "~10 mN"
next to the thrust constant); those are not rewritten, so skim
``mission_config.py`` afterward if a comment looks stale. Any comment
containing the word "PLACEHOLDER" next to a field you explicitly set IS
rewritten (the word is dropped) since a value you deliberately chose is no
longer a guess.

Usage examples::

    # preview changes without writing anything
    python3 configure_mission.py --dry-run --altitude-km 600

    # bump SSO altitude and give it a bigger propellant budget
    python3 configure_mission.py --altitude-km 600 --propellant-kg 50

    # move the epoch and shorten the mission for a quick study
    python3 configure_mission.py --epoch 2030-01-01 --mission-years 2

    # retarget the mid-inclination plane once its coverage RAAN is chosen
    python3 configure_mission.py --midinc-raan-deg 42.5

Run with ``--help`` for the full list of overridable fields. Anything not
covered here (station-keeping deadbands, task rates, comms/ground-station
settings, ...) can still be edited directly in ``mission_config.py``.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "mission_config.py"


# ---------------------------------------------------------------------------
# Surgical text editing of mission_config.py
# ---------------------------------------------------------------------------
def _constant_pattern(name: str) -> re.Pattern:
    # Every \s* here is deliberately [ \t]* instead: \s matches newlines too,
    # so on a constant with NO trailing comment of its own, followed by a
    # blank line and then a comment (a common section-boundary pattern in
    # mission_config.py), a \s* before "#" would silently cross the blank
    # line and glom the NEXT section's comment onto this constant -- not
    # just a display bug, but real file corruption on write (confirmed:
    # EARTH_GRAV_DEGREE, with no comment of its own, ate the "communications"
    # section-header comment two lines below it).
    return re.compile(rf"^({re.escape(name)}[ \t]*=[ \t]*)([^#\n]+?)([ \t]*#.*)?$", re.MULTILINE)


def _current_value(text: str, name: str) -> str:
    matches = list(_constant_pattern(name).finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one assignment to '{name}' in {CONFIG_PATH.name}, "
            f"found {len(matches)}. Refusing to guess -- edit mission_config.py manually."
        )
    return matches[0].group(2).strip()


def _current_comment(text: str, name: str) -> str:
    matches = list(_constant_pattern(name).finditer(text))
    if len(matches) != 1:
        return ""
    return (matches[0].group(3) or "").strip()


def _set_constant(text: str, name: str, value_literal: str, strip_placeholder: bool = True) -> str:
    """Replace the right-hand side of ``NAME = ...`` with ``value_literal``,
    keeping any trailing inline comment (minus a leading "PLACEHOLDER" word,
    since an explicitly-set value is no longer a guess).
    """
    pattern = _constant_pattern(name)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one assignment to '{name}' in {CONFIG_PATH.name}, "
            f"found {len(matches)}. Refusing to guess -- edit mission_config.py manually."
        )
    m = matches[0]
    comment = m.group(3) or ""
    if strip_placeholder and comment:
        comment = re.sub(r"PLACEHOLDER:?\s*", "", comment, flags=re.IGNORECASE)
        comment = re.sub(r"\s{2,}", "  ", comment).rstrip()
        if comment.strip() in ("", "#"):
            comment = ""
    new_line = f"{m.group(1)}{value_literal}{comment}"
    return text[: m.start()] + new_line + text[m.end() :]


def _epoch_literals(dt: datetime) -> tuple:
    """(EPOCH_UTC python literal, EPOCH_SPICE_STRING literal) for a datetime."""
    py_literal = f"datetime({dt.year}, {dt.month}, {dt.day}, {dt.hour}, {dt.minute}, {dt.second})"
    spice_string = dt.strftime("%Y %b %d %H:%M:%S.0 (UTC)").upper()
    return py_literal, repr(spice_string)


# ---------------------------------------------------------------------------
# Overridable fields: CLI flag <-> mission_config.py constant, with the unit
# conversion (user-facing unit -> the constant's SI/native unit) applied.
# ---------------------------------------------------------------------------
@dataclass
class Field:
    flag: str
    dest: str
    constant: str
    parser: Callable[[str], Any]
    to_literal: Callable[[Any], str]
    help: str


def _num(x: str) -> float:
    return float(x)


def _str(x: str) -> str:
    return x


def _lit(x: Any) -> str:
    return repr(x)


FIELDS = [
    # --- Spacecraft bus -----------------------------------------------
    Field("--dry-mass-kg", "dry_mass_kg", "DRY_MASS_KG", _num, _lit, "spacecraft dry mass [kg]"),
    Field("--drag-coeff", "drag_coeff", "DRAG_COEFF", _num, _lit, "drag coefficient Cd [-]"),
    Field("--srp-coeff", "srp_coeff", "SRP_COEFF", _num, _lit, "SRP reflectivity coefficient Cr [-]"),
    Field("--drag-area-m2", "drag_area_m2", "DRAG_AREA_M2", _num, _lit, "drag cross-sectional area [m^2]"),
    Field("--srp-area-m2", "srp_area_m2", "SRP_AREA_M2", _num, _lit, "SRP cross-sectional area [m^2]"),
    # --- Propulsion ------------------------------------------------------
    Field("--propulsion-type", "propulsion_type", "PROPULSION_TYPE", _str, _lit,
          "propulsion system/thruster description [-] (descriptive only, does not affect the simulation)"),
    Field("--thrust-mn", "thrust_mn", "THRUST_N", _num, lambda x: _lit(x * 1.0e-3),
          "electric thruster thrust [mN]"),
    Field("--isp-s", "isp_s", "ISP_S", _num, _lit, "thruster specific impulse [s]"),
    Field("--propellant-kg", "propellant_kg", "PROPELLANT_MASS_BOL_KG", _num, _lit,
          "beginning-of-life propellant mass [kg]"),
    Field("--eclipse-sunlit-threshold", "eclipse_sunlit_threshold", "ECLIPSE_SUNLIT_THRESHOLD", _num, _lit,
          "shadow factor above which the spacecraft counts as sunlit [-, 0-1] "
          "(gates both thrust-enable and the EO instrument's duty cycle)"),
    # --- Constellation orbit ----------------------------------------------
    Field("--altitude-km", "altitude_km", "ALT_NOMINAL_M", _num, lambda x: _lit(x * 1.0e3),
          "default altitude used to build the SSO plane and standalone satellite [km] "
          "(only when constellation_setup.json is absent -- see setup_wizard.py for per-satellite altitudes)"),
    Field("--sso-inclination-deg", "sso_inclination_deg", "SSO_INCLINATION_DEG", _num, _lit,
          "SSO plane inclination [deg]"),
    Field("--sso-ecc", "sso_ecc", "SSO_ECC", _num, _lit, "SSO plane eccentricity [-]"),
    Field("--sso-aop-deg", "sso_aop_deg", "SSO_AOP_DEG", _num, _lit,
          "SSO argument of perigee (90 or 270 for frozen orbit) [deg]"),
    Field("--sso-ltdn-hours", "sso_ltdn_hours", "SSO_LTDN_HOURS", _num, _lit,
          "SSO local time of descending node [hr, 0-24]"),
    Field("--midinc-inclination-deg", "midinc_inclination_deg", "MIDINC_INCLINATION_DEG", _num, _lit,
          "mid-inclination plane inclination [deg]"),
    Field("--midinc-ecc", "midinc_ecc", "MIDINC_ECC", _num, _lit, "mid-inclination plane eccentricity [-]"),
    Field("--midinc-aop-deg", "midinc_aop_deg", "MIDINC_AOP_DEG", _num, _lit,
          "mid-inclination argument of perigee [deg]"),
    Field("--midinc-raan-deg", "midinc_raan_deg", "MIDINC_RAAN_DEG", _num, _lit,
          "mid-inclination RAAN (coverage-driven) [deg]"),
    Field("--midinc-mean-anom-deg", "midinc_mean_anom_deg", "MIDINC_MEAN_ANOM_DEG", _num, _lit,
          "mid-inclination initial mean anomaly [deg]"),
    # --- Station-keeping / phasing -----------------------------------------
    Field("--alt-deadband-km", "alt_deadband_km", "ALT_DEADBAND_M", _num, lambda x: _lit(x * 1.0e3),
          "altitude station-keeping deadband below nominal [km]"),
    Field("--phasing-tolerance-deg", "phasing_tolerance_deg", "PHASING_TOLERANCE_DEG", _num, _lit,
          "SSO phasing trigger threshold [deg]"),
    # --- Gravity fidelity -----------------------------------------------
    Field("--earth-grav-degree", "earth_grav_degree", "EARTH_GRAV_DEGREE", lambda x: int(x), _lit,
          "Earth spherical-harmonics gravity degree/order [-]"),
    # --- Epoch / duration (EPOCH_UTC handled separately, see main()) ------
    Field("--mission-years", "mission_years", "MISSION_DURATION_YEARS", _num,
          lambda x: _lit(int(x) if float(x).is_integer() else x), "mission duration [yr]"),
]

_VALIDATORS = {
    "dry_mass_kg": lambda v: v > 0 or "must be > 0",
    "drag_coeff": lambda v: v > 0 or "must be > 0",
    "srp_coeff": lambda v: v > 0 or "must be > 0",
    "drag_area_m2": lambda v: v > 0 or "must be > 0",
    "srp_area_m2": lambda v: v > 0 or "must be > 0",
    "propulsion_type": lambda v: bool(v.strip()) or "must not be empty",
    "propellant_kg": lambda v: v >= 0 or "must be >= 0",
    "thrust_mn": lambda v: v > 0 or "must be > 0",
    "isp_s": lambda v: v > 0 or "must be > 0",
    "eclipse_sunlit_threshold": lambda v: 0.0 < v <= 1.0 or "must be in (0, 1]",
    "altitude_km": lambda v: v > 100 or "must be > 100 km (else drag will deorbit it almost immediately)",
    "sso_inclination_deg": lambda v: 0 <= v <= 180 or "must be in [0, 180] deg",
    "sso_ecc": lambda v: 0 <= v < 1 or "must be in [0, 1) (elliptical orbit)",
    "sso_ltdn_hours": lambda v: 0 <= v < 24 or "must be in [0, 24) hr",
    "midinc_inclination_deg": lambda v: 0 <= v <= 180 or "must be in [0, 180] deg",
    "midinc_ecc": lambda v: 0 <= v < 1 or "must be in [0, 1) (elliptical orbit)",
    "alt_deadband_km": lambda v: v > 0 or "must be > 0",
    "phasing_tolerance_deg": lambda v: v > 0 or "must be > 0",
    "earth_grav_degree": lambda v: 0 <= v <= 360 or "must be a plausible spherical-harmonics degree",
    "mission_years": lambda v: v > 0 or "must be > 0",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--epoch", type=str, default=None, metavar="ISO_DATETIME",
        help="mission epoch, UTC, e.g. 2030-01-01 or 2030-01-01T06:00:00",
    )
    for field in FIELDS:
        parser.add_argument(field.flag, dest=field.dest, type=str, default=None, help=field.help)
    parser.add_argument("--dry-run", action="store_true",
                         help="print what would change without writing mission_config.py "
                              "or regenerating the space-weather file")
    parser.add_argument("--no-regen-space-weather", action="store_true",
                         help="skip regenerating data/placeholder_space_weather.csv afterward "
                              "(it depends on epoch/mission-years, so this is normally desired)")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)

    overrides = []  # list of (field, raw_value)
    for field in FIELDS:
        raw = getattr(args, field.dest)
        if raw is None:
            continue
        try:
            value = field.parser(raw)
        except ValueError:
            print(f"error: {field.flag} expects a number, got {raw!r}", file=sys.stderr)
            return 2
        validator = _VALIDATORS.get(field.dest)
        if validator is not None:
            ok = validator(value)
            if ok is not True:
                print(f"error: {field.flag} {ok}", file=sys.stderr)
                return 2
        overrides.append((field, value))

    epoch_dt = None
    if args.epoch is not None:
        try:
            epoch_dt = datetime.fromisoformat(args.epoch)
        except ValueError:
            print(f"error: --epoch could not parse {args.epoch!r} as an ISO datetime "
                  f"(try YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)", file=sys.stderr)
            return 2

    if not overrides and epoch_dt is None:
        print("Nothing to do -- pass at least one override flag (see --help).")
        return 0

    text = CONFIG_PATH.read_text()
    original_text = text

    print(f"{'Would change' if args.dry_run else 'Changing'} in {CONFIG_PATH.relative_to(SCRIPT_DIR.parent)}:")

    if epoch_dt is not None:
        old_epoch = _current_value(text, "EPOCH_UTC")
        py_literal, spice_literal = _epoch_literals(epoch_dt)
        text = _set_constant(text, "EPOCH_UTC", py_literal)
        text = _set_constant(text, "EPOCH_SPICE_STRING", spice_literal)
        print(f"  EPOCH_UTC: {old_epoch}  ->  {py_literal}")

    for field, value in overrides:
        old = _current_value(text, field.constant)
        new_literal = field.to_literal(value)
        text = _set_constant(text, field.constant, new_literal)
        comment = _current_comment(text, field.constant)
        note = f"    {comment}" if comment else ""
        print(f"  {field.constant}: {old}  ->  {new_literal}{note}")

    if args.dry_run:
        print("\n--dry-run: no files were written.")
        return 0

    if text == original_text:
        print("(no textual change)")
        return 0

    CONFIG_PATH.write_text(text)
    print(f"\nWrote {CONFIG_PATH.name}.")

    # Fail loudly now, rather than leaving a mission_config.py that fails to
    # import the next time run_constellation_mission.py starts up.
    check = subprocess.run([sys.executable, "-c", "import mission_config"], cwd=SCRIPT_DIR)
    if check.returncode != 0:
        print("\nERROR: the edited mission_config.py failed to import (see traceback above). "
              "The file on disk has been left as written above -- fix it by hand or re-run "
              "this script with corrected values.", file=sys.stderr)
        return 1

    if (epoch_dt is not None or any(f.dest == "mission_years" for f, _ in overrides)) and \
            not args.no_regen_space_weather:
        print("\nRegenerating data/placeholder_space_weather.csv for the new epoch/duration...")
        subprocess.run([sys.executable, "generate_space_weather_placeholder.py"], cwd=SCRIPT_DIR, check=True)

    print("\nDone. Every script in this folder reads mission_config.py at import time, so "
          "run_constellation_mission.py will pick these values up on its next run -- there is "
          "nothing else to update by hand. The comments shown above next to each changed value "
          "were NOT rewritten (only the value was) -- if one of them describes the old number in "
          "words (e.g. a specific altitude, mass, or thrust) rather than just a unit, it may now "
          "read as stale; edit it by hand in mission_config.py if so.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
