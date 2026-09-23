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
Phase 6 (Mission Sequence), part 2: :class:`MissionEngine` walks a
:class:`~missionstudio.schema.Scenario`'s ``mission_sequence`` (built by
``schema/command.py``, Phase 6 part 1) against a real
:class:`~missionstudio.engine.service.SimulationService`, executing each
:class:`~missionstudio.schema.command.Command` in order.

Every Basilisk call sequence below is verified directly against this
checkout's own source or an actually-running official example, not
written from memory:

* Repeated ``ConfigureStopTime()``/``ExecuteSimulation()`` pairs, with
  ``ConfigureStopTime()`` taking an ABSOLUTE cumulative simulation time
  (not a delta) -- ``examples/scenarioOrbitManeuver.py``'s own comment:
  "the total simulation time must be provided, not just the next
  incremental simulation time". ``ExecuteSimulation()`` always resumes
  from ``TotalSim.NextTaskTime``/``CurrentNanos`` rather than restarting
  (see ``SimulationBaseClass.ExecuteSimulation()``'s ``CheckStopCondition()``
  loop) -- already exercised by this project's own, already-passing
  ``engine.service.SimulationService.run_live()`` and
  ``tests/test_service_run_live.py``.
* Impulsive maneuvers: ``scObject.dynManager.getStateObject(scObject.hub.nameOfHubPosition
  /nameOfHubVelocity)`` fetched once, ``simHelpers.EigenVector3d2np(velRef.getState())``
  to read the current velocity as a numpy array, plain numpy arithmetic to
  compute the new velocity, ``velRef.setState(newVelocityNumpyArray)`` to
  apply it -- ``setState()`` accepts a raw numpy array directly (SWIG's
  own typemap converts it), no explicit Eigen-conversion call needed on
  the way in -- all copied from ``examples/scenarioOrbitManeuver.py``'s
  own two maneuver applications, not guessed.
* Orbital-event stop conditions (periapsis/apoapsis): Basilisk's own
  native event mechanism, ``SimBaseClass.createNewEvent(eventName,
  eventRate, eventActive, conditionFunction=..., terminal=True)`` --
  copied from ``examples/scenarioDragDeorbit.py``'s own
  "Event to terminate the simulation" block (its ``conditionFunction``
  reads the spacecraft's OWN output message directly via
  ``scStateOutMsg.read()``, not a subscribed reader -- also copied from
  there). ``ExecuteSimulation()`` checks every active event on every task
  tick where ``eventRate`` divides evenly (see
  ``EventHandlerClass.shouldBeChecked()``/``ExecuteSimulation()``'s own
  event-checking loop in ``SimulationBaseClass.py``) and sets
  ``scSim.terminate = True`` when a ``terminal=True`` event fires,
  breaking ``ExecuteSimulation()``'s loop early -- no extra plumbing
  needed beyond creating the event before the ``ExecuteSimulation()``
  call that should be interrupted by it.

