"""Spatial memory module — geolocation storage and proximity queries.

Honcho parity: stores lat/lng coordinates associated with memories
and supports radius-based proximity queries.

All features are native — no external geospatial dependencies.
Pure Python Haversine formula for distance calculation.
Uses memory_meta for coordinate storage.
"""
from __future__ import annotations

import json
import math
from typing import Any

# Earth radius in kilometers
EARTH_RADIUS_KM = 6371.0


def haversine_distance(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> float:
    """Compute great-circle distance in kilometers between two points.

    Uses the Haversine formula — pure Python, no dependencies.
    """
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(min(1.0, a)))
    return EARTH_RADIUS_KM * c


def validate_coordinates(lat: float, lng: float) -> None:
    """Validate latitude/longitude range.

    Raises ValueError if out of range.
    """
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"Latitude must be in [-90, 90], got {lat}")
    if not (-180.0 <= lng <= 180.0):
        raise ValueError(f"Longitude must be in [-180, 180], got {lng}")


class SpatialMemoryMixin:
    """Mixin that adds spatial memory capabilities to a Client.

    Usage:
        client = Client()
        spatial = SpatialMemoryMixin(client)
        spatial.set_location(memory_id, 40.7128, -74.0060)
        nearby = spatial.find_nearby(workspace_id, 40.7128, -74.0060, radius_km=5.0)
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def set_location(
        self,
        memory_id: str,
        latitude: float,
        longitude: float,
        label: str = "",
    ) -> dict[str, Any]:
        """Record a geolocation for a memory.

        Stores lat/lng in the memory's metadata under the ``spatial`` category.

        Args:
            memory_id: The memory to associate with this location.
            latitude: WGS84 latitude (-90 to 90).
            longitude: WGS84 longitude (-180 to 180).
            label: Optional human-readable place name.

        Returns:
            Dict with ``status`` and the stored metadata.
        """
        validate_coordinates(latitude, longitude)

        extra = {
            "lat": latitude,
            "lng": longitude,
        }
        if label:
            extra["label"] = label

        try:
            self._client.set_memory_meta(
                memory_id=memory_id,
                category="spatial",
                extra_json=json.dumps(extra),
            )
            return {"status": "ok", "memory_id": memory_id, "latitude": latitude, "longitude": longitude}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_location(self, memory_id: str) -> dict[str, Any] | None:
        """Get the stored location for a memory, if any.

        Returns:
            Dict with ``lat``, ``lng``, optionally ``label``,
            or ``None`` if no spatial metadata exists.
        """
        try:
            meta = self._client.get_memory_meta(memory_id)
        except Exception:
            return None

        if not meta:
            return None

        extra = meta.get("extra_json") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except (json.JSONDecodeError, TypeError):
                return None

        lat = extra.get("lat")
        lng = extra.get("lng")
        if lat is not None and lng is not None:
            result: dict[str, Any] = {"lat": float(lat), "lng": float(lng)}
            if "label" in extra:
                result["label"] = extra["label"]
            return result
        return None

    def find_nearby(
        self,
        workspace_id: str,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find memories near a geographic point.

        Queries all memories in the workspace, checks their spatial metadata,
        and returns those within the specified radius.

        NOTE: This is a client-side scan. For workspaces with 100K+ memories
        with spatial data, consider adding a geohash index.

        Args:
            workspace_id: Target workspace.
            latitude: Center point latitude.
            longitude: Center point longitude.
            radius_km: Search radius in kilometers.
            limit: Maximum results.

        Returns:
            List of dicts with ``memory_id``, ``distance_km``, ``lat``, ``lng``,
            optionally ``label``, sorted by distance ascending.
        """
        validate_coordinates(latitude, longitude)

        # Fetch all memories (use _query through the accessor)
        try:
            memories = self._client._query(
                "memory",
                workspace_id=workspace_id,
                columns=["id", "content"],
            )
        except Exception:
            return []

        nearby: list[dict[str, Any]] = []
        for mem in memories or []:
            mem_id = mem.get("id", "")
            if not mem_id:
                continue

            loc = self.get_location(mem_id)
            if loc is None:
                continue

            dist = haversine_distance(
                latitude, longitude,
                loc["lat"], loc["lng"],
            )
            if dist <= radius_km:
                entry: dict[str, Any] = {
                    "memory_id": mem_id,
                    "distance_km": round(dist, 3),
                    "lat": loc["lat"],
                    "lng": loc["lng"],
                }
                if "label" in loc:
                    entry["label"] = loc["label"]
                nearby.append(entry)

        nearby.sort(key=lambda x: x["distance_km"])
        return nearby[:limit]

    def clear_location(self, memory_id: str) -> dict[str, Any]:
        """Remove spatial metadata from a memory.

        Uses set_memory_meta with empty extra_json to clear the spatial category.
        """
        try:
            self._client.set_memory_meta(
                memory_id=memory_id,
                category="spatial",
                extra_json="{}",
            )
            return {"status": "ok", "memory_id": memory_id}
        except Exception as e:
            return {"status": "error", "error": str(e)}
