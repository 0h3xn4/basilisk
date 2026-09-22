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

Default camera / orbit-line view (fixed after user feedback that Vizard
opened locked onto the spacecraft with no context -- "improve" per that
feedback, since a viewer that opens on an unrecognizable close-up isn't
"understandable live data" no matter what panels are attached to it)
-------------------------------------------------------------------------
``enableUnityVisualization()`` on its own does not configure the VIEWER's
starting camera or orbit-trace lines at all -- those are separate fields
on the ``VizSettings`` message it creates (``viz.settings``), read
directly from ``src/simulation/vizard/_GeneralModuleFiles/vizStructures.h``
in this checkout (not guessed): ``mainCameraTarget`` ("if a valid
spacecraft or celestial body name is provided, the main camera will be
targeted at that body at start"), ``orbitLinesOn``/``trueTrajectoryLinesOn``
(osculating/true orbit trace lines, off by default), and the
``show*Labels`` flags. Left unset, Vizard falls back to its own built-in
default, which is a spacecraft-locked view with no orbit trace -- exactly
the complaint. :func:`enable_vizard` now sets these explicitly: camera
targeted at the central body (an Earth-centered view with the orbit
tracing around it, matching STK/GMAT/FreeFlyer's default framing) unless
:attr:`VizardRequest.camera_target` names something else (a specific
spacecraft, to watch it up close, or another body), plus both orbit-trace
line types and spacecraft/body labels on.

Verification status: ``vizSupport.enableUnityVisualization``'s signature
and ``addLocation``'s signature were read directly from
``src/utilities/vizSupport.py`` in this checkout (not assumed); the
``rwEffectorList``/``saveFile``/``liveStream`` usage pattern matches
``examples/scenarioAttitudeFeedbackRW.py``. The ``VizSettings`` fields
this module now sets were confirmed to exist under these exact names by
reading ``vizStructures.h`` directly, but setting them was NOT exercised
against a real running Vizard instance (no display in this development
sandbox to confirm the rendered result) -- report back if the camera/
orbit-line behavior doesn't match what's documented here.

Live-data panels (fixed after user feedback that the live Vizard stream
wasn't "understandable" -- a moving dot with no other readout doesn't
answer "is the battery draining, is the tank running dry, is this pass
actually in contact with the ground")
-------------------------------------------------------------------------
Three more ``VizSettings``/``vizInterface`` structures, all populated from
REAL, already-simulated messages (nothing here is a static snapshot or an
analytical estimate -- see each source module's own docstring):

* **Battery state of charge** -- a Vizard ``GenericStorage`` bar panel per
  spacecraft with ``PowerConfig`` configured, wired directly to that
  spacecraft's ``simpleBattery.SimpleBattery.batPowerOutMsg``
  (``engine.service``). Pattern copied from
  ``examples/MultiSatBskSim/scenariosMultiSat/scenario_StationKeepingMultiSat.py``
  (a real, shipped Basilisk example -- not guessed).
* **Station-keeping propellant remaining** -- a second ``GenericStorage``
  panel per spacecraft with ``StationKeepingConfig`` configured, wired to
  ``engine.orbit_maintenance.StationKeepingController.fuelTankOutMsg`` (a
  real ``FuelTankMsgPayload`` that controller publishes specifically for
  this -- see its own module docstring). Same example's pattern for the
  "Tank" panel.
* **Ground-station access windows** -- one ``GenericSensor`` marker per
  (ground station, spacecraft) pair that Phase 3's access analysis tracks,
  changing color LIVE between "no access" and "access" as
  ``groundLocation.GroundLocation``'s already-computed ``hasAccess`` flag
  changes each tick. ``GenericSensor`` has no boolean/message-driven color
  input on its own -- it takes an integer "mode" via a
  ``DeviceCmdMsgPayload``, so :func:`enable_vizard` adds one small bridge
  ``SysModel`` per pair (defined locally inside this function, not at
  module scope, to keep this module's own Basilisk import lazy -- see
  below) that republishes ``AccessMsgPayload.hasAccess`` as that command
  value. Per ``GenericSensor``'s own field comment in ``vizStructures.h``
  ("Modes 0 and 1 will use the 0th color, Mode 2 will use the color
  indexed to 1"), the bridge commands 0 for no-access and 2 (not 1) for
  access, so the two colors actually differ. This marker's position/
  boresight (``r_SB_B``/``normalVector``) is a placeholder (body origin,
  +X) since neither the schema nor Basilisk's ``groundLocation`` model a
  real antenna mounting direction -- it is a status indicator, not an
  antenna visualization (compare ``Transceiver``/comm-ring visualization,
  which needs a real data-node system this project does not have -- see
  ``PowerConfig``'s docstring on scope).

None of this feeds back into simulated physics or the exported CSV/plot
data -- ``engine.service.run()`` already reports the same battery/
propellant/access numbers there; this only makes them visible live in
Vizard too.

Verification status: the ``GenericStorage``/battery+fuel-tank wiring
matches a real, shipped multi-satellite Basilisk example line-for-line
(cited above). The ``GenericSensor``/``DeviceCmdMsgPayload``/bridge-module
wiring matches the field-level pattern in a second real shipped example
(``examples/scenarioGroundLocationImaging.py``), but the specific
"republish an access flag as a sensor mode" composition is this module's
own, not copied from an example verbatim -- like the camera/orbit-line
work above, none of this was exercised against a real running Vizard
instance (no display in this development sandbox).

**Real bug found on first actual run** (reported: ``basic_string::_M_create``,
a C++ ``std::length_error``, thrown well after setup completed, during an
otherwise-unrelated-looking string operation): every
``_AccessIndicatorBridge`` instance this function created was referenced
ONLY by a local loop variable -- ``engine.service`` discarded this
function's return value entirely, so nothing kept those Python objects
(or ``viz`` itself) alive past this function returning. Unlike the plain
-data ``vizInterface`` structs (``GenericStorage``/``GenericSensor``,
whose relevant state ``enableUnityVisualization()`` copies into its own
C++ containers), ``_AccessIndicatorBridge`` is a custom Python
``SysModel`` with virtual ``UpdateState``/``Reset`` methods Basilisk calls
back into via a SWIG director -- letting the Python side of that get
garbage-collected while the C++ side is still task-registered is
undefined behavior, and heap corruption manifesting later as an unrelated
string-construction crash is a textbook symptom. Every OTHER custom
Python ``SysModel`` in this codebase (this module's own
``StationKeepingController``/``PhasingKeepingController``,
``../missionAnalysis``'s ``PowerLoadGate``/``InstrumentEclipseGate``) is
deliberately kept alive by its caller storing the returned object
somewhere persistent; this bridge class was the one place that pattern
was broken. Fixed by attaching every bridge instance to ``viz`` itself
(``viz._missionstudio_access_indicator_bridges``) and having
``engine.service`` retain the returned ``viz`` (previously discarded) for
the ``SimulationService`` instance's lifetime.
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
    # Name of the spacecraft or celestial body Vizard's main camera starts
    # targeted at. None (the default) targets the scenario's central body --
    # an Earth-centered view with the orbit tracing around it, matching
    # STK/GMAT/FreeFlyer's default framing, rather than a spacecraft-locked
    # close-up. Set this to a spacecraft name to start zoomed in on it instead.
    camera_target: Optional[str] = None
    # Draw osculating + true orbit-trace lines so the orbit path is visible,
    # not just a moving dot. On by default for the same "understandable at a
    # glance" reason as camera_target.
    show_orbit_lines: bool = True


def enable_vizard(scSim, task_name: str, sc_objects: List, request: VizardRequest,
                   rw_effectors_by_spacecraft: Optional[List] = None,
                   ground_stations: Optional[Dict[str, object]] = None,
                   central_body_name: str = "earth",
                   battery_by_spacecraft: Optional[Dict[str, object]] = None,
                   station_keeping_by_spacecraft: Optional[Dict[str, object]] = None,
                   access_out_msgs: Optional[Dict[tuple, object]] = None):
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
        battery_by_spacecraft: ``{spacecraft_name: simpleBattery.SimpleBattery}``
            for every spacecraft with ``PowerConfig`` set -- see module
            docstring's "Live-data panels" section.
        station_keeping_by_spacecraft: ``{spacecraft_name: engine.orbit_maintenance.StationKeepingController}``
            for every spacecraft with ``StationKeepingConfig`` set -- same
            section.
        access_out_msgs: ``{(ground_station_name, spacecraft_name): groundLocation.accessOutMsgs[i]}``
            for every station/spacecraft pair Phase 3's access analysis
            tracks (``engine.service``'s own ``_access_out_msgs``) -- same
            section.
    """
    from Basilisk.architecture import messaging, sysModel
    from Basilisk.simulation import vizInterface
    from Basilisk.utilities import vizSupport

    if request.save_file and request.live_stream:
        raise VizardError("VizardRequest: set at most one of save_file/live_stream, not both")
    if not request.save_file and not request.live_stream:
        raise VizardError("VizardRequest: set save_file or live_stream=True -- nothing to do otherwise")

    if request.save_file:
        save_path = Path(request.save_file)
        save_path.parent.mkdir(parents=True, exist_ok=True)

    battery_by_spacecraft = battery_by_spacecraft or {}
    station_keeping_by_spacecraft = station_keeping_by_spacecraft or {}
    access_out_msgs = access_out_msgs or {}

    class _AccessIndicatorBridge(sysModel.SysModel):
        """See this module's docstring, "Live-data panels" section,
        "Ground-station access windows" bullet, for why this exists and
        why 0/2 (not 0/1) are the two command values used.
        """

        _NO_ACCESS_CMD = 0
        _ACCESS_CMD = 2

        def __init__(self, name: str, access_out_msg):
            super().__init__()
            self.ModelTag = name
            self.accessInMsg = messaging.AccessMsgReader()
            self.accessInMsg.subscribeTo(access_out_msg)
            self.cmdOutMsg = messaging.DeviceCmdMsg()

        def Reset(self, CurrentSimNanos):
            pass

        def UpdateState(self, CurrentSimNanos):
            has_access = bool(self.accessInMsg().hasAccess)
            payload = messaging.DeviceCmdMsgPayload()
            payload.deviceCmd = self._ACCESS_CMD if has_access else self._NO_ACCESS_CMD
            self.cmdOutMsg.write(payload, CurrentSimNanos, self.moduleID)

    generic_storage_list: List[Optional[list]] = []
    generic_sensor_list: List[Optional[list]] = []
    spacecraft_with_storage_panel: List[str] = []
    spacecraft_with_sensor_labels: List[str] = []
    # _AccessIndicatorBridge instances MUST be kept alive by a persistent
    # Python reference for as long as they're registered on scSim's task --
    # they have virtual UpdateState/Reset methods Basilisk calls back into
    # (a SWIG director), unlike the plain-data vizInterface structs below
    # (GenericStorage/GenericSensor), whose relevant state is copied into
    # Basilisk's own C++ containers by enableUnityVisualization() and so
    # don't need this. A Python object garbage-collected while its C++
    # counterpart is still task-registered is undefined behavior -- see
    # where this list is attached to ``viz`` below, and
    # ``engine.service``'s own retention of the returned ``viz``.
    access_indicator_bridges: List[object] = []

    for sc_object in sc_objects:
        sc_name = sc_object.ModelTag
        storages = []

        battery = battery_by_spacecraft.get(sc_name)
        if battery is not None:
            panel = vizInterface.GenericStorage()
            panel.label = "Battery"
            panel.type = "Battery"
            panel.units = "W-s"
            panel.color = vizInterface.IntVector(vizSupport.toRGBA255("red") + vizSupport.toRGBA255("lightgreen"))
            panel.thresholds = vizInterface.IntVector([20])  # [%] below this, use the first (red) color
            battery_reader = messaging.PowerStorageStatusMsgReader()
            battery_reader.subscribeTo(battery.batPowerOutMsg)
            panel.batteryStateInMsg = battery_reader
            storages.append(panel)

        controller = station_keeping_by_spacecraft.get(sc_name)
        if controller is not None:
            panel = vizInterface.GenericStorage()
            panel.label = "Propellant"
            panel.type = "Propellant Tank"
            panel.units = "kg"
            panel.color = vizInterface.IntVector(vizSupport.toRGBA255("cyan"))
            tank_reader = messaging.FuelTankMsgReader()
            tank_reader.subscribeTo(controller.fuelTankOutMsg)
            panel.fuelTankStateInMsg = tank_reader
            storages.append(panel)

        generic_storage_list.append(storages or None)
        if storages:
            spacecraft_with_storage_panel.append(sc_name)

        sensors = []
        for (gs_name, paired_sc_name), access_out_msg in access_out_msgs.items():
            if paired_sc_name != sc_name:
                continue
            bridge = _AccessIndicatorBridge(f"{sc_name}_{gs_name}_accessIndicator", access_out_msg)
            scSim.AddModelToTask(task_name, bridge)
            access_indicator_bridges.append(bridge)

            cmd_reader = messaging.DeviceCmdMsgReader()
            cmd_reader.subscribeTo(bridge.cmdOutMsg)

            sensor = vizInterface.GenericSensor()
            sensor.r_SB_B = [0.0, 0.0, 0.0]  # placeholder -- see module docstring
            sensor.normalVector = [1.0, 0.0, 0.0]  # placeholder -- see module docstring
            sensor.fieldOfView.push_back(0.1)  # [rad] small symbolic cone, not a real antenna beamwidth
            sensor.color = vizInterface.IntVector(vizSupport.toRGBA255("red") + vizSupport.toRGBA255("lightgreen"))
            sensor.label = f"Access: {gs_name}"
            sensor.genericSensorCmdInMsg = cmd_reader
            sensors.append(sensor)

        generic_sensor_list.append(sensors or None)
        if sensors:
            spacecraft_with_sensor_labels.append(sc_name)

    try:
        viz = vizSupport.enableUnityVisualization(
            scSim, task_name, sc_objects,
            saveFile=str(request.save_file) if request.save_file else None,
            liveStream=request.live_stream,
            rwEffectorList=rw_effectors_by_spacecraft,
            genericStorageList=generic_storage_list if any(generic_storage_list) else None,
            genericSensorList=generic_sensor_list if any(generic_sensor_list) else None,
        )
    except Exception as exc:  # noqa: BLE001 -- report ANY Vizard setup failure with a specific message
        raise VizardError(f"vizSupport.enableUnityVisualization failed: {exc}") from exc

    # Keep the access-indicator bridges alive for as long as ``viz`` is --
    # see the comment where access_indicator_bridges is created above.
    viz._missionstudio_access_indicator_bridges = access_indicator_bridges

    # See module docstring: without these, Vizard falls back to its own
    # default (spacecraft-locked, no orbit trace) instead of an
    # STK/GMAT/FreeFlyer-style central-body-centered view.
    viz.settings.mainCameraTarget = request.camera_target or central_body_name
    if request.show_orbit_lines:
        viz.settings.orbitLinesOn = 1  # osculating orbit line, relative to parent body
        viz.settings.trueTrajectoryLinesOn = 1  # true (propagated) trajectory line, inertial
    viz.settings.showSpacecraftLabels = 1
    viz.settings.showCelestialBodyLabels = 1

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

    # showGenericStoragePanel/showGenericSensorLabels default to "use Vizard's
    # own default" (which may be off) unless explicitly requested per
    # spacecraft -- without this, a live battery/propellant panel or access
    # -window label could silently not be visible despite being wired up.
    # ONE setInstrumentGuiSetting call per spacecraft (not one per flag):
    # each call appends a new entry to vizSupport's own module-level
    # settings list rather than merging into an existing one, so a
    # spacecraft needing both flags must set them together.
    for sc_name in set(spacecraft_with_storage_panel) | set(spacecraft_with_sensor_labels):
        kwargs = {}
        if sc_name in spacecraft_with_storage_panel:
            kwargs["showGenericStoragePanel"] = True
        if sc_name in spacecraft_with_sensor_labels:
            kwargs["showGenericSensorLabels"] = True
        vizSupport.setInstrumentGuiSetting(viz, spacecraftName=sc_name, **kwargs)

    return viz
