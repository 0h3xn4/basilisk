"""Tests for engine.mission_engine.MissionEngine -- walks a Scenario's
mission_sequence (schema.command.Command tree) against a real
SimulationService.

Requires a Basilisk build (marked ``requires_basilisk``; see
tests/conftest.py for the auto-skip behavior in this development sandbox,
which does not have one) -- engine.mission_engine imports engine.service,
which itself requires Basilisk at import time, so every test here needs
the marker, exactly like tests/test_two_body_validation.py and
tests/test_service_run_live.py.
"""

import numpy as np
import pytest

from missionstudio.schema.command import Command
from missionstudio.schema.scenario import (
    GravityConfig,
    OrbitIC,
    Scenario,
    SimSettings,
    SpacecraftConfig,
    StationKeepingConfig,
)

pytestmark = pytest.mark.requires_basilisk


def _circular_orbit(semi_major_axis_km=7000.0, inclination_deg=51.6, eccentricity=0.0):
    return OrbitIC(
        type="classical_elements", semi_major_axis_km=semi_major_axis_km, eccentricity=eccentricity,
        inclination_deg=inclination_deg, raan_deg=45.0, arg_periapsis_deg=30.0, true_anomaly_deg=0.0,
    )


def _scenario(duration_days=0.2, dynamics_task_rate_s=10.0, mission_sequence=None, third_body_perturbers=(),
              **spacecraft_overrides):
    spacecraft_kwargs = dict(name="sat-1", orbit=_circular_orbit())
    spacecraft_kwargs.update(spacecraft_overrides)
    return Scenario(
        name="mission engine test", epoch_utc="2030-01-01T00:00:00",
        gravity=GravityConfig(central_body="earth", central_body_degree=0,
                               third_body_perturbers=list(third_body_perturbers)),
        spacecraft=[SpacecraftConfig(**spacecraft_kwargs)],
        sim_settings=SimSettings(duration_days=duration_days, dynamics_task_rate_s=dynamics_task_rate_s,
                                  integrator="rkf78"),
        mission_sequence=mission_sequence or [],
    )


def test_empty_mission_sequence_executes_nothing():
    from missionstudio.engine.mission_engine import MissionEngine

    scenario = _scenario()
    result, summary = MissionEngine(scenario).run()

    assert summary.commands_executed == 0
    assert summary.reports == []
    # A recorder's first sample only exists once ExecuteSimulation() has
    # actually ticked at least once -- InitializeSimulation() alone (which
    # is all build() does here, since no propagate command ever runs)
    # produces zero samples, confirmed directly against a real Basilisk
    # build (this assertion originally, wrongly, expected 1).
    assert len(result.series["sat-1.position_N"].time_s) == 0


def test_single_propagate_duration_matches_plain_run():
    """A mission_sequence with one propagate-for-the-whole-duration
    command must produce the exact same trajectory as
    SimulationService.run() on an identical scenario -- same integrator,
    same task rate, only the ConfigureStopTime()/ExecuteSimulation()
    calls are issued by MissionEngine instead of SimulationService.build().
    """
    from missionstudio.engine.mission_engine import MissionEngine
    from missionstudio.engine.service import SimulationService

    duration_days = 0.1
    mission_scenario = _scenario(duration_days=duration_days, mission_sequence=[
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": duration_days}),
    ])
    mission_result, _ = MissionEngine(mission_scenario).run()

    plain_scenario = _scenario(duration_days=duration_days)
    plain_result = SimulationService(plain_scenario).run()

    mission_pos = mission_result.series["sat-1.position_N"]
    plain_pos = plain_result.series["sat-1.position_N"]
    assert np.array_equal(mission_pos.time_s, plain_pos.time_s)
    assert np.array_equal(mission_pos.data, plain_pos.data)


def test_multiple_propagate_segments_accumulate_not_restart():
    """The core Phase 6 execution-engine requirement: repeated
    ConfigureStopTime()/ExecuteSimulation() calls (one per propagate
    command) must RESUME the same simulation, not restart it -- three
    0.02-day segments must cover exactly as much ground as one 0.06-day
    segment, matching SimulationService.run_live()'s already-verified
    chunking behavior (see test_service_run_live.py) but exercised here
    through MissionEngine's own command dispatch instead.
    """
    from missionstudio.engine.mission_engine import MissionEngine
    from missionstudio.engine.service import SimulationService

    segment_days = 0.02
    mission_scenario = _scenario(duration_days=segment_days * 3, mission_sequence=[
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": segment_days}),
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": segment_days}),
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": segment_days}),
    ])
    mission_result, summary = MissionEngine(mission_scenario).run()
    assert summary.commands_executed == 3

    single_scenario = _scenario(duration_days=segment_days * 3)
    single_result = SimulationService(single_scenario).run()

    mission_pos = mission_result.series["sat-1.position_N"]
    single_pos = single_result.series["sat-1.position_N"]
    assert mission_pos.time_s[-1] == pytest.approx(single_pos.time_s[-1])
    assert np.allclose(mission_pos.data[-1], single_pos.data[-1])


