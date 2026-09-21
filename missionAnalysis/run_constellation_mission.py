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
Multi-year Earth-observation constellation mission-analysis simulation,
built on Basilisk's orbital-dynamics stack only (no attitude/GNC loop --
see ``README.md`` for the full architecture rationale).

Constellation
-------------
Built from ``mission_config.SATELLITES`` (see that module's docstring, or
just run ``setup_wizard.py``):

* An SSO plane of N satellites (N configurable, including 0) sharing one
  sun-synchronous frozen orbit, evenly phased in mean anomaly, each with
  independent altitude/SMA station-keeping and, for N > 1, in-plane
  phasing ("constellation-keeping") against a chief satellite.
* Any number of additional standalone satellites, each independent (no
  phasing partner), with their own inclination/RAAN/altitude/eccentricity.

The default configuration (no ``constellation_setup.json`` present) is 2
SSO satellites at 570 km altitude, i=97.6704 deg, e=0.0011, AOP=90 deg,
RAAN tuned for ~10:30 LTDN, 180 deg apart, plus 1 standalone 53 deg
-inclination satellite at the same altitude.

Perturbations modeled: Earth spherical-harmonics gravity (degree/order per
``mission_config.EARTH_GRAV_DEGREE``), Sun/Moon third-body point-mass
gravity via SPICE, atmospheric drag (NRLMSISE-00 driven by a multi-year
synthetic space-weather profile -- see
``generate_space_weather_placeholder.py``), cannonball SRP with eclipse
shadowing, and Earth-rotation-relative drag velocity (zeroWindModel).
Relativistic (Schwarzschild) correction is implemented but OFF by default;
see ``README.md``.

Automated maintenance: independent altitude/SMA station-keeping per
satellite and in-plane phasing ("constellation-keeping") within any
multi-satellite plane, both via :mod:`constellation_controllers`.

Communications: per-satellite EO data generation, on-board storage, and
ground-station downlink (see :mod:`communications`), driving Vizard's
antenna-ring visualization when ``--vizard``/``--vizard-save`` is used --
purple rings while a satellite is collecting data, green rings while it is
downlinking, with an on-screen storage-level panel rising and falling to
match.

Usage::

    python3 run_constellation_mission.py [--years 5] [--no-plots]
    python3 run_constellation_mission.py --years 0.05 --vizard-save mission_playback

