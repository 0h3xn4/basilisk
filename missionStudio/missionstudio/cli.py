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
    missionstudio kernels-status
    missionstudio spaceweather-resolve scenario.json
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

    try:
        from .engine.service import SimulationService
    except ImportError as exc:
        print(f"ERROR: Basilisk is not installed/built ({exc}) -- see missionStudio/README.md", file=sys.stderr)
        return 2

    print(f"Running {scenario.name!r} ({len(scenario.spacecraft)} spacecraft, "
          f"{scenario.sim_settings.duration_days} day(s), {scenario.sim_settings.integrator})...")
    service = SimulationService(scenario)
    try:
        result = service.run()
    except Exception as exc:  # noqa: BLE001 -- report ANY run failure with a specific message, not a bare traceback
        print(f"ERROR: run failed: {exc}", file=sys.stderr)
        return 3

    paths = result.export_csv(args.out_dir)
    print(f"Wrote {len(paths)} CSV file(s) to {args.out_dir}:")
    for name, path in sorted(paths.items()):
        print(f"  {name}: {path}")
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
    p_run.set_defaults(func=cmd_run)

    p_kernels = subparsers.add_parser("kernels-status", help="fetch/check SPICE kernel cache status")
    p_kernels.set_defaults(func=cmd_kernels_status)

    p_sw = subparsers.add_parser("spaceweather-resolve",
                                  help="resolve space weather for a scenario without running it (no Basilisk needed)")
    p_sw.add_argument("scenario", type=Path)
    p_sw.set_defaults(func=cmd_spaceweather_resolve)

    p_gui = subparsers.add_parser("gui", help="launch the PySide6 GUI shell")
    p_gui.set_defaults(func=cmd_gui)

    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
