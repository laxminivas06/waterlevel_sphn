"""
Shared pytest fixtures and test harness for Water Leveler E2E tests.
Provides UnifiedTestClient supporting both in-process Flask test client and live server requests,
temporary database fixtures, and seed data helpers.
"""

import json
import os
import sqlite3
import sys
import tempfile
from typing import Any, Dict, Optional, Tuple
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Authoritative DDL Schema matching PROJECT.md and spec.md
AUTHORITATIVE_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    api_key TEXT NOT NULL,
    device_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_seen TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS tank_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    tank_height_cm REAL NOT NULL DEFAULT 200.0 CHECK (tank_height_cm > 0),
    sensor_offset_cm REAL NOT NULL DEFAULT 15.0 CHECK (sensor_offset_cm >= 0),
    total_capacity_litres REAL NOT NULL DEFAULT 1000.0 CHECK (total_capacity_litres > 0),
    offline_threshold_seconds INTEGER NOT NULL DEFAULT 300 CHECK (offline_threshold_seconds >= 30),
    low_threshold_percent REAL NOT NULL DEFAULT 20.0 CHECK (low_threshold_percent >= 0 AND low_threshold_percent <= 100),
    critical_low_threshold_percent REAL NOT NULL DEFAULT 10.0 CHECK (critical_low_threshold_percent >= 0 AND critical_low_threshold_percent < low_threshold_percent),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS water_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    distance_cm REAL NOT NULL CHECK (distance_cm >= 0),
    water_level_cm REAL NOT NULL CHECK (water_level_cm >= 0),
    water_percentage REAL NOT NULL CHECK (water_percentage >= 0.0 AND water_percentage <= 100.0),
    water_litres REAL NOT NULL CHECK (water_litres >= 0.0),
    timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    date TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_water_readings_timestamp ON water_readings (timestamp);
CREATE INDEX IF NOT EXISTS idx_water_readings_date ON water_readings (date);
CREATE INDEX IF NOT EXISTS idx_water_readings_device_time ON water_readings (device_id, timestamp);

CREATE TABLE IF NOT EXISTS backup_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_type TEXT NOT NULL CHECK (backup_type IN ('scheduled', 'manual')),
    file_format TEXT NOT NULL CHECK (file_format IN ('csv', 'json', 'both')),
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL CHECK (file_size_bytes >= 0),
    records_count INTEGER NOT NULL CHECK (records_count >= 0),
    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_backup_logs_created_at ON backup_logs (created_at);
"""

AUTHORITATIVE_SEED_SQL = """
INSERT OR IGNORE INTO tank_settings (
    id, tank_height_cm, sensor_offset_cm, total_capacity_litres,
    offline_threshold_seconds, low_threshold_percent, critical_low_threshold_percent
) VALUES (1, 200.0, 15.0, 1000.0, 300, 20.0, 10.0);