Requires a built Basilisk Python package (``pip install .`` from the repo
root, or the Basilisk Docker image) -- this script cannot run against an
unbuilt checkout. Vizard visualization (``--vizard``/``--vizard-save``) also
requires a Vizard-enabled Basilisk build; see the "Optional Vizard
visualization" comment in ``build_simulation()`` for why a short ``--years``
window is recommended over a full 5-year Vizard run.
"""

import argparse
import os

import numpy as np

import mission_config as mc
from constellation_controllers import (
    AltitudeKeepingController,
    PhasingKeepingController,
    SeparationSchedule,
)
import communications

from Basilisk.architecture import messaging
from Basilisk.simulation import (
    spacecraft,
    dragDynamicEffector,
    msisAtmosphere,
    spaceWeatherData,
    zeroWindModel,
    radiationPressure,
    eclipse,
    extForceTorque,
    svIntegrators,
    vizInterface,
)
from Basilisk.utilities import (
    SimulationBaseClass,
    macros,
    orbitalMotion,
    simIncludeGravBody,
    simHelpers,
    vizSupport,
)
from Basilisk.utilities.supportDataTools.dataFetcher import get_path, DataFile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SPACE_WEATHER_CSV = os.path.join(SCRIPT_DIR, "data", "placeholder_space_weather.csv")


def _mean_anom_to_rv(mu, sat):
    """Build (r_N, v_N) [m], [m/s] from a mission_config satellite dict,
    converting the given mean anomaly to true anomaly via Kepler's equation.
    """
    oe = orbitalMotion.ClassicElements()
    oe.a = sat["a_m"]
    oe.e = sat["e"]
    oe.i = np.radians(sat["i_deg"])
    oe.Omega = np.radians(sat["raan_deg"])
    oe.omega = np.radians(sat["aop_deg"])
    eccAnom = orbitalMotion.M2E(np.radians(sat["mean_anom_deg"]), sat["e"])
    oe.f = orbitalMotion.E2f(eccAnom, sat["e"])
    rN, vN = orbitalMotion.elem2rv(mu, oe)
    return rN, vN


def build_simulation(mission_years=mc.MISSION_DURATION_YEARS, earth_grav_degree=mc.EARTH_GRAV_DEGREE,
                      enable_relativistic_correction=False, enable_vizard=False,
                      viz_save_file=None, viz_live_stream=False):
    """Assemble the full Basilisk simulation. Returns a dict of every object
    a caller might want a handle on (sim, per-satellite objects, controllers,
    recorders) for running and post-processing.

    Args:
        enable_vizard: if True, wire up vizSupport.enableUnityVisualization(),
            including the per-satellite comm-rings/data-storage-panel
            visualization from communications.py (see the comment near the
            call site for the frame-rate/blocking-call caveats specific to
            a multi-year run).
        viz_save_file: path (without extension) to write a Vizard playback
            file to; None (default) writes nothing.
        viz_live_stream: forwarded to enableUnityVisualization(); see the
            docstring note on why this is of limited use for a 5-year run.
    """
    scSim = SimulationBaseClass.SimBaseClass()
    scSim.SetProgressBar(True)

    # Two processes at two different rates, per the architecture writeup:
    # a FAST dynamics process (gravity/drag/SRP/eclipse/spacecraft
    # integration) and a COARSE control process (the Python station-keeping
    # / phasing controllers). Decoupling them is what keeps a 5-year x
    # 3-spacecraft run tractable: the expensive fine-grained numerical
    # integration runs entirely in compiled C++ between control ticks, and
    # the (comparatively expensive, per-call) Python controller code only
    # runs a few hundred thousand times total instead of once per dynamics
    # step.
    dynProcess = scSim.CreateNewProcess("dynProcess", priority=100)
    ctrlProcess = scSim.CreateNewProcess("ctrlProcess", priority=90)

    dynTaskName = "dynTask"
    ctrlTaskName = "ctrlTask"
    dynProcess.addTask(scSim.CreateNewTask(dynTaskName, macros.sec2nano(mc.DYNAMICS_TASK_RATE_S)))
    ctrlProcess.addTask(scSim.CreateNewTask(ctrlTaskName, macros.sec2nano(mc.CONTROL_TASK_RATE_S)))

    # ------------------------------------------------------------------
    # Gravity bodies + SPICE (Earth spherical harmonics, Sun/Moon third
    # -body point-mass gravity)
    # ------------------------------------------------------------------
    gravFactory = simIncludeGravBody.gravBodyFactory()
    bodyNames = ["earth", "sun", "moon"]
    gravBodies = gravFactory.createBodies(bodyNames)
    earth = gravBodies["earth"]
    earth.isCentralBody = True
    ggm03s_path = get_path(DataFile.LocalGravData.GGM03S)
    earth.useSphericalHarmonicsGravityModel(str(ggm03s_path), earth_grav_degree)
    mu = earth.mu

    spiceObject = gravFactory.createSpiceInterface(time=mc.EPOCH_SPICE_STRING, epochInMsg=True)
    spiceObject.zeroBase = "Earth"
    scSim.AddModelToTask(dynTaskName, spiceObject, 500)
    # Moon needs no message-level wiring below: gravFactory.addBodiesTo()
    # (called per spacecraft) already includes it as a third-body point-mass
    # gravity perturber for every satellite.
    earthIdx, sunIdx = bodyNames.index("earth"), bodyNames.index("sun")

    # ------------------------------------------------------------------
    # Shared environment modules: space weather -> MSIS atmosphere, wind
    # (Earth-rotation-relative drag velocity), eclipse
    # ------------------------------------------------------------------
    swModule = spaceWeatherData.SpaceWeatherData()
    swModule.ModelTag = "spaceWeatherData"
    swModule.loadSpaceWeatherFile(SPACE_WEATHER_CSV)
    swModule.epochInMsg.subscribeTo(gravFactory.epochMsg)
    scSim.AddModelToTask(dynTaskName, swModule, 400)

    atmoModule = msisAtmosphere.MsisAtmosphere()
    atmoModule.ModelTag = "msisAtmosphere"
    atmoModule.epochInMsg.subscribeTo(gravFactory.epochMsg)
    atmoModule.planetPosInMsg.subscribeTo(spiceObject.planetStateOutMsgs[earthIdx])
    for msgIndex in range(23):
        atmoModule.swDataInMsgs[msgIndex].subscribeTo(swModule.swDataOutMsgs[msgIndex])
    scSim.AddModelToTask(dynTaskName, atmoModule, 390)

    windModel = zeroWindModel.ZeroWindModel()
    windModel.ModelTag = "zeroWind"
    windModel.planetPosInMsg.subscribeTo(spiceObject.planetStateOutMsgs[earthIdx])
    scSim.AddModelToTask(dynTaskName, windModel, 380)

    eclipseObject = eclipse.Eclipse()
    eclipseObject.ModelTag = "eclipse"
    eclipseObject.sunInMsg.subscribeTo(spiceObject.planetStateOutMsgs[sunIdx])
    eclipseObject.addPlanetToModel(spiceObject.planetStateOutMsgs[earthIdx])
    scSim.AddModelToTask(dynTaskName, eclipseObject, 370)

    # ------------------------------------------------------------------
    # Per-satellite spacecraft + effectors
    # ------------------------------------------------------------------
    satellites = {}
    for satIndex, satDef in enumerate(mc.SATELLITES):
        name = satDef["name"]

        scObject = spacecraft.Spacecraft()
        scObject.ModelTag = name
        scObject.hub.mHub = mc.DRY_MASS_KG + mc.PROPELLANT_MASS_BOL_KG  # [kg] BOL wet mass
        # Inertia is a required hub property but is not exercised by this
        # orbital-dynamics-only study (attitude is left uncontrolled and is
        # not evaluated) -- a generic small-sat placeholder is used.
        scObject.hub.IHubPntBc_B = simHelpers.np2EigenMatrix3d([40.0, 0.0, 0.0, 0.0, 40.0, 0.0, 0.0, 0.0, 30.0])

        integratorObject = svIntegrators.svIntegratorRKF78(scObject)
        scObject.setIntegrator(integratorObject)

        gravFactory.addBodiesTo(scObject)

        rN, vN = _mean_anom_to_rv(mu, satDef)
        scObject.hub.r_CN_NInit = rN  # [m]
        scObject.hub.v_CN_NInit = vN  # [m/s]

        dragEffector = dragDynamicEffector.DragDynamicEffector()
        dragEffector.ModelTag = f"{name}Drag"
        dragEffector.coreParams.projectedArea = mc.DRAG_AREA_M2
        dragEffector.coreParams.dragCoeff = mc.DRAG_COEFF
        scObject.addDynamicEffector(dragEffector)
        atmoModule.addSpacecraftToModel(scObject.scStateOutMsg)
        windModel.addSpacecraftToModel(scObject.scStateOutMsg)
        dragEffector.atmoDensInMsg.subscribeTo(atmoModule.envOutMsgs[satIndex])
        dragEffector.windVelInMsg.subscribeTo(windModel.envOutMsgs[satIndex])

        srpEffector = radiationPressure.RadiationPressure()
        srpEffector.ModelTag = f"{name}Srp"
        srpEffector.area = mc.SRP_AREA_M2
        srpEffector.coefficientReflection = mc.SRP_COEFF
        scObject.addDynamicEffector(srpEffector)
        srpEffector.sunEphmInMsg.subscribeTo(spiceObject.planetStateOutMsgs[sunIdx])
        eclipseObject.addSpacecraftToModel(scObject.scStateOutMsg)
        srpEffector.sunEclipseInMsg.subscribeTo(eclipseObject.eclipseOutMsgs[satIndex])

        thrustEffector = extForceTorque.ExtForceTorque()
        thrustEffector.ModelTag = f"{name}Thrust"
        scObject.addDynamicEffector(thrustEffector)

        # Priority: environment/effector UpdateState() calls (which sample
        # input messages) run before the spacecraft integrates this tick, so
        # every dynamics step uses the freshest available atmosphere/eclipse
        # data rather than data that is one macro-step stale.
        scSim.AddModelToTask(dynTaskName, dragEffector, 100)
        scSim.AddModelToTask(dynTaskName, srpEffector, 100)
        scSim.AddModelToTask(dynTaskName, thrustEffector, 100)
        scSim.AddModelToTask(dynTaskName, scObject, 10)

        relCorrection = None
        if enable_relativistic_correction:
            relCorrection = _add_relativistic_correction(scSim, dynTaskName, ctrlTaskName, scObject, mu)

        satellites[name] = dict(
            index=satIndex,
            definition=satDef,
            scObject=scObject,
            dragEffector=dragEffector,
            srpEffector=srpEffector,
            thrustEffector=thrustEffector,
            relCorrection=relCorrection,
        )

    # ------------------------------------------------------------------
    # Communications: EO data generation, on-board storage, ground downlink
    # (see communications.py -- this is what drives the Vizard "comm rings"
    # visualization below).
    # ------------------------------------------------------------------
    groundStations = communications.build_ground_stations(scSim, dynTaskName, spiceObject, earthIdx, satellites)
    comms = communications.build_communications(scSim, dynTaskName, ctrlTaskName, satellites, groundStations)
    for name, sat in satellites.items():
        comms[name]["instrumentGate"].eclipseInMsg.subscribeTo(eclipseObject.eclipseOutMsgs[sat["index"]])

    # ------------------------------------------------------------------
    # Controllers (coarse control task). Each satellite gets its own
    # altitude/SMA station-keeping controller, sized from ITS OWN orbit
    # (different planes/satellites may have different altitudes -- see
    # mission_config.SATELLITES). Satellites sharing a "plane" (built by
    # mission_config._build_satellites(): the SSO plane's N evenly-phased
    # satellites, or a lone standalone satellite in a singleton plane of
    # its own) additionally get one PhasingKeepingController per follower,
    # referenced to the first satellite in that plane (the chief, left
    # unmaneuvered for phasing) at that follower's assigned mean-anomaly
    # offset. A plane with only one member gets no phasing controller.
    # ------------------------------------------------------------------
    def _orbit_period_s(a_m):
        return 2.0 * np.pi * np.sqrt(a_m**3 / mu)

    altControllers = {}
    for name, sat in satellites.items():
        satDef = sat["definition"]
        ctrl = AltitudeKeepingController(
            name=f"{name}AltCtrl",
            mu=mu,
            nominal_alt_m=satDef["a_m"] - earth.radEquator,
            deadband_m=mc.ALT_DEADBAND_M,
            r_planet_m=earth.radEquator,
            thrust_n=mc.THRUST_N,
            isp_s=mc.ISP_S,
            dry_mass_kg=mc.DRY_MASS_KG,
            propellant_kg=mc.PROPELLANT_MASS_BOL_KG,
            orbit_period_s=_orbit_period_s(satDef["a_m"]),
            eclipse_sunlit_threshold=mc.ECLIPSE_SUNLIT_THRESHOLD,
        )
        ctrl.scStateInMsg.subscribeTo(sat["scObject"].scStateOutMsg)
        ctrl.eclipseInMsg.subscribeTo(eclipseObject.eclipseOutMsgs[sat["index"]])
        ctrl.extForceEffector = sat["thrustEffector"]
        ctrl.scObject = sat["scObject"]
        scSim.AddModelToTask(ctrlTaskName, ctrl)
        altControllers[name] = ctrl

    planeMembers = {}
    for name, sat in satellites.items():
        planeMembers.setdefault(sat["definition"]["plane"], []).append(name)

    phaseControllers = {}
    for planeName, members in planeMembers.items():
        if len(members) < 2:
            continue
        chiefName = members[0]
        chief = satellites[chiefName]
        chiefMeanAnomDeg = chief["definition"]["mean_anom_deg"]
        chiefA_m = chief["definition"]["a_m"]
        for followerName in members[1:]:
            follower = satellites[followerName]
            schedule = follower["definition"].get("schedule")
            if schedule is not None:
                # Time-varying target separation: steps through
                # schedule["distances_km"] every schedule["interval_days"],
                # holding at (or looping back to) the last entry -- see
                # SeparationSchedule in constellation_controllers.py.
                separationSchedule = SeparationSchedule(
                    distances_km=schedule["distances_km"],
                    interval_days=schedule["interval_days"],
                    semi_major_axis_m=chiefA_m,
                    loop=schedule.get("loop", False),
                )
            else:
                # No schedule assigned (custom satellites, or an SSO plane
                # with more followers than follower_schedules entries) --
                # hold a fixed target separation for the whole mission,
                # taken from the satellites' assigned mean-anomaly offset.
                fixedSeparationRad = np.radians(
                    (follower["definition"]["mean_anom_deg"] - chiefMeanAnomDeg) % 360.0
                )
                separationSchedule = SeparationSchedule(
                    distances_km=[fixedSeparationRad * chiefA_m / 1000.0],
                    interval_days=0.0,
                    semi_major_axis_m=chiefA_m,
                )
            phaseCtrl = PhasingKeepingController(
                name=f"{followerName}PhaseCtrl",
                mu=mu,
                nominal_a_m=chiefA_m,
                separation_schedule=separationSchedule,
                tolerance_fraction=mc.PHASING_TOLERANCE_FRACTION,
                restore_tolerance_fraction=mc.PHASING_RESTORE_TOLERANCE_FRACTION,
                correction_window_days=mc.PHASING_CORRECTION_WINDOW_DAYS,
                max_drift_days=mc.PHASING_MAX_DRIFT_DAYS,
                max_delta_a_m=mc.PHASING_MAX_DELTA_A_M,
                thrust_n=mc.THRUST_N,
                isp_s=mc.ISP_S,
                dry_mass_kg=mc.DRY_MASS_KG,
                propellant_kg=mc.PROPELLANT_MASS_BOL_KG,
                orbit_period_s=_orbit_period_s(chiefA_m),
                eclipse_sunlit_threshold=mc.ECLIPSE_SUNLIT_THRESHOLD,
            )
            phaseCtrl.scStateInMsgA.subscribeTo(chief["scObject"].scStateOutMsg)
            phaseCtrl.scStateInMsgB.subscribeTo(follower["scObject"].scStateOutMsg)
            phaseCtrl.eclipseInMsgB.subscribeTo(eclipseObject.eclipseOutMsgs[follower["index"]])
            phaseCtrl.extForceEffectorB = follower["thrustEffector"]
            phaseCtrl.scObjectB = follower["scObject"]
            # Thruster-arbitration link: phasing pauses while the
            # follower's own altitude controller is actively reboosting
            # (see constellation_controllers.py).
            phaseCtrl.altitudeControllerB = altControllers[followerName]
            scSim.AddModelToTask(ctrlTaskName, phaseCtrl)
            phaseControllers[followerName] = phaseCtrl

    # ------------------------------------------------------------------
    # Coarse state recorders for trajectory-level plots/exports (separate
    # from the controllers' own decimated Python-side telemetry).
    # ------------------------------------------------------------------
    logTaskName = "logTask"
    logProcess = scSim.CreateNewProcess("logProcess", priority=80)
    logRate_s = 3600.0  # [s] hourly trajectory samples over 5 years (~43800 pts/sat)
    logProcess.addTask(scSim.CreateNewTask(logTaskName, macros.sec2nano(logRate_s)))
    stateRecorders = {}
    storageRecorders = {}
    for name, sat in satellites.items():
        recorder = sat["scObject"].scStateOutMsg.recorder()
        scSim.AddModelToTask(logTaskName, recorder)
        stateRecorders[name] = recorder

        storageRecorder = comms[name]["storageUnit"].storageUnitDataOutMsg.recorder()
        scSim.AddModelToTask(logTaskName, storageRecorder)
        storageRecorders[name] = storageRecorder

    # ------------------------------------------------------------------
    # Optional Vizard visualization. The vizInterface module is added to
    # the same hourly logTask as the state recorders above, NOT the fast
    # (60 s) dynamics task: a 5-year run at 60 s would be ~2.6M frames per
    # spacecraft, which is impractical to write out or play back. Hourly
    # sampling (~43800 frames/spacecraft over 5 years) is coarse compared to
    # Vizard's usual few-orbit GNC-video use case, but is enough to inspect
    # overall constellation/phasing geometry and ground tracks. For a
    # smooth, detailed playback, run a short window instead (e.g.
    # ``--years 0.05 --vizard``).
    #
    # This also means "live" Vizard streaming isn't really meaningful here:
    # the entire multi-year run executes as one blocking call into compiled
    # Basilisk code (see the fast/coarse task-rate split above), so there is
    # no wall-clock-paced moment for a live viewer to watch it happen frame
    # by frame. ``viz_save_file``, not ``liveStream``, is the intended way
    # to use this: it writes a "<viz_save_file>_UnityViz.bin" playback file
    # (under a _VizFiles/ subdirectory) to open in the Vizard app after the
    # run completes.
    viz = None
    if enable_vizard:
        if not vizSupport.vizFound:
            print("vizSupport: this Basilisk build does not include the Vizard interface; skipping.")
        else:
            if viz_save_file is not None and not os.path.isabs(viz_save_file) and not os.path.dirname(viz_save_file):
                # vizSupport.enableUnityVisualization() builds the output
                # path as f"{os.path.dirname(saveFile)}/_VizFiles/...", so a
                # bare name with no directory component (dirname == "")
                # silently resolves to an ABSOLUTE path at the filesystem
                # root ("/_VizFiles/...") -- which fails to write on any
                # normal system. Anchor it to the current directory instead.
                viz_save_file = os.path.abspath(viz_save_file)
            scObjList = [sat["scObject"] for sat in satellites.values()]
            orbitColors = [vizSupport.toRGBA255(c) for c in ("teal", "orange", "purple")]

            # Comm rings + data-storage panel per satellite: a Transceiver
            # fed by BOTH the EO instrument's and the downlink transmitter's
            # nodeDataOutMsg reproduces the video's two-color behavior --
            # purple rings while the instrument reports a positive baud
            # rate (data being generated), green rings while the
            # transmitter reports a negative one (data being sent) -- see
            # communications.py's module docstring and vizInterface.cpp's
            # sending/receiving convention.
            transceiverList = []
            genericStorageList = []
            for name, sat in satellites.items():
                comm = comms[name]

                transceiver = vizInterface.Transceiver()
                transceiver.r_SB_B = [0.0, 0.0, 0.0]  # [m] PLACEHOLDER antenna location (no bus layout defined)
                transceiver.fieldOfView = np.radians(80.0)  # [rad] PLACEHOLDER antenna half-cone angle
                transceiver.normalVector = [1.0, 0.0, 0.0]
                transceiver.label = "Comm"
                instrumentStateInMsg = messaging.DataNodeUsageMsgReader()
                instrumentStateInMsg.subscribeTo(comm["instrument"].nodeDataOutMsg)
                transmitterStateInMsg = messaging.DataNodeUsageMsgReader()
                transmitterStateInMsg.subscribeTo(comm["transmitter"].nodeDataOutMsg)
                transceiver.transceiverStateInMsgs.push_back(instrumentStateInMsg)
                transceiver.transceiverStateInMsgs.push_back(transmitterStateInMsg)

                storagePanel = vizInterface.GenericStorage()
                storagePanel.label = "Data Storage"
                storagePanel.type = "Hard Drive"
                storagePanel.units = "bits"
                storagePanel.color = vizInterface.IntVector(
                    vizSupport.toRGBA255("blue") + vizSupport.toRGBA255("red")
                )
                storagePanel.thresholds = vizInterface.IntVector([90])
                storageStateInMsg = messaging.DataStorageStatusMsgReader()
                storageStateInMsg.subscribeTo(comm["storageUnit"].storageUnitDataOutMsg)
                storagePanel.dataStorageStateInMsg = storageStateInMsg

                transceiverList.append([transceiver])
                genericStorageList.append([storagePanel])

            viz = vizSupport.enableUnityVisualization(
                scSim, logTaskName, scObjList,
                saveFile=viz_save_file,
                oscOrbitColorList=orbitColors,
                liveStream=viz_live_stream,
                transceiverList=transceiverList,
                genericStorageList=genericStorageList,
            )
            viz.settings.orbitLinesOn = 1  # osculating orbit lines relative to the parent body (Earth)
            viz.settings.spacecraftCSon = -1  # no attitude is modeled/controlled here; hide the (meaningless) body frame
            viz.settings.showTransceiverLabels = 1
            for name, sat in satellites.items():
                vizSupport.setInstrumentGuiSetting(viz, spacecraftName=sat["scObject"].ModelTag,
                                                   showGenericStoragePanel=True)

            for gsDef, gs in zip(mc.GROUND_STATIONS, [g["module"] for g in groundStations]):
                vizSupport.addLocation(
                    viz,
                    stationName=gsDef["name"],
                    parentBodyName=earth.displayName,
                    r_GP_P=simHelpers.EigenVector3d2list(gs.r_LP_P_Init),
                    fieldOfView=np.radians(2.0 * (90.0 - gsDef["min_elevation_deg"])),
                    color="pink",
                    range=mc.GROUND_STATION_MAX_RANGE_M,
                )

    scSim.InitializeSimulation()

    stopTimeS = mission_years * 365.25 * 86400.0  # [s]
    scSim.ConfigureStopTime(macros.sec2nano(stopTimeS))

    return dict(
        scSim=scSim,
        mu=mu,
        earth=earth,
        gravFactory=gravFactory,
        satellites=satellites,
        altControllers=altControllers,
        phaseControllers=phaseControllers,
        groundStations=groundStations,
        comms=comms,
        stateRecorders=stateRecorders,
        storageRecorders=storageRecorders,
        stopTimeS=stopTimeS,
        viz=viz,
        viz_save_file=viz_save_file,  # normalized (see the os.path.abspath note above)
    )


def _add_relativistic_correction(scSim, dynTaskName, ctrlTaskName, scObject, mu):
    """OPTIONAL first-post-Newtonian (Schwarzschild) correction, off by
    default -- see README.md for why. The Python module (coarse control
    cadence) computes the correction and writes it, held constant between
    ticks -- the same zero-order-hold approximation used for thrust, which
    is reasonable here since this term varies far more slowly than the
    control cadence. The extForceTorque effector itself lives on the fast
    dynamics task so the integrator samples it every fine step.
    """
    from Basilisk.architecture import sysModel, messaging

    class _RelativisticCorrection(sysModel.SysModel):
        C_LIGHT = 299792458.0  # [m/s]

        def __init__(self, mu):
            super().__init__()
            self.ModelTag = "relCorrection"
            self.scStateInMsg = messaging.SCStatesMsgReader()
            self.forceEffector = None
            self.scObject = None  # used only to read the current total mass
            self.mu = mu

        def Reset(self, CurrentSimNanos):
            if self.forceEffector is not None:
                self.forceEffector.extForce_N = [0.0, 0.0, 0.0]

        def UpdateState(self, CurrentSimNanos):
            state = self.scStateInMsg()
            r = np.array(state.r_BN_N)
            v = np.array(state.v_BN_N)
            rMag = np.linalg.norm(r)
            c2 = self.C_LIGHT**2
            # Standard 1PN geodesic (Schwarzschild) acceleration, IERS Conventions form:
            accel = (self.mu / (c2 * rMag**3)) * (
                (4.0 * self.mu / rMag - v.dot(v)) * r + 4.0 * r.dot(v) * v
            )  # [m/s^2]
            if self.forceEffector is not None:
                # extForce_N is a force in [N]; Basilisk divides by the
                # spacecraft's actual current mass when converting effector
                # forces to acceleration, so the acceleration computed above
                # must be re-multiplied by that same mass here.
                currentMass = self.scObject.hub.mHub if self.scObject is not None else 0.0  # [kg]
                self.forceEffector.extForce_N = (accel * currentMass).tolist()

    relModule = _RelativisticCorrection(mu)
    relModule.scStateInMsg.subscribeTo(scObject.scStateOutMsg)
    relModule.scObject = scObject
    relEffector = extForceTorque.ExtForceTorque()
    relEffector.ModelTag = f"{scObject.ModelTag}RelCorrection"
    scObject.addDynamicEffector(relEffector)
    relModule.forceEffector = relEffector
    scSim.AddModelToTask(ctrlTaskName, relModule)
    scSim.AddModelToTask(dynTaskName, relEffector, 100)
    return dict(module=relModule, effector=relEffector)


def run(mission_years=mc.MISSION_DURATION_YEARS, make_plots=True, enable_vizard=False,
        viz_save_file=None, viz_live_stream=False):
    sim = build_simulation(mission_years=mission_years, enable_vizard=enable_vizard,
                            viz_save_file=viz_save_file, viz_live_stream=viz_live_stream)
    scSim = sim["scSim"]

    scSim.ExecuteSimulation()

    print("Simulation complete.")
    if sim["viz"] is not None and sim["viz_save_file"]:
        savedTo = sim["viz_save_file"]
        binName = os.path.basename(savedTo) + "_UnityViz.bin"
        print(f"Wrote Vizard playback file: {os.path.dirname(savedTo)}/_VizFiles/{binName}")
        print("Open it in the Vizard app (Select button on the startup panel, or "
              f"`open /Applications/Vizard.app --args -loadFile {os.path.dirname(savedTo)}/_VizFiles/{binName}` on macOS).")
    for name, ctrl in sim["altControllers"].items():
        # burnLog is decimated telemetry (see AltitudeKeepingController), so
        # this duty cycle is an approximation, not an exact on-time fraction.
        dutyCyclePct = 100.0 * np.mean(ctrl.burnLog) if ctrl.burnLog else 0.0
        finalDv = ctrl.deltaVLog[-1] if ctrl.deltaVLog else 0.0
        finalProp = ctrl.propellantLog[-1] if ctrl.propellantLog else mc.PROPELLANT_MASS_BOL_KG
        print(f"  {name}: ~{dutyCyclePct:.1f}% reboost duty cycle, cumulative station-keeping dV "
              f"~{finalDv:.2f} m/s, propellant remaining ~{finalProp:.3f} kg")

    for name, phaseCtrl in sim["phaseControllers"].items():
        finalDvPhase = phaseCtrl.deltaVLog[-1] if phaseCtrl.deltaVLog else 0.0
        print(f"  Phasing ({name}): cumulative phasing dV ~{finalDvPhase:.2f} m/s")

    for name, recorder in sim["storageRecorders"].items():
        if len(recorder.storageLevel) == 0:
            continue
        finalLevel = recorder.storageLevel[-1]
        peakLevel = np.max(recorder.storageLevel)
        print(f"  {name}: data on-board at end of run ~{finalLevel / 8e9:.2f} GB "
              f"(peak ~{peakLevel / 8e9:.2f} GB of {mc.DATA_STORAGE_CAPACITY_BITS / 8e9:.0f} GB capacity)")

    if make_plots:
        _make_plots(sim)

    return sim


def _make_plots(sim):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(9, 9.5), sharex=True)
    plottedNominalAlts = set()
    for name, ctrl in sim["altControllers"].items():
        if not ctrl.tLog:
            continue
        tDays = np.array(ctrl.tLog) / 86400.0
        line, = axes[0].plot(tDays, np.array(ctrl.smoothAltLog) / 1000.0, label=name)
        # Each satellite may have its own nominal altitude/deadband (see
        # build_simulation()); draw a reference line per unique value
        # rather than assuming one shared altitude for the whole plot.
        key = round(ctrl.nominalAlt, 3)
        if key not in plottedNominalAlts:
            plottedNominalAlts.add(key)
            axes[0].axhline(ctrl.nominalAlt / 1000.0, color=line.get_color(), linestyle="--", linewidth=0.8)
            axes[0].axhline((ctrl.nominalAlt - ctrl.deadband) / 1000.0, color=line.get_color(), linestyle=":",
                             linewidth=0.8)
    axes[0].set_ylabel("smoothed altitude [km]\n(dashed: nominal, dotted: deadband)")
    axes[0].legend(fontsize=8)

    # No fixed +/-tolerance reference line here: the phasing tolerance is a
    # fraction of each follower's own (possibly time-varying, per
    # SeparationSchedule) target separation, so it differs by follower and
    # by time rather than being one shared degree value.
    for name, phaseCtrl in sim["phaseControllers"].items():
        if phaseCtrl.tLog:
            tDays = np.array(phaseCtrl.tLog) / 86400.0
            axes[1].plot(tDays, phaseCtrl.errorDegLog, label=name)
    axes[1].set_ylabel("mean-anomaly\nphasing error [deg]")
    if sim["phaseControllers"]:
        axes[1].legend(fontsize=8)

    # Hourly-sampled storage level (see build_simulation()'s comment on the
    # logTask rate): this shows the mission-long trend, not individual
    # downlink passes -- rerun with a short --years window to see those.
    for name, recorder in sim["storageRecorders"].items():
        if len(recorder.times()) == 0:
            continue
        tDays = recorder.times() * macros.NANO2SEC / 86400.0
        axes[2].plot(tDays, recorder.storageLevel / 8.0e9, label=name)
    axes[2].axhline(mc.DATA_STORAGE_CAPACITY_BITS / 8.0e9, color="k", linestyle="--", linewidth=0.8, label="capacity")
    axes[2].set_ylabel("on-board data [GB]")
    axes[2].set_xlabel("mission elapsed time [days]")
    axes[2].legend(fontsize=8)

    fig.tight_layout()
    outPath = os.path.join(SCRIPT_DIR, "mission_summary.png")
    fig.savefig(outPath, dpi=150)
    print(f"Saved summary plot to {outPath}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=float, default=mc.MISSION_DURATION_YEARS,
                         help="mission duration to simulate [years]")
    parser.add_argument("--no-plots", action="store_true", help="skip matplotlib summary plot")
    parser.add_argument("--vizard", action="store_true",
                         help="wire up vizSupport.enableUnityVisualization() (requires a Vizard-enabled Basilisk build)")
    parser.add_argument("--vizard-save", type=str, default=None, metavar="PATH",
                         help="write a Vizard playback file (implies --vizard); e.g. --vizard-save mission_playback")
    parser.add_argument("--vizard-live", action="store_true",
                         help="also enable Vizard liveStream (implies --vizard); of limited use for a multi-year "
                              "blocking run -- see the enable_vizard note in build_simulation()")
    args = parser.parse_args()

    run(
        mission_years=args.years,
        make_plots=not args.no_plots,
        enable_vizard=args.vizard or args.vizard_save is not None or args.vizard_live,
        viz_save_file=args.vizard_save,
        viz_live_stream=args.vizard_live,
    )
