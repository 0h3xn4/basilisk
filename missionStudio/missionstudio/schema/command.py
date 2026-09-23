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
:class:`Command` -- the "Mission Sequence" half of a :class:`Scenario`,
alongside the resource fields (``gravity``, ``spacecraft``,
``ground_stations``, ...) that already existed before this module: a
scenario's ``mission_sequence`` is an ORDERED list of :class:`Command`,
walked in order by ``engine.mission_engine`` (not yet written -- this
module is the GUI/Basilisk-independent data model only, same split
``schema/scenario.py`` already uses).

Inspired by GMAT's Resources/Mission-Sequence split and FreeFlyer's
Objects/Mission-Sequence split, but deliberately NOT a port of either
tool's command set or object model -- see this project's own design
discussion for why: Basilisk's continuous feedback controllers
(``engine.orbit_maintenance``), message/recorder architecture, and native
event mechanism (``SimulationBaseClass.EventHandlerClass``) are each, in
their own area, a better fit than copying GMAT/FreeFlyer's shape wholesale
would be -- this schema only borrows the ORGANIZING idea (resources vs.
time-ordered sequence), not the object model underneath it.

One envelope dataclass, not one Python class per command kind
-----------------------------------------------------------------
:class:`Command` has a ``kind: str`` discriminator plus a loosely-typed
``params: dict``, exactly the same shape ``SpacecraftConfig`` already uses
for ``SensorConfig``/``ActuatorConfig`` (``kind`` + ``params``) and for
``fsw_params`` (mode-specific keys in one dict rather than one dataclass
per FSW mode) -- chosen for the same reason those were: command kinds need
very different parameter shapes, and a dataclass-per-kind would also need
a discriminated-union (de)serialization mechanism this schema doesn't have
anywhere else. ``Command.validate()`` is where each kind's specific shape
is actually enforced, matching how ``engine/fsw.py``'s per-mode builders
are where ``fsw_params``' shape is enforced today.

