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
Phase 2: builds the attitude navigation/guidance/control/actuation module
chain for one spacecraft -- kept separate from ``engine/service.py`` so
that file stays orchestration-only (build gravity, build spacecraft, call
into here once per spacecraft that wants attitude control).

Every call sequence below (module class names, attribute names,
``subscribeTo`` message wiring) is copied from an ACTUALLY RUNNING example
script in this checkout, not written from memory or guessed, per this
project's "never fabricate a Basilisk API" rule:

* ``simpleNav``, ``inertial3D`` + ``attTrackingError`` + ``mrpFeedback`` +
  ``rwMotorTorque`` + ``reactionWheelStateEffector`` + ``VehicleConfigMsg``:
  ``examples/scenarioAttitudeFeedbackRW.py``.
* ``hillPoint``, ``extForceTorque`` (idealized actuation) +
  ``scObject.addDynamicEffector``: ``examples/scenarioAttitudeGuidance.py``.
* ``velocityPoint``: ``examples/scenarioHohmann.py``.
* ``locationPointing`` + ``groundLocation.GroundLocation``:
  ``examples/scenarioAttLocPoint.py``.
* ``sunSafePoint`` (``sHatBdyCmd``/``minUnitMag``/``sunDirectionInMsg``/
  ``imuInMsg``): ``src/fswAlgorithms/attGuidance/sunSafePoint/_UnitTest/test_sunSafePoint.py``.
  ``sunSafePoint.imuInMsg`` is REQUIRED (``sunSafePoint.c`` raises
  ``BSK_ERROR`` via an ``isLinked()`` check if it is not connected) --
  confirmed by reading that source directly, not assumed. Both
  ``sunDirectionInMsg`` and ``imuInMsg`` are the same ``NavAttMsgPayload``
  type and ``simpleNav``'s single ``attOutMsg`` already carries both the
  ``vehSunPntBdy`` sun-heading field and ``omega_BN_B``, so both subscribe
  to the same ``simpleNav`` output -- there is no second sensor needed.
* ``magneticFieldWMM`` (``configureWMMFile``, ``addSpacecraftToModel``,
  ``envOutMsgs[i]`` indexed by call order):
  ``src/simulation/environment/magneticFieldWMM/_UnitTest/test_magneticFieldWMM.py``
  and that module's own ``.rst`` user guide.

Scoping decisions made explicit here (see ``engine/service.py``'s Phase 2
docstring for the full list):

* ``hillPoint``/``velocityPoint`` do NOT subscribe ``celBodyInMsg``: every
  orbit IC in this app is already given relative to ``gravity.central_body``
  (``central_body.isCentralBody = True``, matching every example scenario
  in this checkout), so the spacecraft's own ``r_BN_N``/``v_BN_N`` from
  ``simpleNav.transOutMsg`` is central-body-relative -- leaving
  ``celBodyInMsg`` unlinked is correct here, not a missing feature (see
  ``hillPoint.h``'s ``planetMsgIsLinked`` flag, which exists precisely to
  make this optional). This DEPENDS on ``engine/service.py`` setting
  ``spice_object.zeroBase = gravity.central_body`` (see that module's
  ``build()``): without it, the central body's own SPICE-linked position
  gets added into every spacecraft's ``r_BN_N``/``v_BN_N``
  (``GravityEffector::updateInertialPosAndVel()`` in
  ``gravityEffector.cpp`` always adds the central body's own position on
  top of the propagated central-body-relative state), which would make
  this assumption false again -- a real bug this project shipped and only
  caught once Basilisk actually ran end-to-end (see ``engine/service.py``'s
  ``zeroBase`` comment for the full explanation).
* ``locationPointing``'s ``fsw_params["target_body"]`` (point at a
  celestial body directly, vs. a ground station) is schema-valid but NOT
  built here yet -- it needs an ``EphemerisMsg`` (``celBodyInMsg``), which
  this checkout only produces via ``ephemerisConverter`` from a
  ``SpicePlanetStateMsg``; that conversion is not wired up in Phase 2.
  :func:`build_guidance` raises a clear error for it rather than silently
  falling back to ground-station targeting.
* The attitude control loop is closed on TRUTH spacecraft state
  (``simpleNav``'s error model defaults to zero, i.e. ``PMatrix``/noise are
  left at Basilisk's own zero defaults unless a future phase adds a GUI/
  schema field for them) -- ``simpleNav`` is still the module in the loop
  (not raw ``scStateOutMsg``), so wiring in real navigation error later is
  a matter of setting its ``PMatrix``, not restructuring this chain.

