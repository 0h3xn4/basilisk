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
Per-satellite power budget: Basilisk's ``simplePower*`` subsystem
(:ref:`simpleSolarPanel`, :ref:`simpleBattery`, :ref:`simplePowerSink` --
the same modules and wiring pattern as ``examples/scenarioPowerDemo.py``),
wired to the mission's existing per-satellite objects rather than a
standalone scenario.

Power generation comes from :class:`simpleSolarPanel`, which already
accounts for both eclipse shadowing (``sunEclipseInMsg``, shared with the
station-keeping thrust gate and the EO instrument gate) and attitude --
its ``stateInMsg`` reads the spacecraft's *actual, actively-controlled*
``sigma_BN`` (see ``attitude_controllers.py``), so generated power tracks
the real cosine loss between the panel normal and the sun direction, not a
flat average duty cycle. Four loads are modeled as separate
:class:`simplePowerSink` instances so each can be seen independently in the
reported power budget:

* a static always-on bus load (avionics/thermal/ADCS housekeeping),
* the EO instrument, gated on whenever it is actually collecting data
  (mirrors ``communications.InstrumentEclipseGate``'s own eclipse gate --
  see :class:`PowerLoadGate`),
* the downlink transmitter, gated on whenever the satellite's
  :class:`~attitude_controllers.AttitudePointingController` reports it is
  actively pointing the antenna at a ground station (i.e. an access window
  is open -- see :class:`PowerLoadGate`).

All four feed one :class:`simpleBattery` per satellite, which tracks net
power balance and stored energy (state of charge) over the mission.

See ``README.md`` for the full placeholder list (no EPS design -- panel
area/efficiency, battery capacity, or load power draws -- was specified in
the mission statement).
"""

from Basilisk.architecture import sysModel
from Basilisk.simulation import simpleSolarPanel, simplePowerSink, simpleBattery
import mission_config as mc


class PowerLoadGate(sysModel.SysModel):
    """Sets the instrument/downlink power-sink wattage to match whether
    each subsystem is actually active this tick.

    The EO instrument's activity is read directly off its own (already
    eclipse-gated) ``nodeBaudRate`` -- see
    ``communications.InstrumentEclipseGate``. The downlink transmitter's
    ``nodeBaudRate`` is, by contrast, a *static* value set once at build
    time in ``communications.py`` (the transmitter gates its actual data
    flow internally from the ground station access message, not by
    changing ``nodeBaudRate``), so "is the downlink transmitter actually
    active" has to come from somewhere else: this reads it off the
    satellite's own :class:`~attitude_controllers.AttitudePointingController`,
    which already determines every tick whether the antenna currently has
    a ground station to point at.
    """

    def __init__(self, name, instrument, instrument_sink, downlink_sink, attitude_controller,
                 instrument_power_w, downlink_power_w):
        super().__init__()
        self.ModelTag = name
        self.instrument = instrument
        self.instrumentSink = instrument_sink
        self.downlinkSink = downlink_sink
        self.attitudeController = attitude_controller
        self.instrumentPowerW = instrument_power_w  # [W]
        self.downlinkPowerW = downlink_power_w  # [W]

    def Reset(self, CurrentSimNanos):
        self.instrumentSink.nodePowerOut = 0.0
        self.downlinkSink.nodePowerOut = 0.0

    def UpdateState(self, CurrentSimNanos):
        instrumentActive = self.instrument.nodeBaudRate > 0.0
        self.instrumentSink.nodePowerOut = -self.instrumentPowerW if instrumentActive else 0.0

        downlinkActive = (
            self.attitudeController is not None
            and self.attitudeController.mode == self.attitudeController.ANTENNA
        )
        self.downlinkSink.nodePowerOut = -self.downlinkPowerW if downlinkActive else 0.0


def build_power_budget(scSim, dynTaskName, ctrlTaskName, satellites, comms, attitude_controllers,
                        spiceObject, sunIdx, eclipseObject):
    """Per-satellite solar panel + battery + load sinks. Returns a dict
    keyed by satellite name with every power object, for recorder/Vizard
    wiring and reporting in ``run_constellation_mission.py``.
    """
    power = {}
    for name, sat in satellites.items():
        satIndex = sat["index"]

        panel = simpleSolarPanel.SimpleSolarPanel()
        panel.ModelTag = f"{name}SolarPanel"
        panel.setPanelParameters(mc.PANEL_NORMAL_B, mc.SOLAR_PANEL_AREA_M2, mc.SOLAR_PANEL_EFFICIENCY)
        panel.stateInMsg.subscribeTo(sat["scObject"].scStateOutMsg)
        panel.sunInMsg.subscribeTo(spiceObject.planetStateOutMsgs[sunIdx])
        panel.sunEclipseInMsg.subscribeTo(eclipseObject.eclipseOutMsgs[satIndex])
        scSim.AddModelToTask(dynTaskName, panel, 50)

        busSink = simplePowerSink.SimplePowerSink()
        busSink.ModelTag = f"{name}BusPowerSink"
        busSink.nodePowerOut = -mc.BUS_IDLE_POWER_W  # [W] static always-on load
        scSim.AddModelToTask(dynTaskName, busSink, 50)

        instrumentSink = simplePowerSink.SimplePowerSink()
        instrumentSink.ModelTag = f"{name}InstrumentPowerSink"
        scSim.AddModelToTask(dynTaskName, instrumentSink, 50)

        downlinkSink = simplePowerSink.SimplePowerSink()
        downlinkSink.ModelTag = f"{name}DownlinkPowerSink"
        scSim.AddModelToTask(dynTaskName, downlinkSink, 50)

        gate = PowerLoadGate(
            name=f"{name}PowerLoadGate",
            instrument=comms[name]["instrument"],
            instrument_sink=instrumentSink,
            downlink_sink=downlinkSink,
            attitude_controller=attitude_controllers.get(name),
            instrument_power_w=mc.EO_INSTRUMENT_POWER_W,
            downlink_power_w=mc.DOWNLINK_TX_POWER_W,
        )
        scSim.AddModelToTask(ctrlTaskName, gate)

        battery = simpleBattery.SimpleBattery()
        battery.ModelTag = f"{name}Battery"
        battery.storageCapacity = mc.BATTERY_CAPACITY_WH * 3600.0  # [W*s]
        battery.storedCharge_Init = mc.BATTERY_INITIAL_SOC * mc.BATTERY_CAPACITY_WH * 3600.0  # [W*s]
        battery.addPowerNodeToModel(panel.nodePowerOutMsg)
        battery.addPowerNodeToModel(busSink.nodePowerOutMsg)
        battery.addPowerNodeToModel(instrumentSink.nodePowerOutMsg)
        battery.addPowerNodeToModel(downlinkSink.nodePowerOutMsg)
        # Runs after the panel/sinks above (lower priority == later within
        # the same tick) so it reads this tick's fresh generation/load
        # values rather than the previous tick's.
        scSim.AddModelToTask(dynTaskName, battery, 40)

        power[name] = dict(
            panel=panel, busSink=busSink, instrumentSink=instrumentSink,
            downlinkSink=downlinkSink, gate=gate, battery=battery,
        )
    return power
