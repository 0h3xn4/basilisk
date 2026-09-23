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
:func:`validate_all` -- a scenario-wide validation pass that reports EVERY
problem it finds in one call, with item paths, rather than stopping at the
first one.

Honest about what's actually collecting vs. what isn't
-----------------------------------------------------------
``Scenario.validate()`` (``schema/scenario.py``) and every resource
dataclass's own ``.validate()`` are UNCHANGED by this module -- still
raise-fast on the first problem via ``_require()``, exactly as before this
feature existed, preserving current behavior exactly (nothing calling
``Scenario.validate()``/``.save()``/``load_scenario()`` today sees any
different behavior). Rewriting ~15 existing raise-fast validators into
collecting ones would be a much larger, riskier change than this feature
needs, so this module does NOT attempt it. Concretely, that means
:func:`validate_all`'s output has two different granularities:

* **Resources** (gravity, spacecraft, ground stations, Monte Carlo, ...):
  AT MOST ONE message -- whatever ``scenario.validate()`` raises first, if
  anything. Fixing it may reveal another one on the next call, same as
  today.
* **Mission sequence** (``scenario.mission_sequence``): EVERY problem in
  EVERY command, each with its own item path -- ``Command.validate()``
  (``schema/command.py``) was written collecting from the start, and this
  function also collects every dangling spacecraft/ground-station
  reference across the whole sequence, not just the first one.

This asymmetry is deliberate and stated here rather than hidden -- true
"every resource AND every command error, all at once" would require
retrofitting the resource layer, which is out of scope for this change
unless separately requested.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from .scenario import ScenarioValidationError

if TYPE_CHECKING:
    from .scenario import Scenario


def validate_all(scenario: "Scenario") -> List[str]:
    """Returns every problem found, as complete ``f"{path}: {message}"``
    strings -- an empty list means the scenario is fully valid. Never
    raises.
    """
    errors: List[str] = []

    try:
        scenario.validate()
    except ScenarioValidationError as exc:
        errors.append(str(exc))

    spacecraft_names = {sc.name for sc in scenario.spacecraft}
    ground_station_names = {gs.name for gs in scenario.ground_stations}

    for i, command in enumerate(scenario.mission_sequence):
        errors.extend(command.validate(f"mission_sequence[{i}]"))

    errors.extend(_dangling_command_references(scenario, spacecraft_names, ground_station_names))

    return errors


def _dangling_command_references(scenario: "Scenario", spacecraft_names: set, ground_station_names: set) -> List[str]:
    """Cross-references every command's resource-name params against the
    scenario's actual spacecraft/ground stations -- the mission-sequence
    equivalent of ``Scenario.validate()``'s own
    ``dispersion.spacecraft in names`` style checks, but collecting every
    one found instead of raising on the first.
    """
    from .references import _command_references  # local: internal helper, not part of the public API

    errors: List[str] = []
    for ref in _command_references(scenario.mission_sequence, "mission_sequence"):
        known = spacecraft_names if ref.resource_kind == "spacecraft" else ground_station_names
        if ref.name not in known:
            errors.append(f"{ref.path}: {ref.resource_kind} {ref.name!r} is not one of this scenario's "
                            f"{ref.resource_kind}s {sorted(known)}")
    return errors
