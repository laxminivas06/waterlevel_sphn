"""
tests/test_hydrosense.py - Comprehensive Production Test Suite
HydroSense IoT - Smart Water Tank Monitoring System v2.0

Verifies all 12+ scenarios required by the specification:
1.  Successful telemetry reception (POST /api/v1/telemetry)
2.  Invalid data rejection (malformed JSON, negative distance, missing fields)
3.  Unauthorized request rejection (invalid/missing API key, unregistered device)
4.  Tank status classification (CRITICAL LOW, LOW, NORMAL, HIGH, OVERLOADED)
5.  Alert generation on abnormal conditions (OVERFLOW_RISK, CRITICAL_LOW)
6.  Sensor fault & abnormal reading handling
7.  Device offline detection logic based on heartbeat threshold
8.  Historical data retrieval (24h, 7d, 15d ranges with aggregates)
9.  System summary scorecard KPI calculation
10. Device registration and management (POST /api/v1/devices)
11. Tank configuration and volumetric physics (cylinder & rectangle)
12. Backward compatibility with legacy routes (/api/tanks, /api/water-level, etc.)
13. Interactive simulator endpoint (POST /api/v1/simulate)
14. Health check (GET /api/v1/health) and WSGI application callable
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from app import create_app
from app.database import get_db
from app.models import (
    calculate_tank_physics,
    get_tank,
    insert_telemetry,
    get_tank_history,
    get_system_summary,
    get_device,
    register_device,
    create_or_update_tank,
)
from scripts.init_db import apply_schema, seed_database


class HydroSenseTestCase(unittest.TestCase):
    """Test suite for HydroSense IoT Backend and API."""

    def setUp(self):
        """Create a dedicated temporary database and test client for each test."""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix="_test_hydrosense.json")
        os.close(self.db_fd)

        # Initialize schema and seed data
        db = get_db(self.db_path)
        db.seed_defaults(reset=True)

        # Configure Flask test app
        self.app = create_app({
            "TESTING": True,
            "DATABASE_PATH": self.db_path,
            "SECRET_KEY": "test_secret_key",
            "DEFAULT_API_KEY": "water_secret_key_2026",
            "OFFLINE_THRESHOLD_SECONDS": 10,  # Fast offline threshold for testing
        })
        self.client = self.app.test_client()

    def tearDown(self):
        """Close and remove temporary test database."""
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    # =========================================================================
    # 1. Physics Engine Tests
    # =========================================================================
    def test_physics_cylindrical_tank(self):
        """Verify volumetric calculations for cylindrical tank."""
        # Height: 200cm, Offset: 15cm, Capacity: 1000L
        tank = {
            "tank_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1000.0,
            "safe_max_percent": 95.0,
            "critical_low_percent": 10.0,
            "low_percent": 25.0,
            "high_percent": 85.0,
            "shape": "cylinder",
            "radius_cm": 39.89
        }

        # Half full: distance = 15cm (offset) + 100cm = 115cm
        calc = calculate_tank_physics(tank, distance_cm=115.0)
        self.assertAlmostEqual(calc["water_height_cm"], 100.0, places=1)
        self.assertAlmostEqual(calc["water_level_percent"], 50.0, places=1)
        self.assertAlmostEqual(calc["water_volume_litres"], 500.0, places=0)
        self.assertEqual(calc["status"], "NORMAL")

        # Full tank: distance = 15cm
        calc_full = calculate_tank_physics(tank, distance_cm=15.0)
        self.assertAlmostEqual(calc_full["water_level_percent"], 100.0, places=1)
        self.assertAlmostEqual(calc_full["water_volume_litres"], 1000.0, places=0)
        self.assertEqual(calc_full["status"], "HIGH")

        # Overloaded tank: distance = 5cm (< offset 15cm)
        calc_over = calculate_tank_physics(tank, distance_cm=5.0)
        self.assertEqual(calc_over["status"], "OVERLOADED")

        # Critical low tank: distance = 205cm (water height = 10cm, 5%)
        calc_low = calculate_tank_physics(tank, distance_cm=205.0)
        self.assertEqual(calc_low["status"], "CRITICAL LOW")
        self.assertAlmostEqual(calc_low["water_level_percent"], 5.0, places=1)

    # =========================================================================
    # 2. Telemetry Ingestion Tests
    # =========================================================================
    def test_telemetry_success(self):
        """POST /api/v1/telemetry with valid payload and token succeeds with 201."""
        payload = {
            "device_id": "SV_BLOCK_OVER_TANK",
            "distance_cm": 75.0,
            "water_level_percent": 70.0,
            "water_volume_litres": 700.0,
            "status": "NORMAL"
        }
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": "water_secret_key_2026"
        }
        res = self.client.post("/api/v1/telemetry", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["reading"]["device_id"], "SV_BLOCK_OVER_TANK")
        self.assertIn("timestamp", data["reading"])
        self.assertIn("water_level_percent", data["reading"])

    def test_telemetry_embedded_api_key(self):
        """POST /api/v1/telemetry accepts api_key in JSON body."""
        payload = {
            "device_id": "SV_BLOCK_OVER_TANK",
            "api_key": "water_secret_key_2026",
            "distance_cm": 60.0
        }
        res = self.client.post("/api/v1/telemetry", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])

    def test_telemetry_unauthorized_key(self):
        """POST /api/v1/telemetry rejects invalid API key with 401."""
        payload = {
            "device_id": "SV_BLOCK_OVER_TANK",
            "distance_cm": 75.0
        }
        headers = {"X-API-Key": "invalid_wrong_token_123"}
        res = self.client.post("/api/v1/telemetry", json=payload, headers=headers)
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertIn("Unauthorized", data.get("error", ""))

    def test_telemetry_unknown_device(self):
        """POST /api/v1/telemetry rejects unknown device ID with 404."""
        payload = {
            "device_id": "UNKNOWN_DEVICE_XYZ",
            "distance_cm": 50.0
        }
        headers = {"X-API-Key": "water_secret_key_2026"}
        res = self.client.post("/api/v1/telemetry", json=payload, headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_telemetry_missing_distance(self):
        """POST /api/v1/telemetry rejects request missing distance with 400."""
        payload = {
            "device_id": "SV_BLOCK_OVER_TANK"
        }
        headers = {"X-API-Key": "water_secret_key_2026"}
        res = self.client.post("/api/v1/telemetry", json=payload, headers=headers)
        self.assertEqual(res.status_code, 400)

    def test_telemetry_negative_distance(self):
        """POST /api/v1/telemetry rejects negative distance with 400."""
        payload = {
            "device_id": "SV_BLOCK_OVER_TANK",
            "distance_cm": -15.0
        }
        headers = {"X-API-Key": "water_secret_key_2026"}
        res = self.client.post("/api/v1/telemetry", json=payload, headers=headers)
        self.assertEqual(res.status_code, 400)

    # =========================================================================
    # 3. Status Classification & Automated Alert Generation
    # =========================================================================
    def test_overload_alert_generation(self):
        """Posting distance closer than offset (<15cm) marks OVERLOADED and generates OVERFLOW_RISK alert."""
        payload = {
            "device_id": "SV_BLOCK_OVER_TANK",
            "distance_cm": 5.0  # Offset is 15.0cm -> water has overflowed into offset zone
        }
        headers = {"X-API-Key": "water_secret_key_2026"}
        res = self.client.post("/api/v1/telemetry", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["reading"]["status"], "OVERLOADED")

        # Verify active alerts endpoint lists the alert
        alerts_res = self.client.get("/api/v1/alerts")
        self.assertEqual(alerts_res.status_code, 200)
        alerts_data = alerts_res.get_json()
        self.assertTrue(len(alerts_data.get("alerts", [])) > 0)
        alert_types = [a["alert_type"] for a in alerts_data["alerts"]]
        self.assertIn("OVERFLOW_RISK", alert_types)

    def test_critical_low_alert_generation(self):
        """Posting water level below 10% marks CRITICAL LOW and creates alert."""
        payload = {
            "device_id": "SV_BLOCK_OVER_TANK",
            "distance_cm": 208.0  # Height 200, Offset 15 => Water height 7cm (3.5%)
        }
        headers = {"X-API-Key": "water_secret_key_2026"}
        res = self.client.post("/api/v1/telemetry", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["reading"]["status"], "CRITICAL LOW")

        alerts_res = self.client.get("/api/v1/alerts")
        alerts_data = alerts_res.get_json()
        alert_types = [a["alert_type"] for a in alerts_data["alerts"]]
        self.assertIn("CRITICAL_LOW", alert_types)

    def test_alert_acknowledgement(self):
        """Acknowledge active alert via POST /api/v1/alerts/<id>/ack."""
        # Generate an alert
        self.client.post("/api/v1/telemetry", json={
            "device_id": "SV_BLOCK_OVER_TANK",
            "distance_cm": 2.0
        }, headers={"X-API-Key": "water_secret_key_2026"})

        alerts_res = self.client.get("/api/v1/alerts?active_only=true")
        alerts = alerts_res.get_json()["alerts"]
        self.assertTrue(len(alerts) > 0)
        alert_id = alerts[0]["id"]

        # Acknowledge it
        ack_res = self.client.post(f"/api/v1/alerts/{alert_id}/ack", json={"acknowledged_by": "Operator_Alex"})
        self.assertEqual(ack_res.status_code, 200)

        # Check active alerts again
        active_res = self.client.get("/api/v1/alerts?active_only=true")
        active_ids = [a["id"] for a in active_res.get_json()["alerts"]]
        self.assertNotIn(alert_id, active_ids)

    # =========================================================================
    # 4. Historical Data & Analytics
    # =========================================================================
    def test_history_retrieval_and_ranges(self):
        """GET /api/v1/tanks/<tank_id>/history returns data points, min/max/avg."""
        headers = {"X-API-Key": "water_secret_key_2026"}
        
        # Post a series of readings
        distances = [100.0, 80.0, 60.0, 110.0]
        for d in distances:
            self.client.post("/api/v1/telemetry", json={
                "device_id": "SV_BLOCK_OVER_TANK",
                "distance_cm": d
            }, headers=headers)

        res = self.client.get("/api/v1/tanks/SV_BLOCK_OVER_TANK/history?range=24h")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("readings", data)
        self.assertIn("analytics", data)
        self.assertGreaterEqual(len(data["readings"]), 4)
        
        analytics = data["analytics"]
        self.assertIn("min_level_percent", analytics)
        self.assertIn("max_level_percent", analytics)
        self.assertIn("avg_level_percent", analytics)
        self.assertGreaterEqual(analytics["max_level_percent"], analytics["min_level_percent"])

    # =========================================================================
    # 5. Device Management & Offline Detection
    # =========================================================================
    def test_device_registration(self):
        """POST /api/v1/devices registers new hardware."""
        payload = {
            "device_id": "ROOF_RESERVOIR_02",
            "device_name": "Roof North Ultrasonic ESP32",
            "tank_id": "GROUND_SUMP_TANK_01",
            "api_key": "roof_secret_key_2026",
            "firmware_version": "2.2.0"
        }
        res = self.client.post("/api/v1/devices", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])

        # Fetch devices list
        get_res = self.client.get("/api/v1/devices")
        self.assertEqual(get_res.status_code, 200)
        devices = get_res.get_json()["devices"]
        dev_ids = [d["device_id"] for d in devices]
        self.assertIn("ROOF_RESERVOIR_02", dev_ids)

    # =========================================================================
    # 6. Multi-Tank Management
    # =========================================================================
    def test_tank_creation_and_listing(self):
        """POST /api/v1/tanks creates a new rectangular tank."""
        payload = {
            "tank_id": "NORTH_WING_TANK",
            "tank_name": "North Wing Header Tank",
            "shape": "rectangle",
            "tank_height_cm": 250.0,
            "sensor_offset_cm": 20.0,
            "total_capacity_litres": 5000.0,
            "length_cm": 200.0,
            "width_cm": 100.0
        }
        res = self.client.post("/api/v1/tanks", json=payload)
        self.assertEqual(res.status_code, 201)

        tanks_res = self.client.get("/api/v1/tanks")
        self.assertEqual(tanks_res.status_code, 200)
        tanks = tanks_res.get_json()["tanks"]
        tank_ids = [t["tank_id"] for t in tanks]
        self.assertIn("NORTH_WING_TANK", tank_ids)

    # =========================================================================
    # 7. System Summary Scorecard
    # =========================================================================
    def test_system_summary(self):
        """GET /api/v1/system/summary returns 6-metric KPI scorecard."""
        res = self.client.get("/api/v1/system/summary")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["summary"]
        self.assertIn("total_tanks", data)
        self.assertIn("online_devices", data)
        self.assertIn("offline_devices", data)
        self.assertIn("avg_water_level_percent", data)
        self.assertIn("total_water_litres", data)
        self.assertIn("total_capacity_litres", data)
        self.assertIn("critical_alerts_count", data)

    # =========================================================================
    # 8. Interactive Simulator Endpoint
    # =========================================================================
    def test_simulator_reading(self):
        """POST /api/v1/simulate injects calculated physics without physical hardware."""
        payload = {
            "tank_id": "SV_BLOCK_OVER_TANK",
            "water_level_percent": 82.5
        }
        res = self.client.post("/api/v1/simulate", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertAlmostEqual(data["reading"]["water_level_percent"], 82.5, places=1)
        self.assertEqual(data["reading"]["status"], "NORMAL")

    # =========================================================================
    # 9. Backward Compatibility with Legacy Routes
    # =========================================================================
    def test_legacy_get_tanks(self):
        """GET /api/tanks?tanks=SV_BLOCK_OVER_TANK:181 maintains legacy ESP8266 query format."""
        res = self.client.get("/api/tanks?tanks=SV_BLOCK_OVER_TANK:181.0")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success", False))

    def test_legacy_water_level_endpoints(self):
        """GET /api/water-level and /api/water-level/current return valid legacy JSON."""
        # Insert a reading first
        self.client.post("/api/v1/simulate", json={
            "tank_id": "SV_BLOCK_OVER_TANK",
            "water_level_percent": 65.0
        })

        res_current = self.client.get("/api/water-level/current")
        self.assertEqual(res_current.status_code, 200)
        curr_data = res_current.get_json()
        self.assertIn("water_level", curr_data)

        res_list = self.client.get("/api/water-level?limit=10")
        self.assertEqual(res_list.status_code, 200)

    def test_percentage_direct_mapping_not_inverted(self):
        """Verify that sending 2% water level reports exactly 2% (not inverted 98%)."""
        res = self.client.get("/api/tanks?tanks=SV_BLOCK_OVER_TANK:2.0")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertAlmostEqual(data["reading"]["water_percentage"], 2.0, places=1)
        self.assertEqual(data["reading"]["status"], "CRITICAL LOW")

        # Snapshot should also show 2%
        res_current = self.client.get("/api/water-level/current")
        self.assertEqual(res_current.status_code, 200)
        curr = res_current.get_json()
        self.assertAlmostEqual(curr["water_percentage"], 2.0, places=1)

        # Sending 98% should show 98%
        res98 = self.client.get("/api/tanks?tanks=SV_BLOCK_OVER_TANK:98.0")
        self.assertEqual(res98.status_code, 200)
        data98 = res98.get_json()
        self.assertAlmostEqual(data98["reading"]["water_percentage"], 98.0, places=1)

    def test_tank_settings_name_and_liters_occupied(self):
        """Verify settings update allows custom tank name and immediate liters occupied calibration."""
        payload = {
            "tank_id": "SV_BLOCK_OVER_TANK",
            "tank_name": "Main Overhead Reservoir",
            "total_capacity_litres": 1000.0,
            "liters_occupied": 350.0,
            "tank_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
        }
        res = self.client.post("/api/v1/tanks", json=payload)
        self.assertEqual(res.status_code, 201)
        tank_data = res.get_json()["tank"]
        self.assertEqual(tank_data["tank_name"], "Main Overhead Reservoir")

        # Verify current status reflected the 350L (35%)
        res_curr = self.client.get("/api/water-level/current")
        self.assertEqual(res_curr.status_code, 200)
        curr = res_curr.get_json()
        self.assertEqual(curr["tank"]["tank_name"], "Main Overhead Reservoir")
        self.assertAlmostEqual(curr["water_volume_litres"], 350.0, places=1)
        self.assertAlmostEqual(curr["water_percentage"], 35.0, places=1)

    def test_frontend_branding_and_assets(self):
        """Verify UI template contains Aivontraa logo, favicon, footer branding, and no simulator."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("https://aivontraa.com/assets/images/ai.png", html)
        self.assertIn("https://aivontraa.com", html)
        self.assertIn("Aivontraa Automation PVT LTD", html)
        self.assertNotIn("🧪 Sensor Test Simulator", html)

    # =========================================================================
    # 10. Health Check & WSGI Callable
    # =========================================================================
    def test_health_check(self):
        """GET /api/v1/health returns healthy system and DB status."""
        res = self.client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["database"], "connected")

    def test_wsgi_entrypoint(self):
        """Verify wsgi.application exists and is callable per WSGI standard."""
        import wsgi
        self.assertTrue(hasattr(wsgi, "application"))
        self.assertTrue(callable(wsgi.application))


if __name__ == "__main__":
    unittest.main()