Verification status: same as ``engine/service.py`` -- cannot be executed in
this development sandbox (no Basilisk build here), written directly
against the verified call sequences cited above.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from Basilisk.architecture import messaging
from Basilisk.fswAlgorithms import (
    attTrackingError,
    hillPoint,
    inertial3D,
    locationPointing,
    mrpFeedback,
    rwMotorTorque,
    sunSafePoint,
    velocityPoint,
)
from Basilisk.simulation import (
    coarseSunSensor,
    extForceTorque,
    groundLocation,
    imuSensor,
    magnetometer,
    magneticFieldWMM,
    reactionWheelStateEffector,
    simpleNav,
    starTracker,
)
from Basilisk.utilities import simIncludeRW

from ..schema.scenario import SUPPORTED_FSW_MODES

DEFAULT_MRP_GAINS: Dict[str, float] = {"K": 3.5, "P": 30.0}

# RW factory create() kwargs that must be Python float (rwFactory.create()
# calls exit(1) directly -- not a raised exception -- on a type mismatch;
# see simIncludeRW.py's own isinstance(..., float) checks), so any of
# these coming from JSON-loaded params (which may deserialize as int) are
# coerced defensively before being passed through.
_RW_FLOAT_KWARGS = (
    "Omega", "Omega_max", "maxMomentum", "P_max", "betaStatic",
    "fCoulomb", "fStatic", "cViscous", "u_min", "u_max", "Js",
)


class FswError(Exception):
    """Raised for an FSW configuration this module cannot (yet) build --
    always names the specific unsupported combination.
    """


def build_simple_nav(scSim, task_name: str, tag: str, sc_object, sun_state_out_msg=None):
    """Always built for any spacecraft with ``fsw_mode`` set -- the
    truth-to-navigation-message bridge every guidance mode reads from (see
    module docstring). ``sun_state_out_msg`` is the central SPICE
    interface's per-body output message for "sun" (only when "sun" is
    SPICE-tracked in this scenario); when given, ``simpleNav`` populates
    ``NavAttMsgPayload.vehSunPntBdy`` (verified directly in
    ``simpleNav.cpp``'s ``computeTrueOutput()``), which ``sunSafePoint``
    and any ``coarse_sun_sensor`` need.
    """
    nav = simpleNav.SimpleNav()
    nav.ModelTag = f"{tag}_simpleNav"
    nav.scStateInMsg.subscribeTo(sc_object.scStateOutMsg)
    if sun_state_out_msg is not None:
        nav.sunStateInMsg.subscribeTo(sun_state_out_msg)
    scSim.AddModelToTask(task_name, nav)
    return nav


def _wrap_with_att_tracking_error(scSim, task_name: str, tag: str, att_ref_out_msg, nav):
    """``inertial3D``/``hillPoint``/``velocityPoint`` only produce an
    ``AttRefMsg`` (a reference, not yet an error relative to the actual
    spacecraft attitude) -- ``mrpFeedback`` needs an ``AttGuidMsg``, so
    every one of those three modes is routed through this same
    ``attTrackingError`` step. ``sunSafePoint``/``locationPointing``
    produce ``AttGuidMsg`` directly and skip this (see ``build_guidance``).
    """
    err = attTrackingError.attTrackingError()
    err.ModelTag = f"{tag}_attTrackingError"
    err.attNavInMsg.subscribeTo(nav.attOutMsg)
    err.attRefInMsg.subscribeTo(att_ref_out_msg)
    scSim.AddModelToTask(task_name, err)
    return err.attGuidOutMsg