``assignment``/``report``/``if``/``while``/``script_block`` have no
Basilisk-API precedent to verify against -- they are this project's own
design (see each one's own docstring below for the reasoning), scoped as
narrowly as the Phase 6 part 1 schema module's own docstring describes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..schema.command import Command
from ..schema.scenario import Scenario
from .orbit_maintenance import _rtn_basis, _vnb_basis
from .results import ResultSet
from .service import SimulationService

# A `while` command's condition is user-authored and can easily be wrong
# (e.g. a condition that never becomes false because the mission never
# updates the quantity it checks) -- this caps how many times ANY single
# `while` command's body can run before MissionEngine gives up with a
# clear error, rather than hanging the process indefinitely. Generous for
# any real mission (a Command Summary with tens of thousands of report
# rows would already be unusable), tight enough to fail fast on a
# genuinely infinite loop.
_WHILE_MAX_ITERATIONS = 10_000

# propagate.stop_condition == "event" has no natural finite bound (unlike
# "duration"/"epoch") -- an orbit that never reaches the requested event
# (e.g. a hyperbolic escape trajectory asked to find a periapsis it will
# never return to) would otherwise run ExecuteSimulation() forever. This
# multiplies the scenario's own duration_days as a generous safety cap;
# MissionEngineError is raised (not a silent partial result) if the event
# never fires within it.
_EVENT_PROPAGATE_SAFETY_MULTIPLIER = 10.0  # [-]

# assignment.target's second dotted segment (the "controller" a mission
# sequence can vary mid-run) -> the live engine.orbit_maintenance
# controller attribute on _SpacecraftHandle that resolves it. Hand-listed
# (not reflection-based), matching this project's established style for
# every other name-string-to-live-object mapping (schema.references'
# reference sites, engine.fsw's fsw_mode dispatch).
_ASSIGNMENT_CONTROLLERS = {
    "station_keeping": "station_keeping_controller",
    "phasing_keeping": "phasing_keeping_controller",
    "constant_thrust": "constant_thrust_controller",
}

# Third dotted segment (the parameter name) -> the controller's actual
# Python attribute. Deliberately a small, explicit whitelist of the
# knobs that are physically meaningful to vary mid-mission (thrust
# level, specific impulse), not a generic getattr/setattr passthrough --
# matches this schema's existing preference for hand-listed, validated
# surfaces over reflection (see schema/command.py's own docstring on why
# this project avoids reflection-based (de)serialization).
_ASSIGNMENT_ATTRIBUTES = {"thrust_n": "thrustN", "isp_s": "ispS"}


class MissionEngineError(Exception):
    """Raised when a mission_sequence command fails to build or execute --
    always names the specific command (its path within mission_sequence,
    e.g. ``"mission_sequence[2].children[0]"``, and its kind) that failed,
    never a bare exception from deep inside Basilisk or Python's own
    ``eval``/``exec``.
    """


@dataclass
class ReportEntry:
    """One ``report`` command's result: a snapshot (not a time history --
    see :class:`MissionEngine`'s ``_run_report`` docstring) of the
    requested series' most recent values at the mission time this report
    command ran.
    """

    label: Optional[str]
    t_s: float  # [s] elapsed mission time when this report ran
    values: Dict[str, np.ndarray]


@dataclass
class CommandSummary:
    """Everything a mission_sequence run produced beyond the raw
    :class:`~missionstudio.engine.results.ResultSet`: one
    :class:`ReportEntry` per executed ``report`` command, in execution
    order (so a ``report`` inside an ``if``/``while`` only appears when
    that branch/iteration actually ran), plus a count of every command
    actually executed (a ``while`` body run 5 times counts each of those
    5 runs separately, matching how many times each command really
    affected the simulation).
    """

    reports: List[ReportEntry] = field(default_factory=list)
    commands_executed: int = 0


class MissionEngine:
    """Walks ``scenario.mission_sequence`` against a
    :class:`~missionstudio.engine.service.SimulationService`, one
    :class:`~missionstudio.schema.command.Command` at a time, in order.

    Construct with an already-validated ``scenario`` (``scenario.validate()``
    -- or, for collecting every problem at once,
    ``schema.validation.validate_all()`` -- is assumed to have already
    been called, exactly the same precondition :class:`SimulationService`
    itself has). Pass an existing ``service`` to reuse one that was
    already built (e.g. with Monte Carlo dispersions already applied, see
    ``engine/monte_carlo.py``'s ``build(initialize=False)`` pattern) --
    otherwise a fresh one is created and built automatically on
    :meth:`run`.
    """

    def __init__(self, scenario: Scenario, service: Optional[SimulationService] = None):
        self.scenario = scenario
        self.service = service or SimulationService(scenario)
        self._event_counter = 0
        # The cumulative REQUESTED mission time [ns] each propagate command's
        # absolute ConfigureStopTime() target is built from -- deliberately
        # NOT read back from scSim.TotalSim.CurrentNanos after each call.
        # Confirmed directly against sim_model.cpp: CurrentNanos is set to
        # NextTaskTime, i.e. it snaps DOWN to the last task-grid point <=
        # the requested stop time (SimBaseClass.CheckStopCondition() keeps
        # stepping only "while NextTaskTime <= StopTime"), so a requested
        # duration that isn't an exact multiple of dynamics_task_rate_s
        # loses up to one tick every time. Basing each new segment's target
        # on CurrentNanos would silently COMPOUND that loss across segments
        # (three chained propagate commands ending up short of where one
        # equivalent-duration propagate would land) -- caught by this
        # project's own test_multiple_propagate_segments_accumulate_not_restart
        # once actually run against a real Basilisk build. propagate's
        # "event" stop condition is the one exception (see
        # _run_propagate_event): there is no requested target to track, so
        # it re-syncs this to the ACTUAL (grid-snapped) firing time instead.
        self._elapsed_ns = 0

    def run(self) -> Tuple[ResultSet, CommandSummary]:
        """Builds (if not already built) the underlying
        :class:`SimulationService` and executes ``scenario.mission_sequence``
        in order, returning ``(result, summary)``. An empty
        ``mission_sequence`` (the default -- see ``schema/command.py``'s
        own docstring on why this is additive/backward-compatible)
        executes zero commands, so the returned :class:`ResultSet` only
        has whatever ``InitializeSimulation()`` itself records at t=0 --
        callers that want the pre-Phase-6 "just propagate for
        ``sim_settings.duration_days``" behavior should keep using
        :meth:`SimulationService.run` directly, not this class.
        """
        if self.service.scSim is None:
            self.service.build()
        summary = CommandSummary()
        self._run_commands(self.scenario.mission_sequence, summary, "mission_sequence")
        return self.service._extract_results(), summary

    # -- command tree walking ------------------------------------------------

    def _run_commands(self, commands: List[Command], summary: CommandSummary, path: str) -> None:
        for i, command in enumerate(commands):
            self._run_command(command, summary, f"{path}[{i}]")

    def _run_command(self, command: Command, summary: CommandSummary, path: str) -> None:
        handler = {
            "propagate": self._run_propagate,
            "maneuver": self._run_maneuver,
            "assignment": self._run_assignment,
            "report": self._run_report,
            "if": self._run_if,
            "while": self._run_while,
            "script_block": self._run_script_block,
        }.get(command.kind)
        if handler is None:  # unreachable if Command.validate() passed
            raise MissionEngineError(f"{path}: unknown command kind {command.kind!r}")
        summary.commands_executed += 1
        try:
            handler(command, summary, path)
        except MissionEngineError:
            raise
        except Exception as exc:
            raise MissionEngineError(f"{path} ({command.kind}): {exc}") from exc

    # -- propagate -------------------------------------------------------------

    def _run_propagate(self, command: Command, summary: CommandSummary, path: str) -> None:
        from Basilisk.utilities import macros

        stop_condition = command.params.get("stop_condition", "duration")
        if stop_condition == "duration":
            target_ns = self._elapsed_ns + macros.sec2nano(command.params["duration_days"] * 86400.0)
            self.service.scSim.ConfigureStopTime(target_ns)
            self.service.scSim.ExecuteSimulation()
            self._elapsed_ns = target_ns
        elif stop_condition == "epoch":
            stop_epoch_utc = command.params["stop_epoch_utc"]
            stop_epoch = datetime.fromisoformat(stop_epoch_utc)
            start_epoch = datetime.fromisoformat(self.scenario.epoch_utc)
            target_ns = macros.sec2nano((stop_epoch - start_epoch).total_seconds())
            if target_ns <= self._elapsed_ns:
                raise MissionEngineError(
                    f"{path}: propagate.stop_epoch_utc {stop_epoch_utc!r} is not after the current mission "
                    "time -- stop_epoch_utc is an absolute epoch, not an offset"
                )
            self.service.scSim.ConfigureStopTime(target_ns)
            self.service.scSim.ExecuteSimulation()
            self._elapsed_ns = target_ns
        else:  # "event" -- validated by Command.validate()
            self._run_propagate_event(command, path)

    def _run_propagate_event(self, command: Command, path: str) -> None:
        """``propagate.stop_condition == "event"``: runs until the named
        spacecraft crosses periapsis or apoapsis, detected as a sign
        change in radial velocity (``dot(r, v) / |r|``) -- exactly zero at
        periapsis/apoapsis for any Keplerian (or near-Keplerian) orbit,
        going negative-to-positive at periapsis (distance stops
        decreasing, starts increasing) and positive-to-negative at
        apoapsis. Chosen over reconstructing true anomaly via
        ``orbitalMotion.rv2elem`` every check: no extra per-check osculating
        -element computation, and no wrap-around handling needed at the
        0/2*pi true-anomaly boundary.
        """
        from Basilisk.utilities import macros

        spacecraft_name = command.params["spacecraft"]
        event_kind = command.params["event_kind"]
        handle = self.service.spacecraft_handles.get(spacecraft_name)
        if handle is None:
            raise MissionEngineError(
                f"{path}: propagate stop_condition='event' names unknown spacecraft {spacecraft_name!r}"
            )

        # A fresh dict per call (not an instance attribute) so nested/looped
        # invocations of the same command node (e.g. inside a `while`) each
        # get their own independent "have we seen a first sample yet" state,
        # and a per-invocation-unique event name (self._event_counter) so
        # Basilisk's createNewEvent() (which silently no-ops on a reused
        # name -- see SimulationBaseClass.py -- rather than replacing the
        # existing event) never accidentally reuses a previous invocation's
        # already-fired, now-permanently-inactive event.
        detector_state: Dict[str, Optional[float]] = {"prev_radial_velocity": None}

        def condition(_parent_sim, handle=handle, event_kind=event_kind, detector_state=detector_state) -> bool:
            payload = handle.sc_object.scStateOutMsg.read()
            r_bn_n = np.array(payload.r_BN_N)
            v_bn_n = np.array(payload.v_BN_N)
            radial_velocity = float(np.dot(r_bn_n, v_bn_n) / np.linalg.norm(r_bn_n))  # [m/s]
            previous = detector_state["prev_radial_velocity"]
            detector_state["prev_radial_velocity"] = radial_velocity
            if previous is None:
                return False
            if event_kind == "periapsis":
                return previous < 0.0 <= radial_velocity
            return previous > 0.0 >= radial_velocity  # "apoapsis"

        self._event_counter += 1
        event_name = f"missionEngine_event_{self._event_counter}"
        self.service.scSim.createNewEvent(
            event_name,
            macros.sec2nano(self.scenario.sim_settings.dynamics_task_rate_s),
            True,
            conditionFunction=condition,
            terminal=True,
        )

        cap_days = max(self.scenario.sim_settings.duration_days, 1.0) * _EVENT_PROPAGATE_SAFETY_MULTIPLIER  # [d]
        cap_ns = self._elapsed_ns + macros.sec2nano(cap_days * 86400.0)
        self.service.scSim.terminate = False
        self.service.scSim.ConfigureStopTime(cap_ns)
        self.service.scSim.ExecuteSimulation()

        if not self.service.scSim.terminate:
            raise MissionEngineError(
                f"{path}: propagate stop_condition='event' ({event_kind}) for spacecraft {spacecraft_name!r} "
                f"did not occur within the {cap_days:.1f}-day safety cap"
            )
        self.service.scSim.terminate = False  # so a later propagate command's ExecuteSimulation() isn't cut short
        # Unlike duration/epoch, there is no "requested" target here -- the
        # event fired at whatever (task-grid-snapped) instant Basilisk
        # actually detected it, so that IS the new baseline, not something
        # to track separately.
        self._elapsed_ns = self.service.scSim.TotalSim.CurrentNanos

    # -- maneuver ----------------------------------------------------------

    def _run_maneuver(self, command: Command, summary: CommandSummary, path: str) -> None:
        from Basilisk.utilities import simHelpers

        spacecraft_name = command.params["spacecraft"]
        handle = self.service.spacecraft_handles.get(spacecraft_name)
        if handle is None:
            raise MissionEngineError(f"{path}: maneuver names unknown spacecraft {spacecraft_name!r}")

        delta_v_m_s = np.array(command.params["delta_v_m_s"], dtype=float)  # [m/s]
        frame = command.params.get("frame", "inertial")

        pos_ref = handle.sc_object.dynManager.getStateObject(handle.sc_object.hub.nameOfHubPosition)
        vel_ref = handle.sc_object.dynManager.getStateObject(handle.sc_object.hub.nameOfHubVelocity)
        r_bn_n = simHelpers.EigenVector3d2np(pos_ref.getState())  # [m]
        v_bn_n = simHelpers.EigenVector3d2np(vel_ref.getState())  # [m/s]

        if frame == "inertial":
            delta_v_n = delta_v_m_s
        else:
            basis = _vnb_basis if frame == "vnb" else _rtn_basis  # "rtn" -- validated by Command.validate()
            axis1, axis2, axis3 = basis(r_bn_n, v_bn_n)
            delta_v_n = delta_v_m_s[0] * axis1 + delta_v_m_s[1] * axis2 + delta_v_m_s[2] * axis3

        vel_ref.setState(v_bn_n + delta_v_n)

    # -- assignment ----------------------------------------------------------

    def _run_assignment(self, command: Command, summary: CommandSummary, path: str) -> None:
        """Varies a live controller parameter mid-mission (e.g. reducing
        station-keeping thrust for a later mission phase) -- this
        project's own design, scoped to the specific knobs listed in
        ``_ASSIGNMENT_ATTRIBUTES`` (see that constant's comment for why
        this is a hand-listed whitelist rather than generic attribute
        access). ``assignment.target`` is ``"<spacecraft>.<controller>.<parameter>"``,
        e.g. ``"sat-1.station_keeping.thrust_n"``.
        """
        target = command.params["target"]
        value = command.params["value"]
        parts = target.split(".")
        if len(parts) != 3:
            raise MissionEngineError(
                f"{path}: assignment.target {target!r} must have exactly 3 dotted segments "
                "('<spacecraft>.<controller>.<parameter>', e.g. 'sat-1.station_keeping.thrust_n')"
            )
        spacecraft_name, controller_key, parameter_key = parts

        handle = self.service.spacecraft_handles.get(spacecraft_name)
        if handle is None:
            raise MissionEngineError(f"{path}: assignment.target names unknown spacecraft {spacecraft_name!r}")

        controller_attr = _ASSIGNMENT_CONTROLLERS.get(controller_key)
        if controller_attr is None:
            raise MissionEngineError(
                f"{path}: assignment.target names controller {controller_key!r}, must be one of "
                f"{sorted(_ASSIGNMENT_CONTROLLERS)}"
            )
        controller = getattr(handle, controller_attr)
        if controller is None:
            raise MissionEngineError(
                f"{path}: spacecraft {spacecraft_name!r} has no {controller_key} configured (assignment.target "
                f"{target!r})"
            )

        live_attr = _ASSIGNMENT_ATTRIBUTES.get(parameter_key)
        if live_attr is None:
            raise MissionEngineError(
                f"{path}: assignment.target names parameter {parameter_key!r}, must be one of "
                f"{sorted(_ASSIGNMENT_ATTRIBUTES)}"
            )
        setattr(controller, live_attr, float(value))

    # -- report ----------------------------------------------------------------

    def _run_report(self, command: Command, summary: CommandSummary, path: str) -> None:
        """Snapshots the CURRENT (most recently recorded) value of each
        requested series -- deliberately not the whole time history
        ``ResultSet`` already carries (that's always available from
        :meth:`run`'s own return value); a report command's job is to
        capture "what were these values at the moment this ran", matching
        GMAT's ``Report`` command semantics, the closest real-world
        analogue for this command kind.
        """
        from Basilisk.utilities import macros

        result = self.service._extract_results()
        requested = command.params.get("series", [])
        names = requested if requested else sorted(result.series)
        missing = [name for name in names if name not in result.series]
        if missing:
            raise MissionEngineError(f"{path}: report.series names not found in the result set: {missing}")

        snapshot = {name: np.array(result.series[name].data[-1]) for name in names}
        t_s = self.service.scSim.TotalSim.CurrentNanos * macros.NANO2SEC
        summary.reports.append(ReportEntry(label=command.label, t_s=t_s, values=snapshot))

    # -- if / while --------------------------------------------------------

    def _run_if(self, command: Command, summary: CommandSummary, path: str) -> None:
        if self._evaluate_condition(command.params["condition"], path):
            self._run_commands(command.children, summary, f"{path}.children")

    def _run_while(self, command: Command, summary: CommandSummary, path: str) -> None:
        iterations = 0
        while self._evaluate_condition(command.params["condition"], path):
            self._run_commands(command.children, summary, f"{path}.children[{iterations}]")
            iterations += 1
            if iterations > _WHILE_MAX_ITERATIONS:
                raise MissionEngineError(
                    f"{path}: while loop exceeded {_WHILE_MAX_ITERATIONS} iterations -- its condition never "
                    "became false (a likely infinite loop, not a slow one)"
                )

    def _evaluate_condition(self, expression: str, path: str) -> bool:
        try:
            return bool(eval(expression, {"__builtins__": {}}, self._script_context()))
        except MissionEngineError:
            raise
        except Exception as exc:
            raise MissionEngineError(f"{path}: condition {expression!r} failed to evaluate: {exc}") from exc

    def _script_context(self) -> Dict[str, Any]:
        """Read-only-by-convention namespace exposed to ``if``/``while``
        conditions and ``script_block`` code: ``t_s`` (elapsed mission
        time [s]) and ``spacecraft`` (``{name: {"r_BN_N", "v_BN_N",
        "altitude_m", "mass_kg"}}`` for every spacecraft, read directly off
        each one's live ``scStateOutMsg``/``hub.mHub`` -- this project's
        own design, not a Basilisk API (there is no Basilisk concept of a
        user-scriptable mission condition); intentionally narrow rather
        than exposing every possible quantity, matching this schema's
        general preference for a small, explicit, well-documented surface
        over a generic passthrough.
        """
        from Basilisk.utilities import macros

        central_body_name = self.scenario.gravity.central_body
        central_body_radius_m = self.service.grav_factory.gravBodies[central_body_name].radEquator  # [m]

        spacecraft: Dict[str, Dict[str, Any]] = {}
        for name, handle in self.service.spacecraft_handles.items():
            payload = handle.sc_object.scStateOutMsg.read()
            r_bn_n = np.array(payload.r_BN_N)
            v_bn_n = np.array(payload.v_BN_N)
            spacecraft[name] = {
                "r_BN_N": r_bn_n,
                "v_BN_N": v_bn_n,
                "altitude_m": float(np.linalg.norm(r_bn_n)) - central_body_radius_m,
                "mass_kg": handle.sc_object.hub.mHub,
            }

        return {
            "t_s": self.service.scSim.TotalSim.CurrentNanos * macros.NANO2SEC,
            "duration_days": self.scenario.sim_settings.duration_days,
            "spacecraft": spacecraft,
        }

    # -- script_block --------------------------------------------------------

    def _run_script_block(self, command: Command, summary: CommandSummary, path: str) -> None:
        """Executes ``script_block.code`` as full, unrestricted Python
        (``exec`` with real builtins, not a sandbox) against
        :meth:`_script_context` plus ``service``/``scenario``/``summary``.

        This is a deliberate trust boundary, not an oversight: a
        ``script_block`` command is authored by whoever writes the
        mission sequence, exactly like a GMAT/FreeFlyer script command
        (or, for that matter, the Python scenario scripts this whole
        checkout's ``examples/`` directory already consists of) -- only
        run a scenario file you trust, the same rule that already applies
        to running any Python script at all.
        """
        context: Dict[str, Any] = dict(self._script_context())
        context["service"] = self.service
        context["scenario"] = self.scenario
        context["summary"] = summary
        try:
            exec(command.params["code"], {"__builtins__": __builtins__}, context)
        except Exception as exc:
            raise MissionEngineError(f"{path}: script_block raised {type(exc).__name__}: {exc}") from exc
