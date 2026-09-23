"""GeoTIFF DEM 读取、WGS84测地距离和航段高程采样。"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
from PIL import Image
from pyproj import Geod

from .config import DECLARED_DEM_NODATA, DEFAULT_DEM_SAMPLE_INTERVAL_M


@dataclass(frozen=True)
class TerrainProfile:
    distance_m: np.ndarray
    longitude_deg: np.ndarray
    latitude_deg: np.ndarray
    elevation_m: np.ndarray
    horizontal_distance_m: float
    max_terrain_elevation_m: float
    max_terrain_longitude_deg: float
    max_terrain_latitude_deg: float


class DemGrid:
    """一次加载、重复查询的WGS84 DEM。"""

    def __init__(self, path: Path, nodata_value: float = DECLARED_DEM_NODATA):
        self.path = Path(path).resolve()
        with Image.open(self.path) as image:
            self._array = np.asarray(image, dtype=np.float64).copy()
            tags = dict(image.tag_v2)
            self.width, self.height = image.size

        try:
            scale = tuple(float(v) for v in tags[33550])
            tiepoint = tuple(float(v) for v in tags[33922])
        except KeyError as exc:
            raise ValueError("DEM缺少GeoTIFF像元尺度或地理配准标签") from exc

        self.pixel_width_deg = scale[0]
        self.pixel_height_deg = scale[1]
        self.tie_col = tiepoint[0]
        self.tie_row = tiepoint[1]
        self.tie_lon_deg = tiepoint[3]
        self.tie_lat_deg = tiepoint[4]
        self.nodata_value = self._parse_nodata(tags, nodata_value)
        self.epsg = self._parse_epsg(tags)
        self.raster_pixel_is_point = self._parse_raster_type(tags) == 2
        if self.epsg != 4326:
            raise ValueError(f"DEM坐标系应为EPSG:4326，实际为EPSG:{self.epsg}")

        self._geod = Geod(ellps="WGS84")
        self._profile_cache: Dict[Tuple[float, ...], TerrainProfile] = {}

    @staticmethod
    def _parse_nodata(tags: dict, fallback: float) -> float:
        raw = tags.get(42113, fallback)
        if isinstance(raw, (tuple, list)):
            raw = raw[0]
        try:
            return float(str(raw).strip().strip("\x00"))
        except ValueError:
            return float(fallback)

    @staticmethod
    def _parse_geokeys(tags: dict) -> dict[int, int]:
        raw = tags.get(34735)
        if raw is None:
            return {}
        values = [int(v) for v in raw]
        key_count = values[3]
        keys: dict[int, int] = {}
        for index in range(key_count):
            base = 4 + 4 * index
            key_id, tag_location, count, value = values[base : base + 4]
            if tag_location == 0 and count == 1:
                keys[key_id] = value
        return keys

    @classmethod
    def _parse_epsg(cls, tags: dict) -> int:
        keys = cls._parse_geokeys(tags)
        return int(keys.get(2048, -1))

    @classmethod
    def _parse_raster_type(cls, tags: dict) -> int:
        keys = cls._parse_geokeys(tags)
        return int(keys.get(1025, 1))

    @property
    def metadata(self) -> dict:
        valid = self._array[self._array != self.nodata_value]
        return {
            "path": str(self.path),
            "epsg": self.epsg,
            "width": self.width,
            "height": self.height,
            "pixel_width_deg": self.pixel_width_deg,
            "pixel_height_deg": self.pixel_height_deg,
            "tie_lon_deg": self.tie_lon_deg,
            "tie_lat_deg": self.tie_lat_deg,
            "raster_pixel_is_point": self.raster_pixel_is_point,
            "nodata_value": self.nodata_value,
            "valid_min_elevation_m": float(valid.min()),
            "valid_max_elevation_m": float(valid.max()),
        }

    def _lonlat_to_rowcol(self, longitude_deg: float, latitude_deg: float) -> tuple[int, int]:
        col_float = self.tie_col + (longitude_deg - self.tie_lon_deg) / self.pixel_width_deg
        row_float = self.tie_row + (self.tie_lat_deg - latitude_deg) / self.pixel_height_deg
        if self.raster_pixel_is_point:
            col, row = int(round(col_float)), int(round(row_float))
        else:
            col, row = int(np.floor(col_float)), int(np.floor(row_float))
        if not (0 <= row < self.height and 0 <= col < self.width):
            raise ValueError(
                f"坐标超出DEM范围：lon={longitude_deg}, lat={latitude_deg}, row={row}, col={col}"
            )
        return row, col

    def elevation_at(self, longitude_deg: float, latitude_deg: float) -> float | None:
        row, col = self._lonlat_to_rowcol(longitude_deg, latitude_deg)
        value = float(self._array[row, col])
        if not np.isfinite(value) or np.isclose(value, self.nodata_value):
            return None
        return value

    def sample_profile(
        self,
        start_lon_deg: float,
        start_lat_deg: float,
        end_lon_deg: float,
        end_lat_deg: float,
        sample_interval_m: float = DEFAULT_DEM_SAMPLE_INTERVAL_M,
    ) -> TerrainProfile:
        if sample_interval_m <= 0:
            raise ValueError("DEM采样间隔必须为正数")
        key = tuple(
            round(value, 9)
            for value in (
                start_lon_deg,
                start_lat_deg,
                end_lon_deg,
                end_lat_deg,
                sample_interval_m,
            )
        )
        cached = self._profile_cache.get(key)
        if cached is not None:
            return cached

        forward_azimuth, _, total_distance_m = self._geod.inv(
            start_lon_deg, start_lat_deg, end_lon_deg, end_lat_deg
        )
        segments = max(1, int(ceil(total_distance_m / sample_interval_m)))
        distances = np.linspace(0.0, total_distance_m, segments + 1)
        longitudes = np.empty(segments + 1, dtype=np.float64)
        latitudes = np.empty(segments + 1, dtype=np.float64)
        elevations = np.full(segments + 1, np.nan, dtype=np.float64)

        for index, distance_m in enumerate(distances):
            lon, lat, _ = self._geod.fwd(
                start_lon_deg, start_lat_deg, forward_azimuth, float(distance_m)
            )
            longitudes[index] = lon
            latitudes[index] = lat
            elevation = self.elevation_at(lon, lat)
            if elevation is not None:
                elevations[index] = elevation

        if np.all(np.isnan(elevations)):
            raise ValueError("航段所有DEM采样点均为NoData")
        max_index = int(np.nanargmax(elevations))
        profile = TerrainProfile(
            distance_m=distances,
            longitude_deg=longitudes,
            latitude_deg=latitudes,
            elevation_m=elevations,
            horizontal_distance_m=float(total_distance_m),
            max_terrain_elevation_m=float(elevations[max_index]),
            max_terrain_longitude_deg=float(longitudes[max_index]),
            max_terrain_latitude_deg=float(latitudes[max_index]),
        )
        self._profile_cache[key] = profile
        return profile

    def get_max_terrain_elevation(
        self,
        start_lon_deg: float,
        start_lat_deg: float,
        end_lon_deg: float,
        end_lat_deg: float,
        sample_interval_m: float = DEFAULT_DEM_SAMPLE_INTERVAL_M,
    ) -> dict:
        profile = self.sample_profile(
            start_lon_deg,
            start_lat_deg,
            end_lon_deg,
            end_lat_deg,
            sample_interval_m,
        )
        return {
            "horizontal_distance_m": profile.horizontal_distance_m,
            "max_terrain_elevation_m": profile.max_terrain_elevation_m,
            "max_terrain_longitude_deg": profile.max_terrain_longitude_deg,
            "max_terrain_latitude_deg": profile.max_terrain_latitude_deg,
        }
