from __future__ import annotations

import math

import numpy as np
import pytest

from src.config import DEFAULT_PROBLEM_ROOT
from src.flight_calculator import SegmentCalculator


@pytest.fixture(scope="session")
def calculator() -> SegmentCalculator:
    return SegmentCalculator(problem_root=DEFAULT_PROBLEM_ROOT)


def test_01_o01_to_s001_empty_payload(calculator: SegmentCalculator) -> None:
    result = calculator.calculate_segment("O01", "S001", "A", 0.0)
    assert result["horizontal_distance_m"] > 0
    assert result["max_terrain_elev_m"] > 0
    assert result["cruise_altitude_m"] == pytest.approx(
        result["max_terrain_elev_m"] + 50.0
    )
    assert result["total_time_s"] == pytest.approx(
        result["climb_time_s"]
        + result["cruise_time_s"]
        + result["descent_time_s"]
    )


def test_02_payload_changes_range_and_energy(calculator: SegmentCalculator) -> None:
    empty = calculator.calculate_segment("O01", "S001", "A", 0.0)
    loaded = calculator.calculate_segment("O01", "S001", "A", 24.9)
    assert loaded["equivalent_range_m"] < empty["equivalent_range_m"]
    assert loaded["horizontal_energy_kwh"] > empty["horizontal_energy_kwh"]
    assert loaded["climb_energy_kwh"] > empty["climb_energy_kwh"]
    assert loaded["total_energy_kwh"] > empty["total_energy_kwh"]


def test_03_routes_have_distinct_terrain(calculator: SegmentCalculator) -> None:
    results = [
        calculator.calculate_segment("O01", end, "B", 0.0)
        for end in ("S003", "S010", "S015")
    ]
    maxima = {round(row["max_terrain_elev_m"], 1) for row in results}
    cruise_altitudes = {round(row["cruise_altitude_m"], 1) for row in results}
    assert len(maxima) >= 2
    assert len(cruise_altitudes) >= 2


def test_04_service_to_service_is_supported(calculator: SegmentCalculator) -> None:
    result = calculator.calculate_segment("S001", "S002", "B", 10.0)
    assert result["start_node"] == "S001"
    assert result["end_node"] == "S002"
    assert result["horizontal_distance_m"] > 0
    assert result["start_work_altitude_m"] == pytest.approx(
        result["start_ground_elev_m"] + 30.0
    )


def test_05_invalid_payload_raises_clear_error(calculator: SegmentCalculator) -> None:
    with pytest.raises(ValueError, match="超过机型A最大载质量"):
        calculator.calculate_segment("O01", "S001", "A", 25.01)
    with pytest.raises(ValueError, match="不能小于0"):
        calculator.calculate_segment("O01", "S001", "A", -0.1)


def test_06_dem_profile_is_dense_and_consistent(calculator: SegmentCalculator) -> None:
    profile = calculator.terrain_profile("O01", "S015")
    assert len(profile.distance_m) > 2
    assert float(profile.distance_m[-1] - profile.distance_m[-2]) <= 15.01
    assert profile.max_terrain_elevation_m == pytest.approx(
        float(profile.elevation_m[~np.isnan(profile.elevation_m)].max())
    )
    assert math.isfinite(profile.max_terrain_longitude_deg)
    assert math.isfinite(profile.max_terrain_latitude_deg)


def test_all_ordered_node_pairs_are_precomputed(calculator: SegmentCalculator) -> None:
    rows = calculator.all_node_pair_geometry()
    assert len(rows) == 16 * 15
    assert len({(row["start_node"], row["end_node"]) for row in rows}) == 240