def test_propagate_epoch_stop_condition():
    from missionstudio.engine.mission_engine import MissionEngine

    scenario = _scenario(duration_days=1.0, mission_sequence=[
        Command(kind="propagate", params={"stop_condition": "epoch", "stop_epoch_utc": "2030-01-01T02:00:00"}),
    ])
    result, summary = MissionEngine(scenario).run()

    assert summary.commands_executed == 1
    pos = result.series["sat-1.position_N"]
    assert pos.time_s[-1] == pytest.approx(2 * 3600.0, rel=1e-6)


def test_propagate_epoch_before_current_time_is_rejected():
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineError

    scenario = _scenario(duration_days=1.0, mission_sequence=[
        Command(kind="propagate", params={"stop_condition": "epoch", "stop_epoch_utc": "2030-01-01T00:00:00"}),
    ])
    with pytest.raises(MissionEngineError, match="is not after the current mission time"):
        MissionEngine(scenario).run()


def test_propagate_event_periapsis_stops_near_zero_radial_velocity():
    """A tight ``dynamics_task_rate_s`` (the event's own check granularity
    -- see MissionEngine._run_propagate_event) bounds how far past the
    true zero-crossing the event can be caught: near periapsis, radial
    velocity changes at roughly the local gravitational acceleration
    (~8 m/s^2 for this LEO orbit), so a 1 s check interval bounds the
    residual to roughly that same order of magnitude -- the 20 m/s
    tolerance below is deliberately generous relative to that estimate
    (not tuned to the tightest possible pass), so a failure here means a
    real detection bug, not check-granularity noise.
    """
    from missionstudio.engine.mission_engine import MissionEngine

    scenario = _scenario(
        duration_days=1.0, dynamics_task_rate_s=1.0, orbit=_circular_orbit(eccentricity=0.05),
        mission_sequence=[
            Command(kind="propagate", params={
                "stop_condition": "event", "event_kind": "periapsis", "spacecraft": "sat-1",
            }),
        ],
    )
    result, summary = MissionEngine(scenario).run()
    assert summary.commands_executed == 1

    pos = result.series["sat-1.position_N"].data[-1]
    vel = result.series["sat-1.velocity_N"].data[-1]
    radial_velocity = float(np.dot(pos, vel) / np.linalg.norm(pos))
    assert abs(radial_velocity) < 20.0, f"expected near-zero radial velocity at periapsis, got {radial_velocity} m/s"


def test_propagate_event_unknown_spacecraft_raises():
    """MissionEngine's own "unknown spacecraft" check in
    _run_propagate_event is unreachable through a normal Scenario, since
    schema.validation/Scenario.validate() (run inside build()) already
    rejects a mission_sequence command naming a spacecraft that isn't in
    scenario.spacecraft -- confirmed directly (this was originally written
    expecting MissionEngineError and instead hit ScenarioValidationError).
    Reaches the engine's own defensive check instead via the documented
    "reuse an already-built service" path: a service built from a
    scenario that legitimately has "sat-1" is deliberately paired here
    with a DIFFERENT scenario (only used for its mission_sequence) that
    references a name the built service was never given -- the one real
    way this class's own check is reachable, not a contrived one.
    """
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineError
    from missionstudio.engine.service import SimulationService

    service = SimulationService(_scenario())  # only ever knows about "sat-1"
    service.build()

    mismatched_scenario = _scenario(mission_sequence=[
        Command(kind="propagate", params={
            "stop_condition": "event", "event_kind": "periapsis", "spacecraft": "does-not-exist",
        }),
    ])
    with pytest.raises(MissionEngineError, match="unknown spacecraft"):
        MissionEngine(mismatched_scenario, service=service).run()


