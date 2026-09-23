"""可重复调用的运输无人机基础航段时间与能耗计算器。"""

from __future__ import annotations

from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Dict, Tuple

from .config import (
    CRUISE_CLEARANCE_M,
    DEFAULT_DEM_SAMPLE_INTERVAL_M,
    DEFAULT_PROBLEM_ROOT,
    ENERGY_FORMULA_STATUS,
    JOULES_PER_KWH,
    SERVICE_WORK_HEIGHT_AGL_M,
    STANDARD_GRAVITY_M_S2,
)
from .data_loader import Node, ProjectData, TransportModel, load_project_data
from .dem_utils import DemGrid, TerrainProfile


class SegmentCalculator:
    """一次读取附件和DEM，随后快速计算任意节点对、机型和载荷。"""

    def __init__(
        self,
        problem_root: Path = DEFAULT_PROBLEM_ROOT,
        sample_interval_m: float = DEFAULT_DEM_SAMPLE_INTERVAL_M,
    ):
        self.problem_root = Path(problem_root).resolve()
        self.sample_interval_m = float(sample_interval_m)
        self.data: ProjectData = load_project_data(self.problem_root)
        self.dem = DemGrid(self.data.files.dem_tif)
        self._geometry_cache: Dict[Tuple[str, str], dict] = {}

    @property
    def source_manifest(self) -> dict:
        files = self.data.files
        return {
            "problem_docx": str(files.problem_docx),
            "nodes_xlsx": str(files.nodes_xlsx),
            "transport_xlsx": str(files.transport_xlsx),
            "dem_tif": str(files.dem_tif),
            "spatial_pdf": str(files.spatial_pdf),
        }

    def _get_node(self, node_id: str) -> Node:
        try:
            return self.data.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"未知任务节点：{node_id}") from exc

    def _get_model(self, model_id: str) -> TransportModel:
        try:
            return self.data.models[model_id]
        except KeyError as exc:
            raise KeyError(f"未知运输无人机机型：{model_id}") from exc

    @staticmethod
    def _work_altitude_m(node: Node) -> float:
        if node.node_id == "O01":
            return node.ground_elevation_m
        return node.ground_elevation_m + SERVICE_WORK_HEIGHT_AGL_M

    def terrain_profile(self, start_node: str, end_node: str) -> TerrainProfile:
        start = self._get_node(start_node)
        end = self._get_node(end_node)
        if start_node == end_node:
            raise ValueError("起点和终点不能相同")
        return self.dem.sample_profile(
            start.longitude_deg,
            start.latitude_deg,
            end.longitude_deg,
            end.latitude_deg,
            self.sample_interval_m,
        )

    def calculate_geometry(self, start_node: str, end_node: str) -> dict:
        cache_key = (start_node, end_node)
        cached = self._geometry_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        start = self._get_node(start_node)
        end = self._get_node(end_node)
        profile = self.terrain_profile(start_node, end_node)
        cruise_altitude_m = profile.max_terrain_elevation_m + CRUISE_CLEARANCE_M
        start_work_altitude_m = self._work_altitude_m(start)
        end_work_altitude_m = self._work_altitude_m(end)
        result = {
            "start_node": start_node,
            "end_node": end_node,
            "start_lon_deg": start.longitude_deg,
            "start_lat_deg": start.latitude_deg,
            "end_lon_deg": end.longitude_deg,
            "end_lat_deg": end.latitude_deg,
            "start_ground_elev_m": start.ground_elevation_m,
            "end_ground_elev_m": end.ground_elevation_m,
            "horizontal_distance_m": profile.horizontal_distance_m,
            "max_terrain_elev_m": profile.max_terrain_elevation_m,
            "max_terrain_lon_deg": profile.max_terrain_longitude_deg,
            "max_terrain_lat_deg": profile.max_terrain_latitude_deg,
            "cruise_altitude_m": cruise_altitude_m,
            "start_work_altitude_m": start_work_altitude_m,
            "end_work_altitude_m": end_work_altitude_m,
            "climb_height_m": max(0.0, cruise_altitude_m - start_work_altitude_m),
            "descent_height_m": max(0.0, cruise_altitude_m - end_work_altitude_m),
        }
        self._geometry_cache[cache_key] = result
        return dict(result)

    @staticmethod
    def equivalent_range_m(model: TransportModel, payload_kg: float) -> float:
        payload_ratio = payload_kg / model.max_payload_kg
        return model.empty_range_m - (
            model.empty_range_m - model.full_range_m
        ) * payload_ratio**1.5

    @staticmethod
    def horizontal_energy_kwh(
        model: TransportModel, horizontal_distance_m: float, equivalent_range_m: float
    ) -> float:
        """公式待人工核对：用可用能量乘以航段距离占等效航程的比例。"""
        if equivalent_range_m <= 0:
            raise ValueError("等效航程必须为正数")
        return model.usable_energy_kwh * horizontal_distance_m / equivalent_range_m

    @staticmethod
    def climb_energy_kwh(
        model: TransportModel, payload_kg: float, climb_height_m: float
    ) -> float:
        """公式待人工核对：按重力势能除以爬升效率折算为kWh。"""
        mass_kg = model.empty_mass_with_battery_kg + payload_kg
        return (
            mass_kg
            * STANDARD_GRAVITY_M_S2
            * climb_height_m
            / model.climb_efficiency
            / JOULES_PER_KWH
        )

    def calculate_segment(
        self,
        start_node: str,
        end_node: str,
        model_id: str,
        payload_kg: float,
    ) -> dict:
        model = self._get_model(model_id)
        payload = float(payload_kg)
        if not isfinite(payload):
            raise ValueError("payload_kg必须是有限数值")
        if payload < 0:
            raise ValueError("payload_kg不能小于0")
        if payload > model.max_payload_kg:
            raise ValueError(
                f"payload_kg={payload}超过机型{model_id}最大载质量{model.max_payload_kg}kg"
            )

        geometry = self.calculate_geometry(start_node, end_node)
        climb_time_s = geometry["climb_height_m"] / model.climb_speed_m_s
        cruise_time_s = geometry["horizontal_distance_m"] / model.cruise_speed_m_s
        descent_time_s = geometry["descent_height_m"] / model.descent_speed_m_s
        total_time_s = climb_time_s + cruise_time_s + descent_time_s
        equivalent_range_m = self.equivalent_range_m(model, payload)
        horizontal_energy_kwh = self.horizontal_energy_kwh(
            model, geometry["horizontal_distance_m"], equivalent_range_m
        )
        climb_energy_kwh = self.climb_energy_kwh(
            model, payload, geometry["climb_height_m"]
        )
        total_energy_kwh = horizontal_energy_kwh + climb_energy_kwh

        return {
            **geometry,
            "model_id": model_id,
            "payload_kg": payload,
            "climb_time_s": climb_time_s,
            "cruise_time_s": cruise_time_s,
            "descent_time_s": descent_time_s,
            "total_time_s": total_time_s,
            "equivalent_range_m": equivalent_range_m,
            "horizontal_energy_kwh": horizontal_energy_kwh,
            "climb_energy_kwh": climb_energy_kwh,
            "total_energy_kwh": total_energy_kwh,
            "energy_formula_status": ENERGY_FORMULA_STATUS,
        }

    def all_node_pair_geometry(self) -> list[dict]:
        rows: list[dict] = []
        node_ids = sorted(self.data.nodes, key=lambda item: (item != "O01", item))
        for start_node in node_ids:
            for end_node in node_ids:
                if start_node != end_node:
                    rows.append(self.calculate_geometry(start_node, end_node))
        return rows


_default_calculator: SegmentCalculator | None = None
_default_lock = Lock()


def calculate_segment(
    start_node: str,
    end_node: str,
    model_id: str,
    payload_kg: float,
) -> dict:
    """使用默认赛题根目录的便捷入口。"""
    global _default_calculator
    if _default_calculator is None:
        with _default_lock:
            if _default_calculator is None:
                _default_calculator = SegmentCalculator()
    return _default_calculator.calculate_segment(
        start_node=start_node,
        end_node=end_node,
        model_id=model_id,
        payload_kg=payload_kg,
    )
