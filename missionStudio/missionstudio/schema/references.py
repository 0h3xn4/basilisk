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
Reference-integrity utilities for a :class:`~missionstudio.schema.scenario.Scenario`
-- "what refers to this spacecraft/ground station by name", used to back
two GMAT/FreeFlyer-style GUI behaviors neither this schema nor the GUI
layer has today:

* **Delete is refused** with a specific message listing every referencing
  item, instead of silently leaving a dangling name that only surfaces as
  a generic validation error much later (or not at all, if nothing ever
  re-validates). Before this module, ``gui.spacecraft_editor.
  SpacecraftListWidget._on_remove()``/``gui.ground_station_editor.
  GroundStationListWidget._on_remove()`` deleted unconditionally with NO
  reference check at all -- confirmed by reading both, this is a real,
  not hypothetical, gap.
* **Rename updates every reference** atomically (FreeFlyer's "rename
  symbol"), instead of leaving them pointing at a name that no longer
  exists.

Deliberately explicit, not a generic dataclass-field walker
-------------------------------------------------------------
Every reference site below is hand-listed, the same way
``Scenario.validate()`` already hand-lists every cross-reference check
(``phasing_keeping.chief_spacecraft in names``, ``dispersion.spacecraft in
names``, ``fsw_params['target_ground_station'] in gs_names``) rather than
reflecting over dataclass fields generically -- matching this schema's own
established style (explicit and easy to audit over generic and easy to
get subtly wrong), at the cost of needing a new entry here whenever a new
reference site is added elsewhere (e.g. a future ``Command`` kind that
targets a ground station). Kept in one place specifically so that's a
one-file change, the same discipline ``engine.monte_carlo``'s
``_QUANTITY_PATHS`` dict already documents for itself for the same reason.

``assignment`` commands are a deliberate, narrower exception: ``target``
is a dotted path STRING (``"sat-1.station_keeping.thrust_n"``), not a
clean dict key, so the reference is the string's first path segment --
see :func:`_command_references` for exactly how that's parsed, and its
v1 limitation (assignment targets are assumed spacecraft-scoped; nothing
else parses a dotted target yet).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .command import Command
    from .scenario import Scenario


@dataclass(frozen=True)
class Reference:
    """One place a resource's name is referenced from."""

    path: str  # human-readable location, e.g. "spacecraft[1] ('sat-2').phasing_keeping.chief_spacecraft"
    resource_kind: str  # "spacecraft" | "ground_station"
    name: str  # the name being referenced


class ReferenceError(ValueError):
    """Raised by :func:`rename_spacecraft`/:func:`rename_ground_station`
    when the requested rename itself is invalid (old name not found, new
    name collides) -- distinct from finding references TO a name, which
    never raises (see :func:`find_spacecraft_references`).
    """


def _command_references(commands: List["Command"], path_prefix: str) -> List[Reference]:
    """Recursively scans a command list (and every ``if``/``while``
    subtree) for spacecraft-name references. Ground-station references
    aren't scanned here -- no command kind in this project's current
    minimum set (:data:`schema.command.SUPPORTED_COMMAND_KINDS`) targets
    one; add a case here if/when one does.
    """
    refs: List[Reference] = []
    for i, command in enumerate(commands):
        label_suffix = f" ({command.label!r})" if command.label else ""
        path = f"{path_prefix}[{i}]{label_suffix}"

        if command.kind in ("maneuver", "propagate") and isinstance(command.params.get("spacecraft"), str):
            name = command.params["spacecraft"]
            if name:
                refs.append(Reference(path=f"{path}.params['spacecraft']", resource_kind="spacecraft", name=name))
        elif command.kind == "assignment" and isinstance(command.params.get("target"), str):
            # "sat-1.station_keeping.thrust_n" -- the first dotted segment
            # is the spacecraft this assignment targets. See module
            # docstring for why this is parsed rather than a clean key.
            target = command.params["target"]
            if "." in target:
                name = target.split(".", 1)[0]
                if name:
                    refs.append(Reference(path=f"{path}.params['target']", resource_kind="spacecraft", name=name))

        if command.kind in ("if", "while"):
            refs.extend(_command_references(command.children, f"{path}.children"))

    return refs


def find_spacecraft_references(scenario: "Scenario", name: str) -> List[Reference]:
    """Every place ``name`` is referenced from, EXCLUDING the
    ``SpacecraftConfig`` itself (i.e. this never reports a spacecraft as
    referencing its own name) -- an empty list means it's safe to delete.
    """
    refs: List[Reference] = []
    for i, sc in enumerate(scenario.spacecraft):
        if sc.phasing_keeping is not None and sc.phasing_keeping.chief_spacecraft == name:
            refs.append(Reference(
                path=f"spacecraft[{i}] ({sc.name!r}).phasing_keeping.chief_spacecraft",
                resource_kind="spacecraft", name=name,
            ))
    for i, dispersion in enumerate(scenario.monte_carlo.dispersions):
        if dispersion.spacecraft == name:
            refs.append(Reference(
                path=f"monte_carlo.dispersions[{i}]", resource_kind="spacecraft", name=name,
            ))
    refs.extend(r for r in _command_references(scenario.mission_sequence, "mission_sequence")
                if r.resource_kind == "spacecraft" and r.name == name)
    return refs


def find_ground_station_references(scenario: "Scenario", name: str) -> List[Reference]:
    """Every place ``name`` is referenced from -- an empty list means it's
    safe to delete.
    """
    refs: List[Reference] = []
    for i, sc in enumerate(scenario.spacecraft):
        if sc.fsw_mode == "locationPointing" and sc.fsw_params.get("target_ground_station") == name:
            refs.append(Reference(
                path=f"spacecraft[{i}] ({sc.name!r}).fsw_params['target_ground_station']",
                resource_kind="ground_station", name=name,
            ))
    return refs


def rename_spacecraft(scenario: "Scenario", old_name: str, new_name: str) -> int:
    """Renames a spacecraft AND updates every reference to it, atomically
    -- either the whole rename succeeds (including every reference), or
    nothing changes (raises :class:`ReferenceError` first). Returns the
    number of REFERENCES updated (not counting the ``SpacecraftConfig``
    itself, which is always exactly one more if this doesn't raise).
    """
    if not new_name:
        raise ReferenceError("new spacecraft name must not be empty")
    target = next((sc for sc in scenario.spacecraft if sc.name == old_name), None)
    if target is None:
        raise ReferenceError(f"no spacecraft named {old_name!r} in this scenario")
    if new_name != old_name and any(sc.name == new_name for sc in scenario.spacecraft):
        raise ReferenceError(f"a spacecraft named {new_name!r} already exists in this scenario")

    updated = 0
    for sc in scenario.spacecraft:
        if sc.phasing_keeping is not None and sc.phasing_keeping.chief_spacecraft == old_name:
            sc.phasing_keeping.chief_spacecraft = new_name
            updated += 1
    for dispersion in scenario.monte_carlo.dispersions:
        if dispersion.spacecraft == old_name:
            dispersion.spacecraft = new_name
            updated += 1
    updated += _rename_in_commands(scenario.mission_sequence, "spacecraft", old_name, new_name)

    target.name = new_name
    return updated


def rename_ground_station(scenario: "Scenario", old_name: str, new_name: str) -> int:
    """Same contract as :func:`rename_spacecraft`, for ground stations."""
    if not new_name:
        raise ReferenceError("new ground station name must not be empty")
    target = next((gs for gs in scenario.ground_stations if gs.name == old_name), None)
    if target is None:
        raise ReferenceError(f"no ground station named {old_name!r} in this scenario")
    if new_name != old_name and any(gs.name == new_name for gs in scenario.ground_stations):
        raise ReferenceError(f"a ground station named {new_name!r} already exists in this scenario")

    updated = 0
    for sc in scenario.spacecraft:
        if sc.fsw_mode == "locationPointing" and sc.fsw_params.get("target_ground_station") == old_name:
            sc.fsw_params["target_ground_station"] = new_name
            updated += 1

    target.name = new_name
    return updated


def _rename_in_commands(commands: List["Command"], resource_kind: str, old_name: str, new_name: str) -> int:
    updated = 0
    for command in commands:
        if resource_kind == "spacecraft":
            if command.kind in ("maneuver", "propagate") and command.params.get("spacecraft") == old_name:
                command.params["spacecraft"] = new_name
                updated += 1
            elif command.kind == "assignment" and isinstance(command.params.get("target"), str):
                target = command.params["target"]
                if "." in target and target.split(".", 1)[0] == old_name:
                    command.params["target"] = new_name + target[len(old_name):]
                    updated += 1
        if command.kind in ("if", "while"):
            updated += _rename_in_commands(command.children, resource_kind, old_name, new_name)
    return updated
