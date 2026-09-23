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
Scenario schema migrations: one function per version bump, applied in
order by :func:`migrate` so a scenario file written by an older version of
this tool keeps loading correctly.

Adding a migration
-------------------
When a change to ``schema.scenario`` would break older files (a field
renamed/removed/re-typed -- purely *additive* fields with a sensible
default do NOT need a migration, since ``from_dict`` already tolerates
missing keys via dataclass defaults):

1. Bump ``schema.scenario.CURRENT_SCHEMA_VERSION`` by one.
2. Add a ``_migrate_<old>_to_<new>(data: dict) -> dict`` function here that
   transforms a raw dict at the OLD version into one valid at the NEW
   version, and sets ``data["schema_version"] = <new>``.
3. Register it in ``MIGRATIONS`` keyed by the OLD version number.

:func:`migrate` then walks forward one step at a time from whatever
version the file declares up to ``CURRENT_SCHEMA_VERSION``, so a very old
file still loads even after several schema versions have shipped.
"""

from typing import Callable, Dict

from .scenario import CURRENT_SCHEMA_VERSION, ScenarioValidationError

# {old_version: migration_function}. Empty for now -- schema_version 1 is
# the first version, so there is nothing to migrate FROM yet. This is
# where the first entry goes the day version 2 ships.
MIGRATIONS: Dict[int, Callable[[dict], dict]] = {}


def migrate(data: dict) -> dict:
    version = data.get("schema_version")
    # bool is a subclass of int in Python (isinstance(True, int) is True),
    # so a malformed file with "schema_version": true/false would
    # otherwise pass this check and silently end up stored as a literal
    # True/False rather than a real version number.
    if not isinstance(version, int) or isinstance(version, bool):
        raise ScenarioValidationError(
            f"schema_version must be an integer, got {version!r}"
        )
    if version > CURRENT_SCHEMA_VERSION:
        raise ScenarioValidationError(
            f"scenario file is schema_version {version}, but this build of missionStudio "
            f"only understands up to version {CURRENT_SCHEMA_VERSION} -- upgrade missionStudio "
            f"to open it, or use the version that wrote it."
        )
    while version < CURRENT_SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ScenarioValidationError(
                f"no migration registered from schema_version {version} to "
                f"{version + 1} -- this indicates a bug in missionStudio, not a bad file."
            )
        data = step(data)
        new_version = data.get("schema_version")
        if new_version != version + 1:
            raise ScenarioValidationError(
                f"migration from schema_version {version} did not set schema_version to "
                f"{version + 1} (got {new_version!r}) -- this indicates a bug in the migration."
            )
        version = new_version
    return data