def build_guidance(scSim, task_name: str, tag: str, fsw_mode: str, fsw_params: dict, nav, mu: float,
                    ground_locations: Dict[str, object]):
    """Builds the guidance mode named by ``fsw_mode`` (one of
    :data:`schema.scenario.SUPPORTED_FSW_MODES`) and returns its
    ``AttGuidMsg``-typed output message, ready for :func:`build_mrp_feedback`.

    Args:
        ground_locations: ``{ground_station_name: groundLocation.GroundLocation}``
            for every ``GroundStationConfig`` already built for this
            scenario's central body -- only consulted for ``"locationPointing"``.
    """
    if fsw_mode not in SUPPORTED_FSW_MODES:
        raise FswError(f"fsw_mode {fsw_mode!r} must be one of {SUPPORTED_FSW_MODES}")  # unreachable if validated

    if fsw_mode == "inertial3D":
        mod = inertial3D.inertial3D()
        mod.ModelTag = f"{tag}_inertial3D"
        mod.sigma_R0N = list(fsw_params.get("sigma_R0N", [0.0, 0.0, 0.0]))
        scSim.AddModelToTask(task_name, mod)
        return _wrap_with_att_tracking_error(scSim, task_name, tag, mod.attRefOutMsg, nav)

    if fsw_mode == "hillPoint":
        mod = hillPoint.hillPoint()
        mod.ModelTag = f"{tag}_hillPoint"
        mod.transNavInMsg.subscribeTo(nav.transOutMsg)
        scSim.AddModelToTask(task_name, mod)
        return _wrap_with_att_tracking_error(scSim, task_name, tag, mod.attRefOutMsg, nav)

    if fsw_mode == "velocityPoint":
        mod = velocityPoint.velocityPoint()
        mod.ModelTag = f"{tag}_velocityPoint"
        mod.mu = mu
        mod.transNavInMsg.subscribeTo(nav.transOutMsg)
        scSim.AddModelToTask(task_name, mod)
        return _wrap_with_att_tracking_error(scSim, task_name, tag, mod.attRefOutMsg, nav)

    if fsw_mode == "sunSafePoint":
        mod = sunSafePoint.sunSafePoint()
        mod.ModelTag = f"{tag}_sunSafePoint"
        mod.sHatBdyCmd = list(fsw_params.get("sHatBdyCmd", [0.0, 0.0, 1.0]))
        mod.minUnitMag = float(fsw_params.get("min_unit_mag", 0.1))
        mod.sunAxisSpinRate = float(fsw_params.get("sun_axis_spin_rate_rad_s", 0.0))
        mod.sunDirectionInMsg.subscribeTo(nav.attOutMsg)
        mod.imuInMsg.subscribeTo(nav.attOutMsg)  # see module docstring: same NavAttMsgPayload, both fields needed
        scSim.AddModelToTask(task_name, mod)
        return mod.attGuidanceOutMsg

    if fsw_mode == "locationPointing":
        if fsw_params.get("target_body"):
            raise FswError(
                "fsw_params['target_body'] (celestial-body pointing via locationPointing.celBodyInMsg) is "
                "schema-valid but not wired up yet in Phase 2 -- it needs an EphemerisMsg, which this "
                "checkout only produces via ephemerisConverter from a SpicePlanetStateMsg, not yet built "
                "here. Use fsw_params['target_ground_station'] instead."
            )
        target_name = fsw_params.get("target_ground_station")
        ground_location = ground_locations.get(target_name)
        if ground_location is None:  # unreachable if Scenario.validate() passed
            raise FswError(f"locationPointing target_ground_station {target_name!r} has no built GroundLocation")
        mod = locationPointing.locationPointing()
        mod.ModelTag = f"{tag}_locationPointing"
        mod.pHat_B = list(fsw_params.get("pHat_B", [0.0, 0.0, 1.0]))
        mod.useBoresightRateDamping = 1
        mod.scAttInMsg.subscribeTo(nav.attOutMsg)
        mod.scTransInMsg.subscribeTo(nav.transOutMsg)
        mod.locationInMsg.subscribeTo(ground_location.currentGroundStateOutMsg)
        scSim.AddModelToTask(task_name, mod)
        return mod.attGuidOutMsg

    raise FswError(f"fsw_mode {fsw_mode!r} is schema-valid but has no engine.fsw builder")  # unreachable


def build_vehicle_config_msg(inertia_kg_m2: List[float]):
    """The ``VehicleConfigMsg`` ``mrpFeedback`` needs for its gyroscopic
    RW-coupling term -- built with the SAME inertia as the simulated
    spacecraft hub (``sc_object.hub.IHubPntBc_B``), matching
    ``examples/scenarioAttitudeFeedbackRW.py``'s "use the same inertia in
    the FSW algorithm as in the simulation" comment (this app has no
    separate FSW-vs-truth inertia model yet, so they are always equal).
    """
    payload = messaging.VehicleConfigMsgPayload(ISCPntB_B=list(inertia_kg_m2))
    return messaging.VehicleConfigMsg().write(payload)


