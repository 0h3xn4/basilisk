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
Per-satellite EO data generation, on-board storage, and ground-station
downlink -- Basilisk's onboard-data-handling stack (:ref:`simpleInstrument`,
:ref:`partitionedStorageUnit`, :ref:`spaceToGroundTransmitter`,
:ref:`GroundLocation`), wired the same way as :ref:`scenarioGroundDownlink`.

This is what drives the Vizard "comm rings" visualization: a spacecraft's
antenna shows purple rings while its data-node message reports a positive
baud rate (``DataNodeBase.nodeBaudRate``, "receiving" per
``vizInterface.cpp``) and green rings while it reports negative ("sending").
The EO instrument here always reports a positive rate when active (data
being generated/collected) and the downlink transmitter always reports a
negative rate (data being consumed/sent), so pushing both of their
``nodeDataOutMsg`` messages into one Vizard ``Transceiver``'s
``transceiverStateInMsgs`` reproduces exactly the two-color behavior
described in the feature request: purple = collecting data, green =
downlinking it, with the on-screen storage panel rising and falling to
match.

See ``README.md`` for the full placeholder list (no EO payload data rate,
downlink link budget, storage capacity, or ground network was specified in
the mission statement).
"""

import numpy as np
from Basilisk.architecture import sysModel, messaging
from Basilisk.simulation import (
    groundLocation,
    simpleInstrument,
    partitionedStorageUnit,
    spaceToGroundTransmitter,
)
import mission_config as mc


class InstrumentEclipseGate(sysModel.SysModel):
    """Turns a :ref:`simpleInstrument` on/off with sunlight.

    A real EO imaging payload only collects useful data over illuminated
    ground, so the instrument's data-generation rate is gated by the same
    eclipse shadow factor the station-keeping controllers already use for
    thrust gating (see ``constellation_controllers.py``). This runs on the
    coarse control task, like the other controllers -- see README.md for
    why that split keeps a 5-year run tractable.
    """

    def __init__(self, name, instrument, baud_rate_bps, eclipse_sunlit_threshold=0.99):
        super().__init__()
        self.ModelTag = name
        self.eclipseInMsg = messaging.EclipseMsgReader()
        self.instrument = instrument
        self.baudRate = baud_rate_bps  # [bit/s]
        self.sunlitThreshold = eclipse_sunlit_threshold  # [-]

    def Reset(self, CurrentSimNanos):
        self.instrument.nodeBaudRate = 0.0

    def UpdateState(self, CurrentSimNanos):
        inSun = True
        if self.eclipseInMsg.isLinked():
            inSun = self.eclipseInMsg().shadowFactor > self.sunlitThreshold
        self.instrument.nodeBaudRate = self.baudRate if inSun else 0.0


def build_ground_stations(scSim, dynTaskName, spiceObject, earthIdx, satellites):
    """Create the placeholder ground network and register every satellite
    with each ground station (so each gets its own ``accessOutMsgs`` entry,
    in the same order the satellites were added -- matching ``sat["index"]``
    from ``run_constellation_mission.py``).
    """
    groundStations = []
    for gsDef in mc.GROUND_STATIONS:
        gs = groundLocation.GroundLocation()
        gs.ModelTag = f"gs{gsDef['name']}"
        gs.planetRadius = mc.R_EARTH_EQ  # [m]
        gs.specifyLocation(np.radians(gsDef["lat_deg"]), np.radians(gsDef["lon_deg"]), gsDef["alt_m"])
        gs.planetInMsg.subscribeTo(spiceObject.planetStateOutMsgs[earthIdx])
        gs.minimumElevation = np.radians(gsDef["min_elevation_deg"])
        gs.maximumRange = mc.GROUND_STATION_MAX_RANGE_M
        for sat in satellites.values():
            gs.addSpacecraftToModel(sat["scObject"].scStateOutMsg)
        scSim.AddModelToTask(dynTaskName, gs, 350)
        groundStations.append(dict(definition=gsDef, module=gs))
    return groundStations


def build_communications(scSim, dynTaskName, ctrlTaskName, satellites, groundStations):
    """Per-satellite EO instrument + on-board storage + ground downlink
    transmitter, plus the eclipse-gated instrument duty-cycle controller.
    Returns a dict keyed by satellite name with every comm object, for
    recorder/Vizard wiring in ``run_constellation_mission.py``.
    """
    comms = {}
    for name, sat in satellites.items():
        satIndex = sat["index"]

        instrument = simpleInstrument.SimpleInstrument()
        instrument.ModelTag = f"{name}Instrument"
        instrument.nodeDataName = "EO Payload"
        scSim.AddModelToTask(dynTaskName, instrument, 60)

        transmitter = spaceToGroundTransmitter.SpaceToGroundTransmitter()
        transmitter.ModelTag = f"{name}Transmitter"
        # DataNodeBase convention: data provided (+) or consumed (-). The
        # downlink always consumes stored data when it has ground access.
        transmitter.nodeBaudRate = -mc.DOWNLINK_BAUD_RATE_BPS  # [bit/s]
        transmitter.packetSize = -mc.DOWNLINK_PACKET_SIZE_BITS  # [bit]
        transmitter.numBuffers = mc.DOWNLINK_NUM_BUFFERS
        for gs in groundStations:
            transmitter.addAccessMsgToTransmitter(gs["module"].accessOutMsgs[satIndex])
        scSim.AddModelToTask(dynTaskName, transmitter, 60)

        storageUnit = partitionedStorageUnit.PartitionedStorageUnit()
        storageUnit.ModelTag = f"{name}Storage"
        storageUnit.storageCapacity = mc.DATA_STORAGE_CAPACITY_BITS  # [bit]
        storageUnit.addDataNodeToModel(instrument.nodeDataOutMsg)
        storageUnit.addDataNodeToModel(transmitter.nodeDataOutMsg)
        storageUnit.addPartition("EO Payload")
        scSim.AddModelToTask(dynTaskName, storageUnit, 55)

        transmitter.addStorageUnitToTransmitter(storageUnit.storageUnitDataOutMsg)

        gate = InstrumentEclipseGate(
            name=f"{name}InstrumentGate",
            instrument=instrument,
            baud_rate_bps=mc.EO_INSTRUMENT_BAUD_RATE_BPS,
            eclipse_sunlit_threshold=mc.ECLIPSE_SUNLIT_THRESHOLD,
        )
        scSim.AddModelToTask(ctrlTaskName, gate)

        comms[name] = dict(
            instrument=instrument,
            transmitter=transmitter,
            storageUnit=storageUnit,
            instrumentGate=gate,
        )
    return comms
