"""Tests for spatial memory module."""
from __future__ import annotations

import json

import pytest

from spacetime_memory.spatial_memory import (
    SpatialMemoryMixin,
    haversine_distance,
    validate_coordinates,
)


class TestHaversineDistance:
    """Pure unit tests — no STDB connection needed."""

    def test_same_point(self):
        dist = haversine_distance(40.7128, -74.0060, 40.7128, -74.0060)
        assert dist == 0.0

    def test_new_york_to_london(self):
        # Approximate: NYC (40.7128, -74.0060) → London (51.5074, -0.1278)
        dist = haversine_distance(40.7128, -74.0060, 51.5074, -0.1278)
        assert 5500 < dist < 5600  # ~5570 km

    def test_equator_to_pole(self):
        # Equator (0, 0) → North Pole (90, 0)
        dist = haversine_distance(0, 0, 90, 0)
        assert abs(dist - 10007.5) < 1.0  # ~10,007 km (quarter of meridian)

    def test_short_distance(self):
        # ~1 km along a meridian at mid-latitudes
        dist = haversine_distance(40.0, 0, 40.009, 0)
        assert 0.9 < dist < 1.1

    def test_antipodal(self):
        # Opposite sides of earth
        dist = haversine_distance(0, 0, 0, 180)
        assert abs(dist - 20015.0) < 1.0  # ~half the equator

    def test_south_hemisphere(self):
        dist = haversine_distance(-33.8688, 151.2093, -37.8136, 144.9631)
        assert 700 < dist < 800  # Sydney → Melbourne ~713 km

    def test_haversine_symmetric(self):
        """Distance A→B should equal B→A."""
        a = (48.8566, 2.3522)  # Paris
        b = (41.9028, 12.4964)  # Rome
        assert abs(haversine_distance(*a, *b) - haversine_distance(*b, *a)) < 0.001


class TestValidateCoordinates:
    def test_valid_lat_lng(self):
        validate_coordinates(0, 0)
        validate_coordinates(90, 180)
        validate_coordinates(-90, -180)
        validate_coordinates(45.5, -122.6)

    def test_invalid_lat_above_90(self):
        with pytest.raises(ValueError, match="Latitude"):
            validate_coordinates(91, 0)

    def test_invalid_lat_below_90(self):
        with pytest.raises(ValueError, match="Latitude"):
            validate_coordinates(-91, 0)

    def test_invalid_lng_above_180(self):
        with pytest.raises(ValueError, match="Longitude"):
            validate_coordinates(0, 181)

    def test_invalid_lng_below_180(self):
        with pytest.raises(ValueError, match="Longitude"):
            validate_coordinates(0, -181)


class TestFindNearby:
    """Integration tests require a live STDB workspace."""

    def test_haversine_used_in_find_nearby(self):
        """Verify find_nearby uses haversine correctly via a mocked client."""
        class MockClient:
            def __init__(self):
                self.meta_store: dict[str, dict] = {}

            def set_memory_meta(self, memory_id, category, extra_json):
                self.meta_store[memory_id] = {"category": category, "extra_json": extra_json}
                return {"status": "ok"}

            def get_memory_meta(self, memory_id):
                return self.meta_store.get(memory_id)

            def _query(self, table_name, workspace_id=None, columns=None):
                # Return memory IDs that have been set
                return [{"id": mid} for mid in self.meta_store]

        client = MockClient()
        spatial = SpatialMemoryMixin(client)

        # Set locations for NYC and London
        spatial.set_location("mem_nyc", 40.7128, -74.0060, label="New York")
        spatial.set_location("mem_lon", 51.5074, -0.1278, label="London")

        # Find near NYC with 100km radius
        nearby_nyc = spatial.find_nearby("ws_test", 40.7128, -74.0060, radius_km=100)
        assert len(nearby_nyc) == 1
        assert nearby_nyc[0]["memory_id"] == "mem_nyc"
        assert nearby_nyc[0]["distance_km"] == 0.0
        assert nearby_nyc[0]["label"] == "New York"

        # Find near NYC with 6000km radius (should include London)
        nearby_big = spatial.find_nearby("ws_test", 40.7128, -74.0060, radius_km=6000)
        assert len(nearby_big) == 2
        # NYC should be first (closest)
        assert nearby_big[0]["memory_id"] == "mem_nyc"
        assert nearby_big[1]["memory_id"] == "mem_lon"

        # Find with very small radius — only NYC
        nearby_tiny = spatial.find_nearby("ws_test", 40.7128, -74.0060, radius_km=1)
        assert len(nearby_tiny) == 1
        assert nearby_tiny[0]["memory_id"] == "mem_nyc"


class TestSpatialMemoryMixin:
    """Unit tests for SpatialMemoryMixin methods."""

    def test_set_location_validates(self):
        class MockClient:
            def set_memory_meta(self, memory_id, category, extra_json):
                return {"status": "ok"}
            def get_memory_meta(self, memory_id):
                return None
            def _query(self, table_name, workspace_id=None, columns=None):
                return []

        spatial = SpatialMemoryMixin(MockClient())

        with pytest.raises(ValueError, match="Latitude"):
            spatial.set_location("test", 100, 0)
        with pytest.raises(ValueError, match="Longitude"):
            spatial.set_location("test", 0, -200)

    def test_clear_location(self):
        class MockClient:
            def set_memory_meta(self, memory_id, category, extra_json):
                self.last = (memory_id, category, extra_json)
                return {"status": "ok"}
            def get_memory_meta(self, memory_id):
                return None
            def _query(self, table_name, workspace_id=None, columns=None):
                return []

        spatial = SpatialMemoryMixin(MockClient())
        result = spatial.clear_location("mem_test")
        assert result["status"] == "ok"
        assert result["memory_id"] == "mem_test"

    def test_get_location_none(self):
        class MockClient:
            def get_memory_meta(self, memory_id):
                return {"extra_json": json.dumps({"not_spatial": True})}
            def _query(self, table_name, workspace_id=None, columns=None):
                return []

        spatial = SpatialMemoryMixin(MockClient())
        loc = spatial.get_location("test")
        assert loc is None

    def test_set_and_get_location(self):
        class MockClient:
            def __init__(self):
                self._meta = {}

            def set_memory_meta(self, memory_id, category, extra_json):
                self._meta[memory_id] = extra_json
                return {"status": "ok"}

            def get_memory_meta(self, memory_id):
                raw = self._meta.get(memory_id)
                if raw:
                    return {"extra_json": raw}
                return {"extra_json": "{}"}

            def _query(self, table_name, workspace_id=None, columns=None):
                return []

        spatial = SpatialMemoryMixin(MockClient())
        spatial.set_location("mem1", 48.8566, 2.3522, label="Paris")

        loc = spatial.get_location("mem1")
        assert loc is not None
        assert abs(loc["lat"] - 48.8566) < 0.001
        assert abs(loc["lng"] - 2.3522) < 0.001
        assert loc["label"] == "Paris"
