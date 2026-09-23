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
Single source of truth for time/epoch handling.

``schema.scenario.Scenario.epoch_utc`` (an ISO 8601 UTC string) is the ONE
stored representation of a scenario's epoch -- every other representation
(SPICE ET, TAI, TT, or a Basilisk ``EpochMsg``) is DERIVED from it by this
module, on demand, rather than separately stored anywhere (schema, GUI
state, ...) and left free to drift out of sync. Every other part of
missionStudio that needs a time conversion should call into this module,
not roll its own SPICE/datetime math.

Requires a Basilisk build (imports ``Basilisk.architecture.messaging`` and
the ``pyswice`` CSPICE wrapper).

Verification status (updated after this project's first genuine access to
a working Basilisk build, via ``pip install "bsk[all]"`` -- see
``missionStudio/README.md``'s "Getting started" section): the exact
``furnsh_c``/``str2et_c``/``doubleArray``/``et2utc_c``/``unload_c``/
``unitim_c`` call sequence below was run for real against
``Basilisk.topLevelModules.pyswice`` (round-tripping
``"2030-01-01T00:00:00"`` -> ET -> back to the identical ISO string, and
producing sane TAI/TT offsets from ET). One real bug was caught doing
this: the module-level import used to be a bare ``import pyswice``, which
worked against this checkout's own source layout but not against the
published ``bsk`` package on PyPI, where the module lives at
``Basilisk.topLevelModules.pyswice`` (confirmed by reading
``Basilisk.utilities.simHelpers``'s own import of it) -- fixed below.
``get_path()``/kernel-fetching itself (as opposed to the SPICE calls that
consume an already-loaded kernel) could not be exercised end-to-end in
that same environment, because its network egress to NAIF's kernel host
was blocked -- see ``engine/kernels.py``'s own note.

Provenance of the SPICE call sequence below
--------------------------------------------
:func:`utc_to_et` and :func:`et_to_utc_iso` copy the exact
``furnsh_c``/``str2et_c``/``doubleArray``/``et2utc_c``/``unload_c`` call
sequence from ``Basilisk.utilities.simHelpers.timeStringToGregorianUTCMsg``
(verified by directly reading that function's source in this checkout, not
from memory) -- that is the one place in this codebase known to call
``pyswice`` correctly, including the easy-to-get-wrong ``doubleArray``
marshalling ``str2et_c`` needs for its output-pointer argument.

:func:`epoch_times`'s TAI/TT conversions use ``pyswice.unitim_c()``, whose
exposure was confirmed by reading ``src/topLevelModules/pyswice/pyswice.i``
directly (that file wraps the *entire* public CSPICE API via
``#include "SpiceUsr.h"``, excluding only four unrelated functions) before
it was ALSO exercised directly against a real build, per the verification
note above.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime

from Basilisk.utilities.supportDataTools.dataFetcher import DataFile, get_path

try:
    from Basilisk.topLevelModules import pyswice
except ImportError as exc:  # pragma: no cover - only hit without a Basilisk build
    raise ImportError(
        "missionstudio.engine.time_system requires the pyswice CSPICE wrapper, which ships "
        "with a Basilisk build. Build Basilisk (see missionStudio/README.md) before using this module."
    ) from exc


def utc_iso_to_spice_string(epoch_utc: str) -> str:
    """``'2030-01-01T00:00:00'`` -> a SPICE-recognizable time string
    (``'2030 JAN 01 00:00:00.000 (UTC)'``), matching the exact format
    ``missionAnalysis/mission_config.py``'s ``EPOCH_SPICE_STRING`` already
    uses elsewhere in this repo. Any sub-second precision in ``epoch_utc``
    (schema.scenario.Scenario.validate() only requires it to parse as ISO
    8601, not to be a whole second) is preserved to millisecond
    resolution -- ``dt.microsecond`` rounded down to milliseconds, not a
    literal ``.000`` that would silently discard it.
    """
    dt = datetime.fromisoformat(epoch_utc)
    millis = dt.microsecond // 1000
    return (dt.strftime("%Y %b %d %H:%M:%S") + f".{millis:03d} (UTC)").upper()


@contextlib.contextmanager
def _leap_second_kernel_loaded():
    """Load ``naif0012.tls`` for the duration of the ``with`` block, then
    unload it -- mirrors ``simHelpers.timeStringToGregorianUTCMsg()``'s
    own ``furnsh_c``/``unload_c`` pairing exactly, so repeated calls in one
    process don't leak kernel-pool entries.
    """
    lsk_path = str(get_path(DataFile.EphemerisData.naif0012))
    pyswice.furnsh_c(lsk_path)
    try:
        yield
    finally:
        pyswice.unload_c(lsk_path)


def utc_to_et(epoch_utc: str) -> float:
    """UTC ISO 8601 string -> ET (TDB seconds past the J2000 epoch)."""
    spice_string = utc_iso_to_spice_string(epoch_utc)
    with _leap_second_kernel_loaded():
        et_out = pyswice.new_doubleArray(1)
        try:
            pyswice.str2et_c(spice_string, et_out)
            return pyswice.doubleArray_getitem(et_out, 0)
        finally:
            pyswice.delete_doubleArray(et_out)  # free the SWIG-allocated array (leaked otherwise)


def et_to_utc_iso(et: float) -> str:
    """ET (TDB seconds past J2000) -> UTC ISO 8601 string, e.g.
    ``'2030-01-01T00:00:00.000000'``.
    """
    with _leap_second_kernel_loaded():
        return pyswice.et2utc_c(et, "ISOC", 6, 255, "Yo")


@dataclass
class EpochTimes:
    """All the standard time-system representations of one epoch, computed
    together so the GUI/CLI never has to re-derive (or accidentally
    re-diverge) any of them relative to each other.
    """

    utc_iso: str
    et_s: float   # Ephemeris Time / Barycentric Dynamical Time (TDB), seconds past J2000
    tai_s: float  # International Atomic Time, seconds past J2000
    tt_s: float   # Terrestrial Time, seconds past J2000 (CSPICE calls this "TDT")


def epoch_times(epoch_utc: str) -> EpochTimes:
    """Compute ET/TAI/TT for a UTC epoch. See the module docstring for the
    TAI/TT conversion's verification status.
    """
    et = utc_to_et(epoch_utc)
    with _leap_second_kernel_loaded():
        tai = pyswice.unitim_c(et, "ET", "TAI")
        tt = pyswice.unitim_c(et, "ET", "TDT")
    return EpochTimes(utc_iso=epoch_utc, et_s=et, tai_s=tai, tt_s=tt)


def build_epoch_msg(epoch_utc: str):
    """Build a standalone Basilisk ``EpochMsg`` for the given UTC epoch.
    Thin wrapper over ``simHelpers.timeStringToGregorianUTCMsg()`` -- kept
    here so every other missionStudio module asks THIS module for it
    instead of importing ``simHelpers`` directly (single source of truth,
    see module docstring).
    """
    from Basilisk.utilities import simHelpers

    return simHelpers.timeStringToGregorianUTCMsg(utc_iso_to_spice_string(epoch_utc))