def build_mrp_feedback(scSim, task_name: str, tag: str, guid_out_msg, veh_config_msg, control_params: dict,
                        rw_config_msg=None, rw_speed_out_msg=None):
    """``mrpFeedback``'s "simple mode" control law (Ki < 0 disables the
    integral feedback term, matching every example's default). RW
    gyroscopic compensation is enabled automatically whenever
    ``rw_config_msg``/``rw_speed_out_msg`` are given (reaction-wheel
    actuation path); left ``None`` for the idealized-torque path.
    """
    mrp = mrpFeedback.mrpFeedback()
    mrp.ModelTag = f"{tag}_mrpFeedback"
    mrp.K = float(control_params.get("K", DEFAULT_MRP_GAINS["K"]))
    mrp.P = float(control_params.get("P", DEFAULT_MRP_GAINS["P"]))
    mrp.Ki = float(control_params.get("Ki", -1.0))
    mrp.integralLimit = float(control_params.get("integral_limit", 0.0))
    mrp.guidInMsg.subscribeTo(guid_out_msg)
    mrp.vehConfigInMsg.subscribeTo(veh_config_msg)
    if rw_config_msg is not None:
        mrp.rwParamsInMsg.subscribeTo(rw_config_msg)
        mrp.rwSpeedsInMsg.subscribeTo(rw_speed_out_msg)
    scSim.AddModelToTask(task_name, mrp)
    return mrp


def build_idealized_actuation(scSim, task_name: str, tag: str, sc_object, mrp_feedback_module):
    """Idealized direct-torque actuation: ``mrpFeedback``'s commanded
    torque is applied straight to the hub via ``extForceTorque``, with no
    actuator hardware (no saturation, no momentum buildup, no motor
    dynamics) -- the default when a spacecraft has ``fsw_mode`` set but no
    ``"reaction_wheel"`` actuators. Matches
    ``examples/scenarioAttitudeGuidance.py``.
    """
    ext = extForceTorque.ExtForceTorque()
    ext.ModelTag = f"{tag}_extForceTorque"
    ext.cmdTorqueInMsg.subscribeTo(mrp_feedback_module.cmdTorqueOutMsg)
    sc_object.addDynamicEffector(ext)
    scSim.AddModelToTask(task_name, ext)
    return ext


def _coerce_rw_kwargs(params: dict) -> dict:
    kwargs = {k: v for k, v in params.items() if k not in ("gsHat_B", "rw_type")}
    for key in _RW_FLOAT_KWARGS:
        if key in kwargs:
            kwargs[key] = float(kwargs[key])
    if "rWB_B" in kwargs:
        kwargs["rWB_B"] = [float(v) for v in kwargs["rWB_B"]]
    return kwargs


def build_reaction_wheels(scSim, task_name: str, tag: str, sc_object, actuator_configs: List):
    """Builds one reaction wheel per ``ActuatorConfig(kind="reaction_wheel")``
    entry via ``simIncludeRW.rwFactory()`` (see that module for every
    accepted ``params`` key -- ``gsHat_B`` is required by schema validation,
    everything else is optional and defaults exactly as ``rwFactory.create()``
    itself defaults). Returns ``(rw_state_effector, rw_config_msg)`` for
    :func:`build_rw_motor_torque`/:func:`build_mrp_feedback` and Vizard.

    RW device labels use ``"RW1"``, ``"RW2"``, ... (the module's own
    auto-labeling scheme) rather than ``actuator.name``, because
    ``rwFactory.create()`` hard-rejects any label longer than 5 characters
    -- ``actuator.name`` stays the identifier on the missionStudio side
    (schema, results) and is never passed into Basilisk as the RW label.
    """
    rw_factory = simIncludeRW.rwFactory()
    for actuator in actuator_configs:
        params = actuator.params
        gsHat_B = [float(v) for v in params["gsHat_B"]]
        rw_type = params.get("rw_type", "custom")
        kwargs = _coerce_rw_kwargs(params)
        rw_factory.create(rw_type, gsHat_B, **kwargs)

    rw_state_effector = reactionWheelStateEffector.ReactionWheelStateEffector()
    rw_state_effector.ModelTag = f"{tag}_reactionWheels"
    rw_factory.addToSpacecraft(rw_state_effector.ModelTag, rw_state_effector, sc_object)
    # Priority 20 > engine.service's spacecraft priority (10): higher
    # priority runs first in a Basilisk task, and the RW effector's
    # UpdateState() must publish a fresh rwSpeedOutMsg before anything else
    # in this same step reads it (mrpFeedback's rwSpeedsInMsg in
    # particular) -- the effectors -> dynamics -> sensors ordering rule
    # from examples/scenarioAttitudeFeedbackRW.py, re-derived here for
    # THIS app's own priority scheme rather than copying its literal
    # numbers (which used spacecraft priority 1, not 10).
    scSim.AddModelToTask(task_name, rw_state_effector, 20)
    rw_config_msg = rw_factory.getConfigMessage()
    return rw_factory, rw_state_effector, rw_config_msg


