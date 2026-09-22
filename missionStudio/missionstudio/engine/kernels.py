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
SPICE kernel management: a thin, GUI-facing wrapper over Basilisk's own
versioned kernel fetch/cache (``Basilisk.utilities.supportDataTools.dataFetcher``,
which fetches via ``pooch`` and caches locally -- this is real, native
Basilisk infrastructure, not something this module reimplements), adding
a status report so the app is never silently trusting a kernel the user
can't see or verify. Satisfies the "auto-download/cache with version
pinning, not silent hardcoding" requirement.

Requires a Basilisk build (imports ``Basilisk.utilities...``) -- cannot be
executed in this development sandbox (no Basilisk build here; see
``missionStudio/README.md``). Written directly against the verified
``dataFetcher``/``spiceKernels``/``simIncludeGravBody`` source in this
checkout (not from memory) -- exercise on first real run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from Basilisk.utilities.supportDataTools.dataFetcher import DataFile, get_path

# Matches Basilisk's own default kernel set exactly -- see
# utilities/supportDataTools/spiceKernels.py's DEFAULT_KERNELS and
# simIncludeGravBody.gravBodyFactory.createSpiceInterface()'s own default
# spiceKernelFileNames. Kept as a separate constant here (rather than
# importing spiceKernels.DEFAULT_KERNELS) only so this module's own default
# is explicit and independently readable; the values are identical.
DEFAULT_KERNELS: tuple = (
    DataFile.EphemerisData.naif0012,       # leap-second kernel (LSK)
    DataFile.EphemerisData.de430,          # planetary ephemeris (SPK)
    DataFile.EphemerisData.de_403_masses,  # body GM/masses (PCK)
    DataFile.EphemerisData.pck00010,       # planet shape/orientation (PCK)
)


class KernelError(Exception):
    """Raised when a required kernel could not be fetched -- carries the
    specific kernel name(s) and underlying error, never a bare Basilisk
    traceback from deep inside SPICE.
    """


@dataclass
class KernelStatus:
    name: str  # enum member name, e.g. "naif0012"
    filename: str  # e.g. "naif0012.tls"
    path: Optional[Path]
    available: bool
    error: Optional[str]
    modified_utc: Optional[str]  # local cached file's mtime, ISO 8601 -- a
    # proxy for "how current is this cached copy". Surfaced explicitly
    # rather than trusted forever: a leap-second kernel in particular needs
    # periodic refresh as new leap seconds are announced (roughly every
    # few years), and this app must not hide that from the user.


def ensure_kernels(kernels: Iterable = DEFAULT_KERNELS) -> List[KernelStatus]:
    """Ensure every kernel in ``kernels`` is fetched/cached (triggering a
    download through Basilisk's own ``pooch``-backed fetch if not already
    cached) and return a status report for each. The GUI/CLI call this to
    show kernel state (and surface any fetch failure) BEFORE a run, rather
    than the run failing deep inside SPICE with a less actionable error.
    """
    statuses = []
    for kernel in kernels:
        try:
            path = get_path(kernel)
            modified_utc = (
                datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
                if path.exists() else None
            )
            statuses.append(KernelStatus(kernel.name, kernel.value, path, True, None, modified_utc))
        except Exception as exc:  # deliberately broad: report ANY fetch failure, not just FileNotFoundError
            statuses.append(KernelStatus(kernel.name, kernel.value, None, False, str(exc), None))
    return statuses


def require_kernels(kernels: Iterable = DEFAULT_KERNELS) -> List[KernelStatus]:
    """Like :func:`ensure_kernels`, but raises :class:`KernelError` naming
    every kernel that failed, instead of returning a status list with
    ``available=False`` entries for the caller to notice on its own.
    """
    statuses = ensure_kernels(kernels)
    failed = [s for s in statuses if not s.available]
    if failed:
        names = "; ".join(f"{s.name} ({s.error})" for s in failed)
        raise KernelError(f"could not fetch required SPICE kernel(s): {names}")
    return statuses


def build_spice_interface(grav_factory, spice_time_string: str, kernels: Iterable = DEFAULT_KERNELS,
                           epoch_in_msg: bool = True):
    """Thin wrapper over ``gravBodyFactory.createSpiceInterface()``: ensures
    every requested kernel is cached first (see :func:`require_kernels`)
    and passes the resolved local cache directory straight through. Must
    be called AFTER the gravity bodies are added to ``grav_factory``
    (same ordering requirement as the method it wraps).

    Args:
        grav_factory: a ``Basilisk.utilities.simIncludeGravBody.gravBodyFactory``
            instance with its gravity bodies already created.
        spice_time_string: a SPICE-recognizable epoch string -- use
            ``engine.time_system.utc_iso_to_spice_string()`` to build one
            from the scenario's ``epoch_utc``, rather than formatting it
            ad hoc (single source of truth for time, see that module).
        kernels: which kernels to load; defaults to :data:`DEFAULT_KERNELS`.
        epoch_in_msg: forwarded to ``createSpiceInterface`` -- also
            publishes an ``EpochMsg`` other modules (e.g.
            ``spaceWeatherData``) can subscribe to.
    """
    statuses = require_kernels(kernels)
    kernel_dir = statuses[0].path.parent
    return grav_factory.createSpiceInterface(
        path=str(kernel_dir),
        time=spice_time_string,
        spiceKernelFileNames=tuple(kernels),
        epochInMsg=epoch_in_msg,
    )