Minimum command set (per this project's current scope decision)
-------------------------------------------------------------------
``propagate``, ``maneuver`` (impulsive delta-V), ``assignment``,
``report``, ``if``, ``while``, ``script_block``. Targeting/optimization
commands (GMAT's ``Target``/``Vary``/``Optimize``) are explicitly NOT
included -- interface design for those is future work, not implemented
here.

Collecting validation
----------------------
Unlike ``schema.scenario``'s existing ``validate()`` methods (raise on the
FIRST problem found, via ``_require`` -- preserved exactly as-is; nothing
in this module changes that), :meth:`Command.validate` returns a LIST of
every problem found in this command and its ``children`` subtree, each
prefixed with an item path -- the "report all errors at once, with item
paths" behavior requested for the mission-sequence layer specifically.
Cross-reference checks (does a ``"spacecraft"`` param actually name a real
spacecraft in this scenario?) are NOT done here -- exactly like
``DispersionConfig.validate()``/``PhasingKeepingConfig.validate()``
already don't check their own cross-references either, leaving that to
the scenario-level pass (see ``schema.validation.validate_all``) that has
the full spacecraft/ground-station name list to check against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

SUPPORTED_COMMAND_KINDS = ("propagate", "maneuver", "assignment", "report", "if", "while", "script_block")

# propagate.stop_condition
SUPPORTED_STOP_CONDITIONS = ("duration", "epoch", "event")
# propagate.stop_condition == "event": which orbital event to stop at.
# Deliberately just these two for v1 -- the two orbital events that are
# unambiguous from osculating elements alone (true anomaly wrapping through
# 0 or pi), matching "at least one orbital-event condition if feasible"
# from this feature's own scope. Both are meant to be implemented on top of
# Basilisk's OWN event mechanism (SimulationBaseClass.EventHandlerClass's
# conditionFunction/actionFunction/terminal=True -- verified against this
# checkout's source during planning, see the project design discussion)
# rather than a hand-rolled polling loop -- that's engine.mission_engine's
# job, not this module's; this module only needs to capture enough
# information for that engine code to do so later.
SUPPORTED_EVENT_KINDS = ("periapsis", "apoapsis")

# maneuver.frame -- "inertial" applies delta_v_m_s directly in the N frame
# (matching Basilisk's own examples/scenarioOrbitManeuver.py exactly);
# "vnb"/"rtn" reuse engine.orbit_maintenance's ALREADY-WRITTEN, ALREADY
# -TESTED _vnb_basis/_rtn_basis pure-numpy frame helpers (built for
# ConstantThrustConfig) to rotate delta_v_m_s into the inertial frame
# before applying it -- engine.mission_engine's job, not this module's.
SUPPORTED_MANEUVER_FRAMES = ("inertial", "vnb", "rtn")


def _collect(errors: List[str], path: str, condition: bool, message: str) -> None:
    if not condition:
        errors.append(f"{path}: {message}")


@dataclass
class Command:
    """One node in a scenario's ``mission_sequence`` tree.

    Args:
        kind: one of :data:`SUPPORTED_COMMAND_KINDS`.
        label: optional user-facing name (e.g. ``"Prop to Periapsis"``
            instead of an auto-numbered ``"Propagate3"``) -- purely
            cosmetic, never referenced by other commands/resources.
        params: kind-specific fields -- see :meth:`validate` for exactly
            what each kind requires/accepts.
        children: nested commands, meaningful ONLY for ``kind in
            ("if", "while")`` (the compound/control-block kinds) -- empty
            for every other kind. A plain ``list[Command]``, not a
            separate type, so the same tree-walking code (validation,
            reference-scanning, execution) recurses uniformly regardless
            of nesting depth.
    """

    kind: str
    label: Optional[str] = None
    params: dict = field(default_factory=dict)
    children: List["Command"] = field(default_factory=list)

    def validate(self, path: str) -> List[str]:
        """Returns every problem found in this command (and, for
        ``if``/``while``, its ``children`` subtree), each a complete
        ``f"{item_path}: {message}"`` string -- never raises, so a caller
        walking a whole ``mission_sequence`` can collect everything wrong
        with it in one pass rather than fixing one error at a time.
        """
        errors: List[str] = []
        label_suffix = f" ({self.label!r})" if self.label else ""
        full_path = f"{path}{label_suffix}"

        if self.kind not in SUPPORTED_COMMAND_KINDS:
            errors.append(f"{full_path}: kind {self.kind!r} must be one of {SUPPORTED_COMMAND_KINDS}")
            return errors  # nothing else here is checkable without a known kind

        if self.kind == "propagate":
            self._validate_propagate(full_path, errors)
        elif self.kind == "maneuver":
            self._validate_maneuver(full_path, errors)
        elif self.kind == "assignment":
            self._validate_assignment(full_path, errors)
        elif self.kind == "report":
            self._validate_report(full_path, errors)
        elif self.kind in ("if", "while"):
            self._validate_conditional(full_path, errors)
        elif self.kind == "script_block":
            self._validate_script_block(full_path, errors)

        if self.kind not in ("if", "while"):
            _collect(errors, full_path, not self.children,
                      f"kind {self.kind!r} does not accept children (only 'if'/'while' do)")
        else:
            for i, child in enumerate(self.children):
                errors.extend(child.validate(f"{full_path}.children[{i}]"))

        return errors

    def _validate_propagate(self, path: str, errors: List[str]) -> None:
        stop_condition = self.params.get("stop_condition", "duration")
        _collect(errors, path, stop_condition in SUPPORTED_STOP_CONDITIONS,
                  f"propagate.stop_condition {stop_condition!r} must be one of {SUPPORTED_STOP_CONDITIONS}")
        if stop_condition == "duration":
            duration_days = self.params.get("duration_days")
            _collect(errors, path, isinstance(duration_days, (int, float)) and duration_days > 0,
                      "propagate.duration_days must be a number > 0 when stop_condition is 'duration'")
        elif stop_condition == "epoch":
            stop_epoch_utc = self.params.get("stop_epoch_utc")
            if not isinstance(stop_epoch_utc, str):
                errors.append(f"{path}: propagate.stop_epoch_utc must be a string when stop_condition is 'epoch'")
            else:
                try:
                    datetime.fromisoformat(stop_epoch_utc)
                except ValueError:
                    errors.append(f"{path}: propagate.stop_epoch_utc {stop_epoch_utc!r} is not a valid ISO 8601 "
                                    "datetime")
        elif stop_condition == "event":
            event_kind = self.params.get("event_kind")
            _collect(errors, path, event_kind in SUPPORTED_EVENT_KINDS,
                      f"propagate.event_kind {event_kind!r} must be one of {SUPPORTED_EVENT_KINDS} when "
                      "stop_condition is 'event'")
            spacecraft = self.params.get("spacecraft")
            _collect(errors, path, isinstance(spacecraft, str) and bool(spacecraft),
                      "propagate.spacecraft must name the spacecraft this event is evaluated against when "
                      "stop_condition is 'event'")

    def _validate_maneuver(self, path: str, errors: List[str]) -> None:
        spacecraft = self.params.get("spacecraft")
        _collect(errors, path, isinstance(spacecraft, str) and bool(spacecraft),
                  "maneuver.spacecraft must be a non-empty spacecraft name")
        delta_v_m_s = self.params.get("delta_v_m_s")
        _collect(errors, path, isinstance(delta_v_m_s, list) and len(delta_v_m_s) == 3
                  and all(isinstance(v, (int, float)) for v in delta_v_m_s),
                  "maneuver.delta_v_m_s must be a 3-element [x, y, z] list of numbers [m/s]")
        frame = self.params.get("frame", "inertial")
        _collect(errors, path, frame in SUPPORTED_MANEUVER_FRAMES,
                  f"maneuver.frame {frame!r} must be one of {SUPPORTED_MANEUVER_FRAMES}")

    def _validate_assignment(self, path: str, errors: List[str]) -> None:
        target = self.params.get("target")
        _collect(errors, path, isinstance(target, str) and "." in target,
                  "assignment.target must be a dotted path string, e.g. 'sat-1.station_keeping.thrust_n'")
        _collect(errors, path, "value" in self.params, "assignment.value is required")

    def _validate_report(self, path: str, errors: List[str]) -> None:
        series = self.params.get("series", [])
        _collect(errors, path, isinstance(series, list) and all(isinstance(s, str) for s in series),
                  "report.series must be a list of series-name strings (empty list means 'snapshot everything')")

    def _validate_conditional(self, path: str, errors: List[str]) -> None:
        condition = self.params.get("condition")
        _collect(errors, path, isinstance(condition, str) and bool(condition.strip()),
                  f"{self.kind}.condition must be a non-empty expression string")

    def _validate_script_block(self, path: str, errors: List[str]) -> None:
        code = self.params.get("code")
        _collect(errors, path, isinstance(code, str) and bool(code.strip()),
                  "script_block.code must be a non-empty string")

    # -- (de)serialization -------------------------------------------------
    # to_dict() needs no custom implementation: Command is a plain
    # dataclass with only dataclass/dict/list/scalar fields, so
    # dataclasses.asdict() (already how Scenario.to_dict() works) recurses
    # through `children` correctly with zero extra code. from_dict() DOES
    # need one, matching every other nested dataclass in
    # Scenario.from_dict() -- plain dict->dataclass reconstruction isn't
    # automatic in either direction for a self-referential type.
    @staticmethod
    def from_dict(data: dict) -> "Command":
        return Command(
            kind=data["kind"],
            label=data.get("label"),
            params=dict(data.get("params", {})),
            children=[Command.from_dict(c) for c in data.get("children", [])],
        )