def build_rw_motor_torque(scSim, task_name: str, tag: str, mrp_feedback_module, rw_config_msg, rw_state_effector):
    """Maps ``mrpFeedback``'s 3D torque command onto individual RW motor
    torques (all three body axes controlled) and connects the result to
    the RW hardware's command input. Matches
    ``examples/scenarioAttitudeFeedbackRW.py``.
    """
    mod = rwMotorTorque.rwMotorTorque()
    mod.ModelTag = f"{tag}_rwMotorTorque"
    mod.controlAxes_B = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    mod.rwParamsInMsg.subscribeTo(rw_config_msg)
    mod.vehControlInMsg.subscribeTo(mrp_feedback_module.cmdTorqueOutMsg)
    scSim.AddModelToTask(task_name, mod)
    rw_state_effector.rwMotorCmdInMsg.subscribeTo(mod.rwMotorTorqueOutMsg)
    return mod


def build_ground_location(scSim, task_name: str, gs_config, central_body_radius_m: float, planet_state_out_msg,
                           sc_state_out_msgs: List):
    """One ``groundLocation.GroundLocation`` per
    :class:`schema.scenario.GroundStationConfig`. Matches
    ``examples/scenarioAttLocPoint.py``. Its ``currentGroundStateOutMsg`` is
    what ``locationPointing`` targets (:func:`build_guidance`).

    ``engine.service`` calls this BEFORE any spacecraft exist (ground
    stations don't depend on them), so ``sc_state_out_msgs`` is normally
    ``[]`` here -- access analysis (populating ``accessOutMsgs``) is added
    in a second pass once every spacecraft is built, via
    :func:`add_access_analysis`.
    """
    gl = groundLocation.GroundLocation()
    gl.ModelTag = f"groundStation_{gs_config.name}"
    gl.planetRadius = central_body_radius_m
    gl.specifyLocation(np.radians(gs_config.latitude_deg), np.radians(gs_config.longitude_deg), gs_config.altitude_m)
    gl.minimumElevation = np.radians(gs_config.min_elevation_deg)
    gl.maximumRange = -1.0  # no maximum slant range
    gl.planetInMsg.subscribeTo(planet_state_out_msg)
    for sc_state_out_msg in sc_state_out_msgs:
        gl.addSpacecraftToModel(sc_state_out_msg)
    scSim.AddModelToTask(task_name, gl)
    return gl


def add_access_analysis(ground_location, sc_objects: List) -> None:
    """Phase 3: calls ``addSpacecraftToModel`` on ``ground_location`` for
    every spacecraft in ``sc_objects``, in order -- populates
    ``ground_location.accessOutMsgs[i]`` (index == this call's position in
    ``sc_objects``, verified the same way as ``magneticFieldWMM``'s
    ``envOutMsgs`` indexing in :func:`build_magnetic_field_wmm`) for
    ``engine.service`` to record as ``hasAccess``/``slantRange``/
    ``elevation``/``azimuth`` time series. Safe to call once per ground
    station for the scenario's full spacecraft list -- each
    ``GroundLocation`` keeps its own independent ``accessOutMsgs`` index
    sequence, so calling this for several stations against the same
    ``sc_objects`` list does not cross-contaminate indices.
    """
    for sc_object in sc_objects:
        ground_location.addSpacecraftToModel(sc_object.scStateOutMsg)


def build_magnetic_field_wmm(scSim, task_name: str, planet_state_out_msg, central_body_radius_m: float):
    """One shared ``magneticFieldWMM`` environment model for the whole
    scenario's central body (Earth only -- see module docstring); every
    spacecraft with a ``magnetometer`` sensor calls
    ``addSpacecraftToModel`` on this SAME instance and reads back its own
    indexed ``envOutMsgs[i]`` entry (index == call order, verified via
    ``magneticFieldWMM``'s own unit test).
    """
    from Basilisk.utilities.supportDataTools.dataFetcher import DataFile, get_path

    mod = magneticFieldWMM.MagneticFieldWMM()
    mod.ModelTag = "magneticFieldWMM"
    mod.configureWMMFile(str(get_path(DataFile.MagneticFieldData.WMM)))
    mod.planetRadius = central_body_radius_m
    mod.planetPosInMsg.subscribeTo(planet_state_out_msg)
    scSim.AddModelToTask(task_name, mod)
    return mod


