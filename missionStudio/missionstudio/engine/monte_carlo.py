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
Phase 3: Monte Carlo batch execution, wrapping the real, already-native
``Basilisk.utilities.MonteCarlo`` framework (``Controller``,
``Dispersions``, ``RetentionPolicy``) -- this module does not reimplement
any dispersion math or batch-execution logic; it only translates
:class:`schema.scenario.MonteCarloConfig`/``DispersionConfig`` into calls
against that framework, matching the pattern already `.md` documented in
``src/utilities/MonteCarlo/README.md`` and exercised end-to-end in
``examples/scenarioMonteCarloAttRW.py``.

Why ``SimulationService.build(initialize=False)``
---------------------------------------------------
``Controller`` calls, per run: creation function (no args, returns a
``SimBaseClass``) -> apply dispersions (mutating attributes directly on
that returned sim object, via dotted/indexed/zero-arg-method path strings
-- see ``Controller.SimulationExecutor.getNestedAttr``/``setNestedAttr``)
-> configure function (optional) -> execution function. Basilisk's
``InitializeSimulation()`` calls ``Reset()`` on every module using
whatever attribute values are set AT THAT MOMENT -- if it already ran
(which ``SimulationService.build()`` always used to do, Phase 0 through
Phase 2), a dispersion applied afterward would silently have no effect,
since Reset() already latched in the un-dispersed nominal values. So the
creation function here calls ``service.build(initialize=False)`` and the
execution function finishes the job (``InitializeSimulation()``,
``ConfigureStopTime()``, ``ExecuteSimulation()``) AFTER the Controller has
applied every dispersion.

A ``dry_mass_kg`` dispersion writes directly to ``hub.mHub`` (see
``_QUANTITY_PATHS`` below), which survives ``Reset()`` fine (no module's
``Reset()`` touches ``hub.mHub``) -- but a real bug, found by audit and
fixed in ``engine.orbit_maintenance``, used to silently UNDO it on the
first tick for any spacecraft with ``station_keeping``/``constant_thrust``
configured: those controllers used to recompute ``hub.mHub`` from their
own construction-time-captured, undispersed ``dry_mass_kg`` every tick,
discarding whatever this dispersion had just set. See
``engine.orbit_maintenance``'s "Shared mass bookkeeping" docstring note --
those controllers now read ``hub.mHub`` back and only subtract what they
themselves burn, so a dispersion applied here is preserved correctly.

Dispersion path resolution
---------------------------
Basilisk's dispersion path strings resolve via attribute access, integer
indexing, and zero-argument method calls ONLY -- no string-keyed lookups
(confirmed by reading ``Controller._parseAttributePath``/``_resolvePathPart``
directly: a path segment is either ``.name``, ``[int]``, or ``name()``).
Since a scenario can have several spacecraft, and there is no
string-keyed way to reach "the sc_object for spacecraft named X" from the
sim object, the creation function attaches one dynamically-named,
zero-argument accessor method per spacecraft directly onto the returned
sim object (``sim.get_spacecraft_<sanitized name>()`` -> that spacecraft's
``spacecraft.Spacecraft`` instance) -- a dispersion path like
``"get_spacecraft_sat_1().hub.mHub"`` then resolves exactly per the rules
above. This is not a Basilisk API; it is this module's own bridge, built
entirely from the documented, verified path-resolution rules.