INSERT OR IGNORE INTO devices (
    device_id, api_key, device_name, is_active
) VALUES ('esp32_tank_01', 'water_secret_key_2026', 'Main Tank Sensor', 1);
"""


class ApiResponseWrapper:
    """Standardized response wrapper adapting both Flask TestResponse and requests.Response."""

    def __init__(self, raw_response, is_flask_response: bool = True):
        self.raw = raw_response
        self.is_flask = is_flask_response
        if is_flask_response:
            self.status_code = raw_response.status_code
            self.headers = dict(raw_response.headers)
            self._data = raw_response.data
            self._text = raw_response.get_data(as_text=True)
        else:
            self.status_code = raw_response.status_code
            self.headers = dict(raw_response.headers)
            self._data = raw_response.content
            self._text = raw_response.text

    @property
    def data(self) -> bytes:
        return self._data

    @property
    def text(self) -> str:
        return self._text

    def get_json(self, silent: bool = False) -> Any:
        try:
            return json.loads(self._text)
        except Exception:
            if silent:
                return None
            raise

    @property
    def json(self) -> Any:
        return self.get_json(silent=True)


class UnifiedTestClient:
    """
    Unified client abstraction supporting Flask test client or live HTTP server requests.
    """

    def __init__(self, flask_client=None, server_url: Optional[str] = None):
        self.flask_client = flask_client
        self.server_url = server_url.rstrip("/") if server_url else None

    def get(self, path: str, query_string: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> ApiResponseWrapper:
        if self.flask_client:
            resp = self.flask_client.get(path, query_string=query_string, headers=headers)
            return ApiResponseWrapper(resp, is_flask_response=True)
        elif self.server_url:
            import requests
            url = f"{self.server_url}{path}"
            resp = requests.get(url, params=query_string, headers=headers)
            return ApiResponseWrapper(resp, is_flask_response=False)
        else:
            pytest.fail("Backend application is not implemented or running yet.")

    def post(self, path: str, json: Optional[Dict[str, Any]] = None, data: Optional[Any] = None, headers: Optional[Dict[str, str]] = None) -> ApiResponseWrapper:
        if self.flask_client:
            resp = self.flask_client.post(path, json=json, data=data, headers=headers)
            return ApiResponseWrapper(resp, is_flask_response=True)
        elif self.server_url:
            import requests
            url = f"{self.server_url}{path}"
            resp = requests.post(url, json=json, data=data, headers=headers)
            return ApiResponseWrapper(resp, is_flask_response=False)
        else:
            pytest.fail("Backend application is not implemented or running yet.")

    def put(self, path: str, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> ApiResponseWrapper:
        if self.flask_client:
            resp = self.flask_client.put(path, json=json, headers=headers)
            return ApiResponseWrapper(resp, is_flask_response=True)
        elif self.server_url:
            import requests
            url = f"{self.server_url}{path}"
            resp = requests.put(url, json=json, headers=headers)
            return ApiResponseWrapper(resp, is_flask_response=False)
        else:
            pytest.fail("Backend application is not implemented or running yet.")

    def delete(self, path: str, headers: Optional[Dict[str, str]] = None) -> ApiResponseWrapper:
        if self.flask_client:
            resp = self.flask_client.delete(path, headers=headers)
            return ApiResponseWrapper(resp, is_flask_response=True)
        elif self.server_url:
            import requests
            url = f"{self.server_url}{path}"
            resp = requests.delete(url, headers=headers)
            return ApiResponseWrapper(resp, is_flask_response=False)
        else:
            pytest.fail("Backend application is not implemented or running yet.")


@pytest.fixture(scope="session")
def project_root() -> str:
    return PROJECT_ROOT


@pytest.fixture
def test_db_path(tmp_path) -> str:
    """Provides a fresh isolated SQLite database file with authoritative schema and seed data."""
    db_file = str(tmp_path / "test_water_leveler.db")
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Apply schema
    schema_file = os.path.join(PROJECT_ROOT, "schema.sql")
    if os.path.exists(schema_file):
        with open(schema_file, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
    else:
        conn.executescript(AUTHORITATIVE_SCHEMA_SQL)
    # Apply seed data
    conn.executescript(AUTHORITATIVE_SEED_SQL)
    conn.commit()
    conn.close()
    return db_file


@pytest.fixture
def temp_backup_dir(tmp_path) -> str:
    """Provides a fresh temporary directory for backup tests."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return str(backup_dir)


@pytest.fixture
def default_device_id() -> str:
    return "esp32_tank_01"


@pytest.fixture
def default_api_key() -> str:
    return "water_secret_key_2026"


@pytest.fixture
def valid_auth_headers(default_api_key) -> Dict[str, str]:
    return {
        "X-API-Key": default_api_key,
        "Content-Type": "application/json",
    }


@pytest.fixture
def sample_telemetry_payload(default_device_id, default_api_key) -> Dict[str, Any]:
    return {
        "device_id": default_device_id,
        "distance_cm": 42.5,
        "water_level_cm": 157.5,
        "water_percentage": 78.75,
        "water_litres": 787.5,
        "api_key": default_api_key,
    }


@pytest.fixture
def client(test_db_path, temp_backup_dir) -> UnifiedTestClient:
    """
    Provides a UnifiedTestClient instance.
    Checks environment for TEST_SERVER_URL, or attempts to instantiate Flask app.
    If backend is not yet implemented, raises pytest.fail with informative message.
    """
    server_url = os.environ.get("TEST_SERVER_URL")
    if server_url:
        return UnifiedTestClient(server_url=server_url)

    # Attempt to load Flask app
    app_instance = None
    try:
        from app import create_app
        app_instance = create_app({
            "TESTING": True,
            "DATABASE_PATH": test_db_path,
            "BACKUP_DIR": temp_backup_dir,
        })
    except ImportError:
        try:
            # Fallback to direct app or wsgi
            from wsgi import application
            app_instance = application
        except ImportError:
            try:
                import app as flask_module
                if hasattr(flask_module, "app"):
                    app_instance = flask_module.app
            except ImportError:
                pass

    if app_instance is not None:
        app_instance.config["TESTING"] = True
        app_instance.config["DATABASE_PATH"] = test_db_path
        app_instance.config["BACKUP_DIR"] = temp_backup_dir
        return UnifiedTestClient(flask_client=app_instance.test_client())

    # App not yet implemented
    pytest.fail("Backend application (Flask app) is not implemented yet. Milestone M1/M2 in progress.")
