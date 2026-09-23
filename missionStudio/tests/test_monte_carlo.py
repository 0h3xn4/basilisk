"""Tests for missionstudio.engine.monte_carlo.run_monte_carlo(). Needs a
Basilisk build to import (Basilisk.utilities.MonteCarlo.* at module level);
see tests/conftest.py for the auto-skip behavior in this development
sandbox, which does not have one.
"""

import pytest

from missionstudio.schema import GravityConfig, MonteCarloConfig, OrbitIC, Scenario, SpacecraftConfig

pytestmark = pytest.mark.requires_basilisk


def _scenario():
    return Scenario(
        name="mc test scenario",
        epoch_utc="2030-01-01T00:00:00",
        gravity=GravityConfig(central_body="earth", central_body_degree=0),
        spacecraft=[SpacecraftConfig(
            name="sat-1",
            orbit=OrbitIC(type="cartesian", position_km=[7000.0, 0.0, 0.0], velocity_km_s=[0.0, 7.5, 0.0]),
        )],
        monte_carlo=MonteCarloConfig(enabled=True, num_runs=1),
    )


def test_run_monte_carlo_reports_a_clean_error_when_archive_dir_is_a_file(tmp_path):
    """Regression test for an audit finding: archive_dir.mkdir(...) used to
    sit outside run_monte_carlo()'s own try/except (which only wrapped
    controller.executeSimulations()), so pointing --archive-dir at a path
    that already exists as a plain file raised a bare FileExistsError
    instead of this module's usual MonteCarloError.
    """
    from missionstudio.engine.monte_carlo import MonteCarloError, run_monte_carlo

    archive_dir = tmp_path / "already_a_file"
    archive_dir.write_text("not a directory")

    with pytest.raises(MonteCarloError, match="could not create Monte Carlo archive directory"):
        run_monte_carlo(_scenario(), MonteCarloConfig(enabled=True, num_runs=1), archive_dir)