def _read_velocity_state(handle):
    """The live translational-velocity state object's CURRENT value,
    bypassing scStateOutMsg/the recorder entirely -- a maneuver mutates
    the state directly (see MissionEngine._run_maneuver) and that message
    is only refreshed on the spacecraft's own next UpdateState() cycle, so
    checking the recorded history right after a maneuver with no
    subsequent propagate command would still show the PRE-maneuver value.
    Reading the state object itself is also the most direct possible
    check of the underlying Basilisk state-mutation pattern this method
    relies on (dynManager.getStateObject(...).getState()/.setState()),
    matching examples/scenarioOrbitManeuver.py's own verified usage.
    """
    from Basilisk.utilities import simHelpers

    vel_ref = handle.sc_object.dynManager.getStateObject(handle.sc_object.hub.nameOfHubVelocity)
    return simHelpers.EigenVector3d2np(vel_ref.getState())


def test_maneuver_inertial_frame_applies_exact_delta_v():
    from missionstudio.engine.mission_engine import MissionEngine

    delta_v = np.array([10.0, -5.0, 2.0])  # [m/s]
    scenario = _scenario(mission_sequence=[
        Command(kind="maneuver", params={"spacecraft": "sat-1", "delta_v_m_s": delta_v.tolist(), "frame": "inertial"}),
    ])
    engine = MissionEngine(scenario)
    engine.service.build()
    handle = engine.service.spacecraft_handles["sat-1"]
    v0 = _read_velocity_state(handle)

    _, summary = engine.run()
    assert summary.commands_executed == 1

    v1 = _read_velocity_state(handle)
    assert np.allclose(v1 - v0, delta_v, atol=1e-9)


def test_maneuver_vnb_prograde_increases_speed_by_exact_magnitude():
    from missionstudio.engine.mission_engine import MissionEngine

    dv_mag = 25.0  # [m/s]
    scenario = _scenario(mission_sequence=[
        Command(kind="maneuver", params={"spacecraft": "sat-1", "delta_v_m_s": [dv_mag, 0.0, 0.0], "frame": "vnb"}),
    ])
    engine = MissionEngine(scenario)
    engine.service.build()
    handle = engine.service.spacecraft_handles["sat-1"]
    v0 = _read_velocity_state(handle)

    engine.run()

    v1 = _read_velocity_state(handle)
    assert np.linalg.norm(v1) - np.linalg.norm(v0) == pytest.approx(dv_mag, abs=1e-6)


def test_maneuver_unknown_spacecraft_raises():
    """See test_propagate_event_unknown_spacecraft_raises's docstring for
    why this needs a pre-built, deliberately mismatched service rather
    than a plain Scenario -- Scenario.validate() (run inside build())
    already rejects an unknown spacecraft name in mission_sequence before
    MissionEngine's own check would ever run.
    """
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineError
    from missionstudio.engine.service import SimulationService

    service = SimulationService(_scenario())  # only ever knows about "sat-1"
    service.build()

    mismatched_scenario = _scenario(mission_sequence=[
        Command(kind="maneuver", params={"spacecraft": "ghost", "delta_v_m_s": [1.0, 0.0, 0.0]}),
    ])
    with pytest.raises(MissionEngineError, match="unknown spacecraft"):
        MissionEngine(mismatched_scenario, service=service).run()


def test_assignment_updates_live_station_keeping_thrust():
    from missionstudio.engine.mission_engine import MissionEngine

    scenario = _scenario(mission_sequence=[
        Command(kind="assignment", params={"target": "sat-1.station_keeping.thrust_n", "value": 0.5}),
    ], third_body_perturbers=["sun"], station_keeping=StationKeepingConfig(
        # station_keeping needs the real eclipse shadow factor (see
        # engine/service.py's build()), which needs 'sun' SPICE-tracked --
        # third_body_perturbers=["sun"] above, not just a schema-level
        # requirement: SimulationServiceError otherwise.
        target_altitude_km=7000.0, deadband_km=1.0, thrust_n=0.1, isp_s=200.0, propellant_kg=1.0,
    ))
    engine = MissionEngine(scenario)
    engine.run()

    controller = engine.service.spacecraft_handles["sat-1"].station_keeping_controller
    assert controller.thrustN == pytest.approx(0.5)


def test_assignment_bad_target_shape_raises():
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineError

    scenario = _scenario(mission_sequence=[
        Command(kind="assignment", params={"target": "sat-1.thrust_n", "value": 1.0}),
    ])
    with pytest.raises(MissionEngineError, match="3 dotted segments"):
        MissionEngine(scenario).run()