def attach_sensors(scSim, task_name: str, tag: str, sc_object, sensor_configs: List,
                    sun_state_out_msg=None, mag_field_model=None) -> Dict[str, object]:
    """Builds every :class:`schema.scenario.SensorConfig` entry for one
    spacecraft and returns ``{sensor.name: output_message}`` for
    :class:`~missionstudio.engine.results.ResultSet` recording.
    ``sun_state_out_msg``/``mag_field_model`` are ``None`` unless the
    scenario actually provides them (see ``engine.service`` for the
    preconditions -- "sun" SPICE-tracked, Earth central body respectively);
    a ``coarse_sun_sensor``/``magnetometer`` entry without the matching
    precondition raises :class:`FswError` with a specific message rather
    than silently building a sensor that would output nothing.
    """
    out_msgs: Dict[str, object] = {}
    for sensor in sensor_configs:
        params = sensor.params
        if sensor.kind == "star_tracker":
            mod = starTracker.StarTracker()
            mod.ModelTag = f"{tag}_{sensor.name}"
            mod.scStateInMsg.subscribeTo(sc_object.scStateOutMsg)
            noise_rad = np.radians(float(params.get("noise_arcsec", 0.0)) / 3600.0)
            mod.PMatrix = (noise_rad * np.eye(3)).tolist()
            scSim.AddModelToTask(task_name, mod)
            out_msgs[sensor.name] = mod.sensorOutMsg

        elif sensor.kind == "imu":
            mod = imuSensor.ImuSensor()
            mod.ModelTag = f"{tag}_{sensor.name}"
            mod.scStateInMsg.subscribeTo(sc_object.scStateOutMsg)
            gyro_noise = float(params.get("gyro_noise_rad_s", 0.0))
            accel_noise = float(params.get("accel_noise_m_s2", 0.0))
            mod.PMatrixGyro = (gyro_noise * np.eye(3)).tolist()
            mod.PMatrixAccel = (accel_noise * np.eye(3)).tolist()
            scSim.AddModelToTask(task_name, mod)
            out_msgs[sensor.name] = mod.sensorOutMsg

        elif sensor.kind == "coarse_sun_sensor":
            if sun_state_out_msg is None:
                raise FswError(
                    f"{tag}: coarse_sun_sensor {sensor.name!r} needs 'sun' to be SPICE-tracked -- add 'sun' to "
                    "gravity.third_body_perturbers (or set it as gravity.central_body)"
                )
            mod = coarseSunSensor.CoarseSunSensor()
            mod.ModelTag = f"{tag}_{sensor.name}"
            mod.nHat_B = [float(v) for v in params["nHat_B"]]  # required, schema-validated
            mod.fov = np.radians(float(params.get("fov_deg", 90.0)))
            mod.senNoiseStd = float(params.get("noise_std", 0.0))
            mod.sunInMsg.subscribeTo(sun_state_out_msg)
            mod.stateInMsg.subscribeTo(sc_object.scStateOutMsg)
            scSim.AddModelToTask(task_name, mod)
            out_msgs[sensor.name] = mod.cssDataOutMsg

        elif sensor.kind == "magnetometer":
            if mag_field_model is None:
                raise FswError(
                    f"{tag}: magnetometer {sensor.name!r} needs an Earth central body in Phase 2 "
                    "(magneticFieldWMM is only wired up for gravity.central_body == 'earth')"
                )
            mod = magnetometer.Magnetometer()
            mod.ModelTag = f"{tag}_{sensor.name}"
            noise_tesla = params.get("noise_std_tesla", [0.0, 0.0, 0.0])
            mod.senNoiseStd = [float(v) for v in noise_tesla]
            mod.stateInMsg.subscribeTo(sc_object.scStateOutMsg)
            env_index = len(mag_field_model.scStateInMsgs)
            mag_field_model.addSpacecraftToModel(sc_object.scStateOutMsg)
            mod.magInMsg.subscribeTo(mag_field_model.envOutMsgs[env_index])
            scSim.AddModelToTask(task_name, mod)
            out_msgs[sensor.name] = mod.tamDataOutMsg

        else:  # unreachable if SpacecraftConfig.validate() passed
            raise FswError(f"sensor {sensor.name!r} kind {sensor.kind!r} has no engine.fsw builder")

    return out_msgs
