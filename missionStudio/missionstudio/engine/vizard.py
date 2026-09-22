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
Vizard integration: satisfies the user's explicit "no embedded 3D viewer is
okay, as long as you ... provide good Vizard visualization with valuable
'live simulation data'" requirement.

Vizard is a separate, precompiled Unity application -- it cannot be
embedded in a Qt window (confirmed during the pre-Phase-0 capability audit;
see missionStudio/README.md), so this module wraps Basilisk's own
``vizSupport.enableUnityVisualization()``, which either streams live to a
running Vizard instance over TCP (``liveStream=True`` -- the user launches
Vizard themselves and this app just feeds it) or writes a ``.bin``
playback file Vizard opens afterward (``saveFile=...``). Both modes are
native Basilisk functionality; nothing here reimplements or emulates
Vizard's rendering.

"Live simulation data", concretely, for what ``engine.service`` actually
wires up in Phase 2:

* Reaction wheel speeds/torques -- passed via ``rwEffectorList``, which
  makes Vizard draw its native per-wheel speed/torque bars. Only present
  for spacecraft with ``"reaction_wheel"`` actuators (see ``engine.fsw``);
  ``None`` otherwise, matching ``enableUnityVisualization``'s own
  ``ensure_correct_len_list`` handling of a per-spacecraft ``None`` entry.
* Ground stations -- drawn via ``vizSupport.addLocation`` (lat/lon/alt,
  field of view, minimum-elevation cone) for every
  :class:`schema.scenario.GroundStationConfig`, so the access geometry
  ``locationPointing``/``groundLocation`` compute is actually visible in
  Vizard, not just in a CSV.
* Attitude, position, and (natively, always) eclipse/sun-direction
  indication come from ``enableUnityVisualization``'s own per-spacecraft
  state message wiring -- no extra work needed here.

Thruster plumes (``thrEffectorList``) are NOT passed: Phase 2 does not
wire up thruster actuators (see ``engine.fsw``'s module docstring), so
there is nothing to visualize there yet.

Verification status: ``vizSupport.enableUnityVisualization``'s signature
and ``addLocation``'s signature were read directly from
``src/utilities/vizSupport.py`` in this checkout (not assumed); the
``rwEffectorList``/``saveFile``/``liveStream`` usage pattern matches
``examples/scenarioAttitudeFeedbackRW.py``. Cannot be executed in this
development sandbox (no Basilisk build here).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


class VizardError(Exception):
    """Raised when Vizard support (``vizSupport``/``vizInterface``) cannot
    be set up -- carries the specific underlying error, not a bare
    traceback.
    """


@dataclass
class VizardRequest:
    """What the GUI/CLI ask for. Exactly one of ``save_file``/``live_stream``
    should be set -- see :func:`enable_vizard`.
    """

    save_file: Optional[str] = None  # path for a .bin playback file Vizard opens after the run
    live_stream: bool = False  # stream live to a Vizard instance already running on this machine


def enable_vizard(scSim, task_name: str, sc_objects: List, request: VizardRequest,
                   rw_effectors_by_spacecraft: Optional[List] = None,
                   ground_stations: Optional[Dict[str, object]] = None,
                   central_body_name: str = "earth"):
    """Call once, after every spacecraft/sensor/actuator/FSW module for
    this run has been added to ``scSim`` and BEFORE ``InitializeSimulation()``
    (matches every ``vizSupport.enableUnityVisualization`` call site in
    this checkout's own examples).

    Args:
        sc_objects: every ``spacecraft.Spacecraft`` in this run, in the
            same order as ``rw_effectors_by_spacecraft`` if given.
        rw_effectors_by_spacecraft: one ``reactionWheelStateEffector.ReactionWheelStateEffector``
            (or ``None``) per entry in ``sc_objects`` -- see module
            docstring.
        ground_stations: ``{name: groundLocation.GroundLocation}`` for
            every ``GroundStationConfig`` already built for this scenario.
    """
    from Basilisk.utilities import vizSupport

    if request.save_file and request.live_stream:
        raise VizardError("VizardRequest: set at most one of save_file/live_stream, not both")
    if not request.save_file and not request.live_stream:
        raise VizardError("VizardRequest: set save_file or live_stream=True -- nothing to do otherwise")

    if request.save_file:
        save_path = Path(request.save_file)
        save_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        viz = vizSupport.enableUnityVisualization(
            scSim, task_name, sc_objects,
            saveFile=str(request.save_file) if request.save_file else None,
            liveStream=request.live_stream,
            rwEffectorList=rw_effectors_by_spacecraft,
        )
    except Exception as exc:  # noqa: BLE001 -- report ANY Vizard setup failure with a specific message
        raise VizardError(f"vizSupport.enableUnityVisualization failed: {exc}") from exc

    for gs_name, gs in (ground_stations or {}).items():
        # Edge-to-edge cone angle for the access region above gs.minimumElevation
        # (elevation measured from the local horizon): a zenith-centered cone of
        # half-angle (pi/2 - minimumElevation) has full angle pi - 2*minimumElevation.
        field_of_view = math.pi - 2.0 * gs.minimumElevation
        vizSupport.addLocation(
            viz, stationName=gs_name, parentBodyName=central_body_name,
            r_GP_P=list(gs.r_LP_P_Init), fieldOfView=field_of_view,
            color="cyan", label=gs_name,
        )

    return viz