def test_assignment_missing_controller_raises():
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineError

    scenario = _scenario(mission_sequence=[
        Command(kind="assignment", params={"target": "sat-1.station_keeping.thrust_n", "value": 1.0}),
    ])  # no station_keeping configured
    with pytest.raises(MissionEngineError, match="has no station_keeping configured"):
        MissionEngine(scenario).run()


def test_report_snapshots_current_value_not_whole_history():
    from missionstudio.engine.mission_engine import MissionEngine

    scenario = _scenario(duration_days=0.05, mission_sequence=[
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": 0.025}, label="halfway"),
        Command(kind="report", params={"series": ["sat-1.position_N"]}, label="checkpoint"),
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": 0.025}),
    ])
    result, summary = MissionEngine(scenario).run()

    assert len(summary.reports) == 1
    report = summary.reports[0]
    assert report.label == "checkpoint"
    assert set(report.values) == {"sat-1.position_N"}
    assert report.values["sat-1.position_N"].shape == (3,)

    # The snapshot must match the position AT THAT TIME, not the final one.
    full_series = result.series["sat-1.position_N"]
    halfway_index = int(np.argmin(np.abs(full_series.time_s - report.t_s)))
    assert np.allclose(report.values["sat-1.position_N"], full_series.data[halfway_index], atol=1.0)
    assert not np.allclose(report.values["sat-1.position_N"], full_series.data[-1], atol=1.0)


def test_report_unknown_series_raises():
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineError

    scenario = _scenario(mission_sequence=[
        Command(kind="report", params={"series": ["sat-1.nonexistent_series"]}),
    ])
    with pytest.raises(MissionEngineError, match="not found in the result set"):
        MissionEngine(scenario).run()


def test_if_true_branch_runs_children():
    from missionstudio.engine.mission_engine import MissionEngine

    # A script_block marker, not a report command: this test is about
    # if's own branching, not about report's recorder-snapshot semantics
    # (a report has nothing to snapshot until a propagate command has
    # actually run at least once -- see _run_report's own guard).
    scenario = _scenario(mission_sequence=[
        Command(kind="if", params={"condition": "t_s == 0.0"}, children=[
            Command(kind="script_block", params={"code": "summary.reports.append('ran')"}),
        ]),
    ])
    _, summary = MissionEngine(scenario).run()
    assert summary.reports == ["ran"]


def test_if_false_branch_skips_children():
    from missionstudio.engine.mission_engine import MissionEngine

    scenario = _scenario(mission_sequence=[
        Command(kind="if", params={"condition": "t_s > 0.0"}, children=[
            Command(kind="report", params={"series": []}, label="should not run"),
        ]),
    ])
    _, summary = MissionEngine(scenario).run()
    assert summary.reports == []
    # The `if` itself still counts as an executed command even when its
    # branch doesn't run -- only the child inside it is skipped.
    assert summary.commands_executed == 1


def test_if_condition_can_read_spacecraft_state():
    from missionstudio.engine.mission_engine import MissionEngine

    scenario = _scenario(mission_sequence=[
        Command(kind="if", params={"condition": "spacecraft['sat-1']['altitude_m'] > 0"}, children=[
            Command(kind="script_block", params={"code": "summary.reports.append('above surface')"}),
        ]),
    ])
    _, summary = MissionEngine(scenario).run()
    assert summary.reports == ["above surface"]


def test_while_loop_runs_expected_iterations_and_terminates():
    from missionstudio.engine.mission_engine import MissionEngine

    segment_days = 0.01
    segment_s = segment_days * 86400.0
    # Threshold deliberately set HALFWAY between 1 and 2 segments (not at
    # an exact segment boundary): t_s after N segments is N*segment_s
    # recomputed from integer nanoseconds via a NANO2SEC float multiply,
    # which is not bit-exact for round decimal seconds -- comparing
    # against an exact boundary value risks the condition's <
    # going the "wrong" way on a sub-ULP rounding difference. A
    # mid-segment threshold keeps a wide margin on both sides so the
    # iteration count this test asserts is robust to that, not merely
    # true by luck.
    scenario = _scenario(duration_days=segment_days * 10, mission_sequence=[
        Command(kind="while", params={"condition": f"t_s < {1.5 * segment_s}"}, children=[
            Command(kind="propagate", params={"stop_condition": "duration", "duration_days": segment_days}),
            Command(kind="report", params={"series": []}),
        ]),
    ])
    _, summary = MissionEngine(scenario).run()

    # while's own condition is re-evaluated after each iteration using the
    # ADVANCED mission time, so it should run exactly twice (t_s starts at
    # 0 < threshold, runs once -> t_s = 1 segment < threshold, runs again
    # -> t_s = 2 segments, past the 1.5-segment threshold, stops).
    assert len(summary.reports) == 2