Retained data
-------------
V1 scope: every run retains each spacecraft's position/velocity
(``r_BN_N``/``v_BN_N`` off its ``scStateOutMsg`` recorder, via
``sim.msgRecList`` + one ``RetentionPolicy.addMessageLog`` call per
spacecraft -- both documented, verified mechanisms, see
``MonteCarlo/README.md``'s "Retain simulation data" section). There is no
per-run custom retention selection in the schema yet (e.g. "also retain
attitude" or "also retain a specific sensor") -- a reasonable v1 scope
given position/velocity dispersion spread is the headline Monte Carlo
question for a mission-analysis tool, extendable later without a schema
break (``MonteCarloConfig`` is a dataclass like everything else here).

Thread count
------------
``Controller.setThreadCount(n)`` for ``n > 1`` uses ``multiprocessing.Pool``
(confirmed by reading ``Controller.py`` directly). Python's
``multiprocessing`` needs the worker's target callables to be importable
(pickle-based "spawn"/"forkserver" start methods) or merely needs the
parent process state duplicated (fork). This module's creation/execution
functions are plain module-level functions (not closures) specifically so
they pickle cleanly either way, but the SCENARIO itself is threaded through
via ``functools.partial`` (also picklable, since :class:`Scenario` is a
plain dataclass tree of built-in types). This has NOT been exercised
against a real multi-process run in this project's development sandbox
(no Basilisk build here -- see this module's own verification-status note
below), so :data:`schema.scenario.MonteCarloConfig.thread_count` defaults
to the definitely-safe ``1``.

Verification status
--------------------
Requires a Basilisk build -- cannot be executed in this development
sandbox (no Basilisk build here; see ``missionStudio/README.md``). Written
directly against ``src/utilities/MonteCarlo/Controller.py``,
``Dispersions.py``, and ``RetentionPolicy.py`` (read directly in this
checkout, including ``Controller``'s path-parsing internals) and against
that package's own ``README.md`` usage guide -- not from memory, and not
guessed.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import List

from Basilisk.utilities import macros
from Basilisk.utilities.MonteCarlo.Controller import Controller
from Basilisk.utilities.MonteCarlo.Dispersions import (
    NormalDispersion,
    UniformDispersion,
    UniformEulerAngleMRPDispersion,
)
from Basilisk.utilities.MonteCarlo.RetentionPolicy import RetentionPolicy

from ..schema.scenario import DispersionConfig, MonteCarloConfig, Scenario
from .service import SimulationService

# spacecraft.name -> attribute path suffix on that spacecraft's sc_object,
# rooted after the "get_spacecraft_<name>()." accessor -- see module
# docstring. Kept in lock-step with schema.scenario.DISPERSION_QUANTITIES.
_QUANTITY_PATHS = {
    "dry_mass_kg": "hub.mHub",
    "attitude_sigma_bn": "hub.sigma_BNInit",
}


class MonteCarloError(Exception):
    """Raised for anything that prevents building or running the Monte
    Carlo batch -- always a specific, actionable message.
    """


def _accessor_name(spacecraft_name: str) -> str:
    """A valid, unique-enough Python identifier for
    ``sim.get_spacecraft_<...>()`` -- see module docstring. Uniqueness
    relies on ``schema.scenario.Scenario.validate()`` already requiring
    spacecraft names to be unique; two names that only differ by
    non-identifier characters (e.g. ``"sat 1"`` and ``"sat-1"``) would
    collide here, which is a real but narrow edge case worth knowing about
    rather than silently mishandling -- callers with such names should
    rename them.
    """
    safe = re.sub(r"\W+", "_", spacecraft_name)
    if not safe or safe[0].isdigit():
        safe = f"sc_{safe}"
    return f"get_spacecraft_{safe}"


def _build_dispersion(dispersion: DispersionConfig):
    accessor = _accessor_name(dispersion.spacecraft)
    path = f"{accessor}().{_QUANTITY_PATHS[dispersion.quantity]}"

    if dispersion.quantity == "dry_mass_kg":
        if dispersion.kind == "uniform":
            return UniformDispersion(path, bounds=dispersion.bounds)
        if dispersion.kind == "normal":
            return NormalDispersion(path, mean=dispersion.mean, stdDeviation=dispersion.std_deviation,
                                     bounds=dispersion.bounds)
    if dispersion.quantity == "attitude_sigma_bn" and dispersion.kind == "uniform_euler_mrp":
        return UniformEulerAngleMRPDispersion(path, bounds=dispersion.bounds)

    # unreachable if DispersionConfig.validate() passed (schema.scenario.DISPERSION_KINDS_BY_QUANTITY
    # is the single source of truth for which (quantity, kind) pairings exist)
    raise MonteCarloError(
        f"no engine.monte_carlo builder for dispersion kind {dispersion.kind!r} on quantity "
        f"{dispersion.quantity!r} (spacecraft {dispersion.spacecraft!r})"
    )


def _create_sim(scenario: Scenario):
    """Monte Carlo creation function (see module docstring for why
    ``initialize=False``). Module-level + ``functools.partial``-bound
    (never a closure) so it stays picklable for ``thread_count > 1``.
    """
    service = SimulationService(scenario)
    service.build(initialize=False)
    sim = service.scSim

    for name, handle in service.spacecraft_handles.items():
        sc_object = handle.sc_object
        setattr(sim, _accessor_name(name), (lambda sc_object=sc_object: sc_object))

    sim.msgRecList = {f"{name}.scState": handle.recorder for name, handle in service.spacecraft_handles.items()}
    sim._missionstudio_service = service  # stashed for _execute_sim to finish init/configure/execute
    return sim


def _execute_sim(sim) -> None:
    """Monte Carlo execution function: finishes what ``_create_sim`` left
    undone, AFTER the Controller has applied every dispersion to ``sim``
    (see module docstring).
    """
    service = sim._missionstudio_service
    sim.InitializeSimulation()
    stop_time_s = service.scenario.sim_settings.duration_days * 86400.0
    sim.ConfigureStopTime(macros.sec2nano(stop_time_s))
    sim.ExecuteSimulation()


def _default_retention_policy(scenario: Scenario) -> RetentionPolicy:
    policy = RetentionPolicy()
    for sc in scenario.spacecraft:
        policy.addMessageLog(f"{sc.name}.scState", ["r_BN_N", "v_BN_N"])
    return policy


def run_monte_carlo(scenario: Scenario, mc_config: MonteCarloConfig, archive_dir: "str | Path") -> List[int]:
    """Runs ``mc_config.num_runs`` dispersed executions of ``scenario`` via
    ``Basilisk.utilities.MonteCarlo.Controller``, archiving retained
    position/velocity data (JSON per-run parameter files plus the
    Controller's own pickled archive) to ``archive_dir``. Returns the list
    of FAILED run indices, exactly as ``Controller.executeSimulations()``
    does (empty list == every run succeeded).

    ``scenario`` must already be valid (``scenario.validate()`` -- this
    function does not re-validate it, since :func:`SimulationService.build`
    inside each run's creation function does, and a validation failure
    there surfaces as a per-run failure rather than an upfront one).
    """
    if not mc_config.enabled:
        raise MonteCarloError("monte_carlo.enabled is False -- set it True before calling run_monte_carlo()")

    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    controller = Controller()
    controller.setSimulationFunction(functools.partial(_create_sim, scenario))
    controller.setExecutionFunction(_execute_sim)
    controller.setExecutionCount(mc_config.num_runs)
    controller.setShouldDisperseSeeds(True)
    controller.setThreadCount(mc_config.thread_count)
    controller.setVerbose(mc_config.verbose)
    controller.setArchiveDir(str(archive_dir))

    for dispersion in mc_config.dispersions:
        controller.addDispersion(_build_dispersion(dispersion))

    controller.addRetentionPolicy(_default_retention_policy(scenario))

    try:
        return controller.executeSimulations()
    except Exception as exc:  # noqa: BLE001 -- report ANY batch-level failure with a specific message
        raise MonteCarloError(f"Monte Carlo batch execution failed: {exc}") from exc
