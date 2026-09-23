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

r"""Batch/headless CLI, separate from the interactive GUI -- and built on
exactly the same ``schema``/``engine`` layer the GUI uses, nothing
duplicated. This is also the architectural proof that the "decoupled from
the sim engine via a clean API/service layer" goal actually held: every
command below is a thin wrapper over ``schema.load_scenario()``,
``engine.service.SimulationService``, ``engine.kernels``, and
``engine.spaceweather`` -- the exact same calls
``gui.main_window.MainWindow`` makes.

Commands that don't need Basilisk (``validate``) work without a Basilisk
build; commands that do (``run``, ``kernels-status``) import it lazily and
report a clear, specific error instead of an ``ImportError`` traceback if
it's missing -- see each command function's own lazy import.

Usage::

    missionstudio validate scenario.json
    missionstudio run scenario.json --out-dir results/
    missionstudio monte-carlo scenario.json --archive-dir mc_results/
    missionstudio kernels-status
    missionstudio spaceweather-resolve scenario.json
    missionstudio generate-constellation template.json --out constellation.json \
        --total-satellites 12 --planes 3 --phasing-factor 1 --altitude-km 780 --inclination-deg 86.4
    missionstudio gui
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .schema import ScenarioValidationError, load_scenario


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        scenario = load_scenario(args.scenario)
    except ScenarioValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {scenario.name!r} -- {len(scenario.spacecraft)} spacecraft, "
          f"schema version {scenario.schema_version}, epoch {scenario.epoch_utc}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        scenario = load_scenario(args.scenario)
    except ScenarioValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    if args.vizard_save_file and args.vizard_live_stream:
        print("ERROR: pass at most one of --vizard-save-file / --vizard-live-stream", file=sys.stderr)
        return 1

    try:
        from .engine.service import SimulationService
    except ImportError as exc:
        print(f"ERROR: Basilisk is not installed/built ({exc}) -- see missionStudio/README.md", file=sys.stderr)
        return 2

    vizard_request = None
    if args.vizard_save_file or args.vizard_live_stream:
        from .engine.vizard import VizardRequest

        vizard_request = VizardRequest(
            save_file=args.vizard_save_file, live_stream=args.vizard_live_stream,
            camera_target=args.vizard_camera_target, show_orbit_lines=not args.vizard_no_orbit_lines,
        )

    print(f"Running {scenario.name!r} ({len(scenario.spacecraft)} spacecraft, "
          f"{scenario.sim_settings.duration_days} day(s), {scenario.sim_settings.integrator})...")
    service = SimulationService(scenario, vizard_request=vizard_request)
    try:
        result = service.run()
    except Exception as exc:  # noqa: BLE001 -- report ANY run failure with a specific message, not a bare traceback
        print(f"ERROR: run failed: {exc}", file=sys.stderr)
        return 3

    paths = result.export_csv(args.out_dir)
    print(f"Wrote {len(paths)} CSV file(s) to {args.out_dir}:")
    for name, path in sorted(paths.items()):
        print(f"  {name}: {path}")

    if any(sc.station_keeping is not None for sc in scenario.spacecraft):
        print("Station-keeping summary:")
        _print_station_keeping_summary(scenario, result)
    if any(sc.constant_thrust is not None for sc in scenario.spacecraft):
        print("Constant-thrust summary:")
        _print_constant_thrust_summary(scenario, result)
    return 0


def _print_station_keeping_summary(scenario, result) -> None:
    """Prints total delta-V used and propellant used/remaining per
    spacecraft with ``station_keeping`` configured -- the headline numbers
    ``engine.orbit_maintenance`` tracks, surfaced directly rather than
    leaving the user to dig them out of a CSV. Reads the final sample of
    each spacecraft's ``.station_keeping.delta_v``/``.propellant_remaining``
    series (see ``engine.service.SimulationService.run()``); silently
    skips a spacecraft whose series aren't present (station_keeping was
    configured but, e.g., the run failed before the series could be built).

    A spacecraft with ``phasing_keeping`` ALSO configured shares one
    propellant tank between the two controllers (see
    ``schema.scenario.PhasingKeepingConfig``'s docstring), so
    ``propellant_used_kg`` here already covers both; delta-V is tracked
    separately per controller, so the total reported is their sum, with a
    breakdown line underneath.
    """
    for sc in scenario.spacecraft:
        if sc.station_keeping is None:
            continue
        delta_v_series = result.series.get(f"{sc.name}.station_keeping.delta_v")
        propellant_series = result.series.get(f"{sc.name}.station_keeping.propellant_remaining")
        if delta_v_series is None or propellant_series is None or len(delta_v_series.data) == 0:
            continue
        station_keeping_delta_v_m_s = float(delta_v_series.data[-1, 0])
        propellant_remaining_kg = float(propellant_series.data[-1, 0])
        propellant_used_kg = sc.station_keeping.propellant_kg - propellant_remaining_kg

        phasing_delta_v_m_s = 0.0
        if sc.phasing_keeping is not None:
            phasing_delta_v_series = result.series.get(f"{sc.name}.phasing_keeping.delta_v")
            if phasing_delta_v_series is not None and len(phasing_delta_v_series.data) > 0:
                phasing_delta_v_m_s = float(phasing_delta_v_series.data[-1, 0])

        total_delta_v_m_s = station_keeping_delta_v_m_s + phasing_delta_v_m_s
        print(f"  {sc.name}: {total_delta_v_m_s:.3f} m/s delta-V, "
              f"{propellant_used_kg:.3f} kg propellant used ({propellant_remaining_kg:.3f} kg remaining)")
        if sc.phasing_keeping is not None:
            print(f"    (altitude-keeping: {station_keeping_delta_v_m_s:.3f} m/s, "
                  f"phasing vs. {sc.phasing_keeping.chief_spacecraft!r}: {phasing_delta_v_m_s:.3f} m/s)")


def _print_constant_thrust_summary(scenario, result) -> None:
    """Same idea as :func:`_print_station_keeping_summary`, for
    ``constant_thrust`` -- an INDEPENDENT propellant budget/tank from
    station_keeping's (see ``schema.scenario.ConstantThrustConfig``'s
    docstring), so this is always its own separate line, never combined
    with the station-keeping summary above even when both are configured
    on the same spacecraft.
    """
    for sc in scenario.spacecraft:
        if sc.constant_thrust is None:
            continue
        delta_v_series = result.series.get(f"{sc.name}.constant_thrust.delta_v")
        propellant_series = result.series.get(f"{sc.name}.constant_thrust.propellant_remaining")
        if delta_v_series is None or propellant_series is None or len(delta_v_series.data) == 0:
            continue
        delta_v_m_s = float(delta_v_series.data[-1, 0])
        propellant_remaining_kg = float(propellant_series.data[-1, 0])
        propellant_used_kg = sc.constant_thrust.propellant_kg - propellant_remaining_kg
        print(f"  {sc.name}: {delta_v_m_s:.3f} m/s delta-V ({sc.constant_thrust.frame} frame), "
              f"{propellant_used_kg:.3f} kg propellant used ({propellant_remaining_kg:.3f} kg remaining)")


def cmd_monte_carlo(args: argparse.Namespace) -> int:
    try:
        scenario = load_scenario(args.scenario)
    except ScenarioValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    if not scenario.monte_carlo.enabled:
        print("ERROR: scenario.monte_carlo.enabled is false in this scenario file -- "
              "set it true (and configure dispersions) before running Monte Carlo", file=sys.stderr)
        return 1

    try:
        from .engine.monte_carlo import MonteCarloError, run_monte_carlo
    except ImportError as exc:
        print(f"ERROR: Basilisk is not installed/built ({exc}) -- see missionStudio/README.md", file=sys.stderr)
        return 2

    print(f"Running {scenario.monte_carlo.num_runs} Monte Carlo case(s) of {scenario.name!r} "
          f"({len(scenario.monte_carlo.dispersions)} dispersion(s), {scenario.monte_carlo.thread_count} thread(s))...")
    try:
        failures = run_monte_carlo(scenario, scenario.monte_carlo, args.archive_dir)
    except MonteCarloError as exc:
        print(f"ERROR: Monte Carlo run failed: {exc}", file=sys.stderr)
        return 3

    print(f"Archived results to {args.archive_dir}")
    if failures:
        print(f"FAILED runs: {failures}", file=sys.stderr)
        return 4
    print(f"All {scenario.monte_carlo.num_runs} run(s) succeeded.")
    return 0


def cmd_kernels_status(args: argparse.Namespace) -> int:
    try:
        from .engine import kernels
    except ImportError as exc:
        print(f"ERROR: Basilisk is not installed/built ({exc}) -- see missionStudio/README.md", file=sys.stderr)
        return 2

    statuses = kernels.ensure_kernels()
    for status in statuses:
        if status.available:
            cached_note = f" (cached, last modified {status.modified_utc})" if status.modified_utc else ""
            print(f"  OK    {status.filename}: {status.path}{cached_note}")
        else:
            print(f"  FAIL  {status.filename}: {status.error}")
    return 0 if all(s.available for s in statuses) else 1


def cmd_spaceweather_resolve(args: argparse.Namespace) -> int:
    try:
        scenario = load_scenario(args.scenario)
    except ScenarioValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    from .engine import spaceweather as sw

    start = datetime.fromisoformat(scenario.epoch_utc)
    end = start + timedelta(days=scenario.sim_settings.duration_days)
    resolved = sw.resolve(
        scenario.space_weather.source, start, end,
        local_file_path=scenario.space_weather.local_file_path,
        cache_dir=scenario.space_weather.cache_dir,
    )
    print(f"Resolved to: {resolved.path}")
    print(f"Synthetic: {resolved.is_synthetic}")
    for warning in resolved.warnings:
        print(f"  warning: {warning}")
    return 0


def cmd_generate_constellation(args: argparse.Namespace) -> int:
    try:
        scenario = load_scenario(args.scenario)
    except ScenarioValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    if args.template_spacecraft is not None:
        template = next((sc for sc in scenario.spacecraft if sc.name == args.template_spacecraft), None)
        if template is None:
            print(f"ERROR: no spacecraft named {args.template_spacecraft!r} in {args.scenario} -- "
                  f"this scenario has: {[sc.name for sc in scenario.spacecraft]}", file=sys.stderr)
            return 1
    elif len(scenario.spacecraft) == 1:
        template = scenario.spacecraft[0]
    else:
        print(f"ERROR: {args.scenario} has {len(scenario.spacecraft)} spacecraft -- pass "
              "--template-spacecraft NAME to say which one to clone into the constellation", file=sys.stderr)
        return 1

    from .engine.constellation import WalkerConstellationRequest, generate_walker_constellation

    # central_body always comes from the scenario itself, never an
    # independent flag -- see gui.constellation_dialog's docstring for why
    # a mismatch there would silently produce satellites at the wrong
    # altitude relative to whatever body actually gets simulated.
    request = WalkerConstellationRequest(
        total_satellites=args.total_satellites, num_planes=args.planes, phasing_factor=args.phasing_factor,
        altitude_km=args.altitude_km, inclination_deg=args.inclination_deg,
        central_body=scenario.gravity.central_body, eccentricity=args.eccentricity,
        arg_periapsis_deg=args.arg_periapsis_deg, pattern=args.pattern,
        raan_offset_deg=args.raan_offset_deg, name_prefix=args.name_prefix,
    )
    try:
        generated = generate_walker_constellation(request, template)
    except ScenarioValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    scenario.spacecraft = (scenario.spacecraft + generated) if args.append else generated
    try:
        scenario.save(args.out)
    except ScenarioValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    print(f"Generated {len(generated)} spacecraft ({args.planes} plane(s), {request.pattern} pattern) "
          f"from template {template.name!r}, wrote {len(scenario.spacecraft)}-spacecraft scenario to {args.out}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from .gui.app import main as gui_main
    except ImportError as exc:
        print(f"ERROR: the GUI needs PySide6 and matplotlib installed "
              f"(pip install -e '.[gui]') -- {exc}", file=sys.stderr)
        return 2
    return gui_main([])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="missionstudio", description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_validate = subparsers.add_parser("validate", help="validate a scenario file (no Basilisk needed)")
    p_validate.add_argument("scenario", type=Path)
    p_validate.set_defaults(func=cmd_validate)

    p_run = subparsers.add_parser("run", help="run a scenario headlessly and export results to CSV")
    p_run.add_argument("scenario", type=Path)
    p_run.add_argument("--out-dir", type=Path, default=Path("results"), help="directory to write CSV results to")
    p_run.add_argument("--vizard-save-file", type=str, default=None,
                        help="write a Vizard .bin playback file to this path (see engine/vizard.py)")
    p_run.add_argument("--vizard-live-stream", action="store_true",
                        help="live-stream to a Vizard instance already running on this machine")
    p_run.add_argument("--vizard-camera-target", type=str, default=None,
                        help="spacecraft or celestial body name for Vizard's camera to start locked on "
                             "(default: the scenario's central body -- an Earth-centered view with the orbit "
                             "tracing around it, like STK/GMAT/FreeFlyer, rather than a spacecraft-locked close-up)")
    p_run.add_argument("--vizard-no-orbit-lines", action="store_true",
                        help="don't draw Vizard's orbit-trace lines (they're on by default)")
    p_run.set_defaults(func=cmd_run)

    p_mc = subparsers.add_parser("monte-carlo", help="run a Monte Carlo batch and archive retained results")
    p_mc.add_argument("scenario", type=Path)
    p_mc.add_argument("--archive-dir", type=Path, default=Path("monte_carlo_results"),
                       help="directory to archive per-run parameters and retained data to")
    p_mc.set_defaults(func=cmd_monte_carlo)

    p_kernels = subparsers.add_parser("kernels-status", help="fetch/check SPICE kernel cache status")
    p_kernels.set_defaults(func=cmd_kernels_status)

    p_sw = subparsers.add_parser("spaceweather-resolve",
                                  help="resolve space weather for a scenario without running it (no Basilisk needed)")
    p_sw.add_argument("scenario", type=Path)
    p_sw.set_defaults(func=cmd_spaceweather_resolve)

    p_const = subparsers.add_parser(
        "generate-constellation",
        help="generate a Walker-pattern constellation from a template scenario (no Basilisk needed)",
    )
    p_const.add_argument("scenario", type=Path, help="scenario file to load the template spacecraft/gravity from")
    p_const.add_argument("--out", type=Path, required=True, help="scenario file to write the result to")
    p_const.add_argument("--template-spacecraft", type=str, default=None,
                          help="name of the spacecraft to clone into the constellation (required if the input "
                               "scenario has more than one spacecraft)")
    p_const.add_argument("--total-satellites", type=int, required=True, help="T -- total satellite count")
    p_const.add_argument("--planes", type=int, required=True, help="P -- number of orbital planes")
    p_const.add_argument("--phasing-factor", type=int, required=True, help="F -- Walker phasing factor, 0 <= F < P")
    p_const.add_argument("--altitude-km", type=float, required=True, help="circular-orbit altitude [km]")
    p_const.add_argument("--inclination-deg", type=float, required=True, help="orbit inclination [deg]")
    p_const.add_argument("--pattern", choices=["delta", "star"], default="delta",
                          help="Walker-Delta (RAAN spread over 360deg) or Walker-Star (180deg); default delta")
    p_const.add_argument("--eccentricity", type=float, default=0.0)
    p_const.add_argument("--arg-periapsis-deg", type=float, default=0.0)
    p_const.add_argument("--raan-offset-deg", type=float, default=0.0,
                          help="rotates the whole constellation's RAAN reference")
    p_const.add_argument("--name-prefix", type=str, default="sat",
                          help="generated spacecraft are named '{prefix}-{plane:02d}-{slot:02d}'")
    p_const.add_argument("--append", action="store_true",
                          help="add the generated satellites to the template scenario's existing spacecraft "
                               "instead of replacing them")
    p_const.set_defaults(func=cmd_generate_constellation)

    p_gui = subparsers.add_parser("gui", help="launch the PySide6 GUI shell")
    p_gui.set_defaults(func=cmd_gui)

    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