def test_while_loop_exceeding_iteration_cap_raises_clear_error():
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineError

    scenario = _scenario(mission_sequence=[
        Command(kind="while", params={"condition": "True"}, children=[
            Command(kind="script_block", params={"code": "pass"}),
        ]),
    ])
    with pytest.raises(MissionEngineError, match="exceeded .* iterations"):
        MissionEngine(scenario).run()


def test_script_block_can_write_to_summary():
    from missionstudio.engine.mission_engine import MissionEngine

    scenario = _scenario(mission_sequence=[
        Command(kind="script_block", params={"code": "summary.reports.append(None)"}),
    ])
    _, summary = MissionEngine(scenario).run()
    assert summary.reports == [None]


def test_script_block_exception_is_wrapped_in_mission_engine_error():
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineError

    scenario = _scenario(mission_sequence=[
        Command(kind="script_block", params={"code": "raise ValueError('boom')"}),
    ])
    with pytest.raises(MissionEngineError, match="boom"):
        MissionEngine(scenario).run()


def test_nested_if_inside_while_shares_one_command_summary():
    from missionstudio.engine.mission_engine import MissionEngine

    segment_days = 0.01
    segment_s = segment_days * 86400.0
    # Threshold set HALFWAY between 2 and 3 segments (so exactly 3
    # iterations run: checks at t_s = 0, 1, 2 segments all pass, the
    # check at 3 segments does not) -- see the wide-margin comment on
    # test_while_loop_runs_expected_iterations_and_terminates for why an
    # exact segment-boundary threshold is avoided here.
    scenario = _scenario(duration_days=segment_days * 5, mission_sequence=[
        Command(kind="while", params={"condition": f"t_s < {2.5 * segment_s}"}, children=[
            Command(kind="propagate", params={"stop_condition": "duration", "duration_days": segment_days}),
            Command(kind="if", params={"condition": "True"}, children=[
                Command(kind="report", params={"series": []}, label="nested"),
            ]),
        ]),
    ])
    _, summary = MissionEngine(scenario).run()
    assert [r.label for r in summary.reports] == ["nested", "nested", "nested"]


def test_should_cancel_stops_before_the_first_command_and_raises_mission_engine_cancelled():
    """The "abort a running simulation" GUI feature's mission_sequence
    path: should_cancel is checked before each top-level command runs
    too (see _run_commands), not just mid-command (see
    test_should_cancel_checked_mid_single_long_propagate_command below,
    the actual bug this whole feature exists to fix) -- here it trips on
    the very first check, before "one" ever starts, so nothing at all
    gets simulated.
    """
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineCancelled

    scenario = _scenario(mission_sequence=[
        Command(kind="propagate", label="one", params={"stop_condition": "duration", "duration_days": 0.02}),
        Command(kind="propagate", label="two", params={"stop_condition": "duration", "duration_days": 0.02}),
    ])

    with pytest.raises(MissionEngineCancelled) as exc_info:
        MissionEngine(scenario, should_cancel=lambda: True).run()

    cancelled = exc_info.value
    assert cancelled.summary.commands_executed == 0
    # Same reasoning as test_empty_mission_sequence_executes_nothing:
    # InitializeSimulation() alone (no propagate command ever ran)
    # produces zero recorded samples.
    assert len(cancelled.partial_result.series["sat-1.position_N"].time_s) == 0


