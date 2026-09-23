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

"""Pure propellant/mass bookkeeping math (explicit-Euler rocket
equation), factored out of ``engine.orbit_maintenance`` so it can be
unit-tested WITHOUT a Basilisk build -- that module imports
``Basilisk.architecture``/``Basilisk.simulation`` at module level (its
``SysModel`` controller classes need them), which would otherwise make
even this plain arithmetic untestable in a development sandbox with no
Basilisk build (see ``missionStudio/README.md``'s "Environment honesty
note"). No Basilisk import here -- safe to import from anywhere,
matching the same "pure math, no Basilisk" split ``engine.constellation``
and ``engine.spacecraft_templates`` already use for the same reason.

This is the fix for a real bug (found by a full-codebase audit): every
mass-tracking controller in ``engine.orbit_maintenance``
(``StationKeepingController``, ``PhasingKeepingController``,
``ConstantFrameThrustController``) used to recompute an ABSOLUTE
``scObject.hub.mHub = self.dryMass + self.propellant`` every tick, from
its own construction-time-captured belief -- with more than one such
controller on the same spacecraft (``station_keeping`` +
``constant_thrust`` is an explicitly supported combination), or a Monte
Carlo ``dry_mass_kg`` dispersion applied before any of them ever run,
whichever one's ``UpdateState`` happened to run last each tick silently
discarded whatever mass contribution the others/the dispersion had
already made. :func:`apply_propellant_burn` fixes this at the root: it
takes the spacecraft's CURRENT total mass and returns that total minus
ONLY what this one tank burns this tick -- a self-contained delta,
order-independent and composable no matter how many other sources are
also adjusting the same mass.
"""

from __future__ import annotations

from typing import Tuple


def apply_propellant_burn(current_total_mass_kg: float, propellant_kg: float, thrust_n: float,
                           isp_s: float, dt_s: float, g0_mps2: float = 9.80665) -> Tuple[float, float, float, float]:
    """One tick's propellant burn via the explicit-Euler rocket equation,
    applied as a DELTA to ``current_total_mass_kg`` -- see this module's
    docstring for why that (rather than recomputing an absolute mass) is
    the fix for a real bug.

    Args:
        current_total_mass_kg: the spacecraft's ACTUAL current total mass
            (e.g. read from ``scObject.hub.mHub`` at the top of this
            tick) -- NOT this tank's own dry-mass-plus-propellant belief.
        propellant_kg: this tank's own remaining propellant BEFORE this
            tick's burn.
        thrust_n: commanded thrust magnitude this tick [N] (0.0 if not
            thrusting -- returned unchanged with zero burn).
        isp_s: thruster specific impulse [s].
        dt_s: elapsed time since the last tick [s].
        g0_mps2: standard gravity, for the rocket equation's mass flow
            rate [m/s^2].

    Returns:
        ``(new_total_mass_kg, new_propellant_kg, burned_kg, mdot_kg_s)``.
        ``burned_kg`` is clamped to never exceed ``propellant_kg`` (can't
        burn more than what's left, even if thrust/isp/dt would imply
        more) -- ``new_total_mass_kg == current_total_mass_kg -
        burned_kg`` and ``new_propellant_kg == propellant_kg -
        burned_kg`` always.
    """
    if thrust_n <= 0.0 or propellant_kg <= 1e-9:
        return current_total_mass_kg, propellant_kg, 0.0, 0.0
    mdot_kg_s = thrust_n / (isp_s * g0_mps2)  # [kg/s]
    burned_kg = min(mdot_kg_s * dt_s, propellant_kg)  # [kg] can't burn more than what's left
    return current_total_mass_kg - burned_kg, propellant_kg - burned_kg, burned_kg, mdot_kg_s
