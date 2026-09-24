# Template missions

Nine ready-to-run scenario files, each demonstrating one missionStudio
concept in isolation -- for learning the tool and the orbital-mechanics
concepts it simulates, and as starting points for your own missions
(copy one, edit it, save it under a new name).

Every file is a complete, independently valid `Scenario` (built through
`schema.scenario`'s own dataclasses and `Scenario.validate()`, not
hand-written JSON -- see `scripts/_generate_templates.py` in this
repository, the source of truth these were generated from) with an
extensive `description` field explaining what it teaches, what to look at
after running it, and what to try changing. Read that field (open the
`.json` file directly, or look at the Description box at the top of the
GUI's scenario form after opening one) before diving into the raw numbers.

## Opening a template

```bash
# GUI: File -> Open..., then browse to one of these files, or:
python3 -m missionstudio.gui.app

# CLI (needs a real Basilisk build):
missionstudio run missionstudio/scenarios/templates/01_two_body_circular_orbit.json --out-dir out

# Just check it's schema-valid, no Basilisk needed:
missionstudio validate missionstudio/scenarios/templates/01_two_body_circular_orbit.json
```

Once opened in the GUI, **Save As...** under a new name/location before
editing if you want to keep the original template intact for next time.

## Catalog

Roughly progressive order -- each one builds on ideas from the ones
before it, but none of them depend on running an earlier one first.

| # | File | Teaches |
|---|------|---------|
| 01 | `01_two_body_circular_orbit.json` | The basics: a single circular orbit, point-mass Earth, no perturbations, no attitude (`simulation_mode: orbit_only`). Kepler's third law. |
| 02 | `02_elliptical_orbit_with_perturbations.json` | An eccentric (GTO-like) orbit with Earth oblateness (J2 via 8th-degree spherical harmonics) and Sun/Moon third-body gravity switched on -- nodal regression, apsidal rotation, why a fine `dynamics_task_rate_s` matters once `central_body_degree > 0`. |
| 03 | `03_geo_station_keeping.json` | A GEO satellite actively correcting real perturbation-driven drift with a deadband thrust controller (`station_keeping`) -- propellant budgeting for a multi-week station-keeping campaign. |
| 04 | `04_walker_constellation.json` | A 6-satellite, 2-plane Walker delta constellation, generated programmatically via `engine.constellation.generate_walker_constellation()` -- the same code path the GUI's "Generate Walker constellation..." dialog and the `generate-constellation` CLI subcommand use. |
| 05 | `05_formation_flying_phasing.json` | Two spacecraft, one holding a fixed in-track separation behind the other (`phasing_keeping`, always paired with its own `station_keeping` -- see that config's own docstring for why) -- a basic formation-flying/proximity-operations control model. |
| 06 | `06_attitude_pointing_basic.json` | Attitude pointing as a pure concept: `fsw_mode: hillPoint` (nadir pointing) with no sensors/actuators configured, so control torque is applied through an idealized effector rather than modeled hardware. Watch the attitude error converge. |
| 07 | `07_attitude_pointing_with_adcs_hardware.json` | The same pointing problem as '06', but with a realistic hardware suite: star tracker, IMU, coarse sun sensor, three reaction wheels, and a solar-array/battery power budget -- what a real small-sat `SpacecraftConfig` actually looks like. |
| 08 | `08_mission_sequence_orbit_raise.json` | The Mission Sequence layer: a time-ordered command list (coast, snapshot, impulsive prograde burn, coast, snapshot) instead of one flat propagate-to-duration run -- edit it as a tree in the GUI's "Mission sequence" panel. The building block for a full two-burn Hohmann transfer (see the file's own description for how to extend it into one). |
| 09 | `09_monte_carlo_dispersion_analysis.json` | Uncertainty quantification: the same orbit as '01', run as a 20-case Monte Carlo batch with `dry_mass_kg` independently redrawn per run from a normal distribution. |

## Using one as a starting point for your own mission

These are deliberately minimal and self-contained -- no ground stations,
no RF links, no Monte Carlo batches layered on top of an attitude
scenario, etc. -- so each idea is easy to see in isolation. A real mission
scenario will usually combine several of these concepts (e.g. a
comms-relay constellation might start from '04' and add '07''s ADCS
hardware plus a ground station and RF link to each satellite, matching
what `gui/ground_station_editor.py`/`RFLinkConfig` add). Copying the
closest template and layering in the next concept from this list is
generally easier than starting from a blank scenario.