def test_should_cancel_checked_mid_single_long_propagate_command():
    """Regression test for a real user report: aborting a mission
    sequence with one long propagate command froze for minutes with no
    effect, because should_cancel used to only be checked BETWEEN
    top-level commands (see the test above) -- a single command's own
    ExecuteSimulation() call ran straight through to completion
    regardless. _advance_to() now chunks it (mirroring
    engine.service.run_live()'s already-existing chunking for the
    non-mission_sequence path), so cancelling partway through one
    command must leave a partial result strictly short of what letting
    it finish would have produced.
    """
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineCancelled
    from missionstudio.engine.service import SimulationService

    duration_days = 0.1
    scenario = _scenario(duration_days=duration_days, mission_sequence=[
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": duration_days}),
    ])
    calls = []

    def should_cancel():
        calls.append(1)
        return len(calls) >= 3  # False before the command starts, then a couple of chunks in

    with pytest.raises(MissionEngineCancelled) as exc_info:
        MissionEngine(scenario, should_cancel=should_cancel).run()

    cancelled = exc_info.value
    assert cancelled.summary.commands_executed == 1  # incremented when the command started, not when it finishes
    partial_samples = len(cancelled.partial_result.series["sat-1.position_N"].time_s)
    assert partial_samples > 0  # some chunks did run before cancelling

    full_result = SimulationService(_scenario(duration_days=duration_days)).run()
    full_samples = len(full_result.series["sat-1.position_N"].time_s)
    assert partial_samples < full_samples, (
        "cancelling mid-command must not let the propagate command run to completion"
    )


def test_should_cancel_checked_mid_propagate_event_command():
    """Same bug, same fix, for propagate.stop_condition == "event": its
    safety-capped ExecuteSimulation() call is chunked exactly like
    _advance_to() now chunks duration/epoch, so cancelling before the
    event actually fires must still report a clean MissionEngineCancelled
    (not, e.g., the "did not occur within the safety cap"
    MissionEngineError a real completion failure would raise).
    """
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineCancelled

    scenario = _scenario(
        duration_days=1.0, dynamics_task_rate_s=1.0, orbit=_circular_orbit(eccentricity=0.05),
        mission_sequence=[
            Command(kind="propagate", params={
                "stop_condition": "event", "event_kind": "periapsis", "spacecraft": "sat-1",
            }),
        ],
    )
    calls = []

    def should_cancel():
        calls.append(1)
        return len(calls) >= 3  # well before a full orbital period (~90 min) has been simulated

    with pytest.raises(MissionEngineCancelled) as exc_info:
        MissionEngine(scenario, should_cancel=should_cancel).run()

    cancelled = exc_info.value
    assert cancelled.summary.commands_executed == 1
    assert len(cancelled.partial_result.series["sat-1.position_N"].time_s) > 0


def test_should_cancel_checked_between_while_loop_iterations():
    """should_cancel is checked before each while-loop iteration's child
    command starts (_run_commands, re-entered once per iteration by
    _run_while) -- here with each iteration's propagate sized to finish
    in exactly one _advance_to() chunk (duration_s well under
    dynamics_task_rate_s), so should_cancel is called exactly twice per
    iteration: once before the child starts, once right after its one
    chunk finishes (see test_should_cancel_checked_mid_single_long_
    propagate_command for the case where a single command spans many
    chunks instead). commands_executed also counts the "while" command
    itself (incremented once, before the loop's first iteration even
    starts), so 2 full iterations plus that one "while" node's own count
    totals 3.
    """
    from missionstudio.engine.mission_engine import MissionEngine, MissionEngineCancelled

    dynamics_task_rate_s = 10.0
    segment_days = (dynamics_task_rate_s / 2.0) / 86400.0  # well under one tick -> always exactly one chunk
    scenario = _scenario(duration_days=segment_days * 10, dynamics_task_rate_s=dynamics_task_rate_s,
                          mission_sequence=[
        Command(kind="while", params={"condition": "True"}, children=[
            Command(kind="propagate", params={"stop_condition": "duration", "duration_days": segment_days}),
        ]),
    ])
    calls = []

    def should_cancel():
        calls.append(1)
        # call1: before the "while" command itself starts
        # call2/3: before/after iteration 0's propagate
        # call4/5: before/after iteration 1's propagate
        # call6: before iteration 2's propagate -- trips here
        return len(calls) > 5

    with pytest.raises(MissionEngineCancelled) as exc_info:
        MissionEngine(scenario, should_cancel=should_cancel).run()

    assert exc_info.value.summary.commands_executed == 3


def test_no_should_cancel_runs_to_completion_as_before():
    """should_cancel=None (the default, matching every pre-existing
    caller) must not change behavior at all.
    """
    from missionstudio.engine.mission_engine import MissionEngine

    scenario = _scenario(mission_sequence=[
        Command(kind="propagate", params={"stop_condition": "duration", "duration_days": 0.02}),
    ])
    _, summary = MissionEngine(scenario).run()
    assert summary.commands_executed == 1
