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

"""A small curated library of reusable spacecraft "bus" templates.

Per user feedback: a brand-new :class:`schema.scenario.SpacecraftConfig`
starts from ``SpacecraftConfig()``'s bare dataclass defaults (100 kg, a
flat 10 kg*m^2 diagonal inertia, no sensors/actuators/power/attitude
control) -- a placeholder, not anything resembling a real vehicle, forcing
a beginner to invent every number from scratch. Each :class:`SpacecraftTemplate`
here instead ``build()``\\ s a complete, internally-consistent, physically
REASONABLE starting point (mass, inertia, sensors, actuators, power,
attitude mode, drag/SRP) the user can then adjust in the ordinary
spacecraft editor -- exactly like starting a document from a template
instead of a blank page.

Pure Python/schema data, no Basilisk import, matching
``engine.constellation``'s same "pure orbital mechanics/data, no Basilisk
import" split (see that module's docstring) -- this is reusable by the
GUI (``gui.spacecraft_editor``'s "New from template..." button) and would
be equally usable from a headless/CLI path later without needing a
Basilisk build.

Numbers here are ROUNDED, ORDER-OF-MAGNITUDE-REASONABLE engineering
figures for illustration (e.g. a 3U CubeSat's inertia from its rectangular
-prism dimensions/mass), not a specific real flight vehicle's actual
datasheet -- same "don't fabricate precision this project doesn't have"
discipline used elsewhere (see e.g. ``engine.link_budget``'s module
docstring). Pick a template as a STARTING POINT, then adjust for your
actual spacecraft. Reaction-wheel figures intentionally reuse
``gui.sensor_actuator_editor._KIND_PARAM_SPECS``'s own "reaction_wheel"
example values, so this module doesn't invent a second, inconsistent set
of "typical RW numbers".

Every template's orbit is the same placeholder (~500 km circular,
97.4 deg -- a common sun-synchronous inclination at that altitude): the
"New from template..." flow opens the ordinary
:class:`gui.spacecraft_editor.SpacecraftEditorDialog` right after picking
one, so the user sets the ACTUAL orbit (and name, and anything else) there
via the normal orbit editor, same as always.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

from ..schema.scenario import (
    ActuatorConfig,
    OrbitIC,
    PowerConfig,
    SensorConfig,
    SpacecraftConfig,
)

# Matches gui.sensor_actuator_editor._KIND_PARAM_SPECS["reaction_wheel"]'s
# own example values -- see this module's docstring.
_RW_EXAMPLE_PARAMS = {"rw_type": "custom", "Omega_max": 6000.0, "u_max": 0.2, "maxMomentum": 50.0, "Js": 0.028}


def _placeholder_orbit() -> OrbitIC:
    return OrbitIC(
        type="classical_elements",
        semi_major_axis_km=6878.0,  # ~500 km altitude
        eccentricity=0.0,
        inclination_deg=97.4,  # sun-synchronous at ~500 km
        raan_deg=0.0,
        arg_periapsis_deg=0.0,
        anomaly_type="true",
        true_anomaly_deg=0.0,
    )


def _three_reaction_wheels() -> List[ActuatorConfig]:
    return [
        ActuatorConfig(kind="reaction_wheel", name="rw-x", params={"gsHat_B": [1.0, 0.0, 0.0], **_RW_EXAMPLE_PARAMS}),
        ActuatorConfig(kind="reaction_wheel", name="rw-y", params={"gsHat_B": [0.0, 1.0, 0.0], **_RW_EXAMPLE_PARAMS}),
        ActuatorConfig(kind="reaction_wheel", name="rw-z", params={"gsHat_B": [0.0, 0.0, 1.0], **_RW_EXAMPLE_PARAMS}),
    ]


def _build_cubesat_3u_passive() -> SpacecraftConfig:
    # 3U CubeSat: ~10x10x34 cm, 4 kg -- treated as a uniform rectangular
    # prism (z = long axis) for the inertia estimate:
    #   Izz = m*(a^2+b^2)/12, Ixx=Iyy = m*(b^2+c^2)/12
    return SpacecraftConfig(
        name="template",
        orbit=_placeholder_orbit(),
        dry_mass_kg=4.0,
        inertia_kg_m2=[0.042, 0.0, 0.0, 0.0, 0.042, 0.0, 0.0, 0.0, 0.007],
        enable_drag=True,
        drag_coeff=2.2,
        drag_area_m2=0.03,  # ~0.1 x 0.3 m average projected (tumbling) area
        enable_srp=True,
        srp_coeff=1.3,
        srp_area_m2=0.03,
    )


def _build_cubesat_3u_stabilized() -> SpacecraftConfig:
    config = _build_cubesat_3u_passive()
    config.sensors = [SensorConfig(kind="coarse_sun_sensor", name="css-1", params={"nHat_B": [1.0, 0.0, 0.0]})]
    config.actuators = _three_reaction_wheels()
    config.power = PowerConfig(
        panel_area_m2=0.06,  # two 3U side panels' worth of deployed cell area, order of magnitude
        panel_efficiency=0.29,
        panel_normal_b=[0.0, 0.0, 1.0],
        bus_idle_power_w=5.0,
        battery_capacity_wh=20.0,
        battery_initial_soc=0.9,
    )
    config.fsw_mode = "sunSafePoint"
    config.fsw_params = {"sHatBdyCmd": [1.0, 0.0, 0.0]}
    return config


def _build_smallsat_espa() -> SpacecraftConfig:
    # ESPA-class smallsat, ~100 kg -- inertia is an illustrative
    # order-of-magnitude figure for a roughly 0.5 m bus, not derived from a
    # specific vehicle's mass properties.
    return SpacecraftConfig(
        name="template",
        orbit=_placeholder_orbit(),
        dry_mass_kg=100.0,
        inertia_kg_m2=[15.0, 0.0, 0.0, 0.0, 15.0, 0.0, 0.0, 0.0, 12.0],
        sensors=[
            SensorConfig(kind="star_tracker", name="st-1", params={"noise_arcsec": 5.0}),
            SensorConfig(kind="coarse_sun_sensor", name="css-1", params={"nHat_B": [0.0, 0.0, 1.0]}),
        ],
        actuators=_three_reaction_wheels(),
        power=PowerConfig(
            panel_area_m2=1.0,
            panel_efficiency=0.29,
            panel_normal_b=[0.0, 0.0, 1.0],
            bus_idle_power_w=25.0,
            battery_capacity_wh=150.0,
            battery_initial_soc=0.9,
        ),
        fsw_mode="inertial3D",
        fsw_params={"sigma_R0N": [0.0, 0.0, 0.0]},
        enable_drag=True,  # SpacecraftConfig's own drag_coeff/drag_area_m2 defaults (2.2, 1.0 m^2) are already
        enable_srp=True,   # a reasonable order-of-magnitude fit for a ~100 kg, ~1 m-class bus -- left as-is.
    )


@dataclass(frozen=True)
class SpacecraftTemplate:
    name: str
    description: str
    build: Callable[[], SpacecraftConfig]


SPACECRAFT_TEMPLATES: List[SpacecraftTemplate] = [
    SpacecraftTemplate(
        "3U CubeSat -- passive (no ADCS)",
        "4 kg, no sensors/actuators/power/attitude control -- drag+SRP enabled. A minimal orbit-propagation-"
        "only bus: good for delta-V/station-keeping/orbit-lifetime studies where attitude doesn't matter.",
        _build_cubesat_3u_passive,
    ),
    SpacecraftTemplate(
        "3U CubeSat -- 3-axis stabilized",
        "4 kg, coarse sun sensor + 3 reaction wheels + sunSafePoint attitude control + a small power budget. "
        "Drag+SRP enabled.",
        _build_cubesat_3u_stabilized,
    ),
    SpacecraftTemplate(
        "ESPA-class smallsat (100 kg)",
        "100 kg, star tracker + coarse sun sensor + 3 reaction wheels + inertial3D attitude control + a "
        "~1 m-class power budget. Drag+SRP enabled.",
        _build_smallsat_espa,
    ),
]
