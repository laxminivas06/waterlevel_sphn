"""
app/database.py - Lightweight JSON Database Engine & Connection Lifecycle

Replaces SQLite with a robust, thread-safe, pure-JSON flat-file database.
Provides:
- Thread-safe read/write operations using re-entrant locks (threading.RLock)
- Safe atomic persistence via temporary file writes and atomic os.replace
- Automatic file initialization and factory seeding (zero missing-table errors)
- Seamless dual-mode factory (Flask request context via flask.g.db & standalone CLI/scripts)
- Support for persistent JSON files and volatile in-memory (:memory:) databases for testing
"""

from contextlib import contextmanager
import copy
from datetime import datetime
import json
import os
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Union

# Flask is imported conditionally/safely so non-Flask scripts work cleanly
try:
    from flask import current_app, g, has_app_context
except ImportError:
    has_app_context = lambda: False
    g = None
    current_app = None

# Absolute path resolution from config
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
try:
    from app.config import DATABASE_PATH as DEFAULT_DB_PATH
except ImportError:
    DEFAULT_DB_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "data", "database.json"))

# Global registry of JSON database instances by path to share caches
_DB_REGISTRY: Dict[str, "JsonDatabase"] = {}
_REGISTRY_LOCK = threading.Lock()


def get_default_seed_data() -> Dict[str, Any]:
    """Returns factory default records for all system collections."""
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "users": [
            {
                "id": 1,
                "username": "admin",
                "password_hash": "pbkdf2:sha256:600000$hydrosense$admin",
                "email": "admin@hydrosense.local",
                "role": "admin",
                "created_at": now_ts,
            }
        ],
        "tanks": [
            {
                "tank_id": "SV_BLOCK_OVER_TANK",
                "tank_name": "Main Water Tank",
                "shape": "cylinder",
                "tank_height_cm": 200.0,
                "sensor_offset_cm": 15.0,
                "total_capacity_litres": 1000.0,
                "radius_cm": 39.89,
                "length_cm": None,
                "width_cm": None,
                "safe_max_percent": 95.0,
                "critical_low_percent": 10.0,
                "low_percent": 25.0,
                "high_percent": 85.0,
                "offline_threshold_seconds": 300,
                "created_at": now_ts,
                "updated_at": now_ts,
            },
        ],
        "devices": [
            {
                "device_id": "SV_BLOCK_OVER_TANK",
                "device_name": "Water Level Sensor",
                "tank_id": "SV_BLOCK_OVER_TANK",
                "api_key": "water_secret_key_2026",
                "ip_address": None,
                "firmware_version": "2.1.0",
                "created_at": now_ts,
                "last_seen": None,
                "is_active": 1,
            },
        ],
        "telemetry": [],
        "alerts": [],
        "backup_records": [],
        "tank_settings": {
            "id": 1,
            "tank_height_cm": 200.0,
            "total_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1000.0,
            "warning_low_percent": 25.0,
            "warning_normal_percent": 85.0,
            "low_threshold_percent": 25.0,
            "critical_low_threshold_percent": 10.0,
            "offline_threshold_seconds": 300,
            "updated_at": now_ts,
        },
        "water_readings": [],
        "backup_logs": [],
    }


class JsonDatabase:
    """
    Lightweight, thread-safe flat JSON database with atomic file updates.
    """

    def __init__(self, file_path: Optional[str] = None):
        self.file_path = file_path or DEFAULT_DB_PATH
        self.is_memory = (self.file_path == ":memory:")
        self._lock = threading.RLock()
        self._last_mtime: float = 0.0
        self._data: Dict[str, Any] = {}

        # Auto-initialize and load
        with self._lock:
            self.load()

    def _ensure_dir(self):
        """Creates parent directory if not existing."""
        if not self.is_memory and self.file_path:
            parent_dir = os.path.dirname(os.path.abspath(self.file_path))
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

    def load(self):
        """Loads data from disk if modified, or creates factory defaults."""
        with self._lock:
            if self.is_memory:
                if not self._data:
                    self._data = get_default_seed_data()
                return

            self._ensure_dir()
            if not os.path.exists(self.file_path) or os.path.getsize(self.file_path) == 0:
                self._data = get_default_seed_data()
                self.save()
                return

            try:
                mtime = os.path.getmtime(self.file_path)
                if mtime > self._last_mtime or not self._data:
                    with open(self.file_path, "r", encoding="utf-8") as f:
                        self._data = json.load(f)
                    self._last_mtime = mtime
            except Exception:
                # If corrupted or unreadable, fall back to default seed
                self._data = get_default_seed_data()
                self.save()

    def save(self):
        """Safely writes current data to disk via atomic replace."""
        with self._lock:
            if self.is_memory:
                return

            self._ensure_dir()
            abs_path = os.path.abspath(self.file_path)
            temp_path = f"{abs_path}.tmp_{os.getpid()}_{threading.get_ident()}"

            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(temp_path, abs_path)
                self._last_mtime = os.path.getmtime(abs_path)
            except Exception:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                raise

    def get_data(self) -> Dict[str, Any]:
        """Returns the in-memory database dict (reloads if changed on disk)."""
        with self._lock:
            if not self.is_memory and os.path.exists(self.file_path):
                try:
                    mtime = os.path.getmtime(self.file_path)
                    if mtime > self._last_mtime:
                        self.load()
                except OSError:
                    pass
            return self._data

    def get(self, collection: str, default: Any = None) -> Any:
        """Retrieves a top-level collection or setting."""
        with self._lock:
            data = self.get_data()
            if collection not in data:
                data[collection] = [] if default is None else default
            return data[collection]

    def set(self, collection: str, value: Any):
        """Sets a collection and persists."""
        with self._lock:
            self.get_data()[collection] = value
            self.save()

    def insert(self, collection: str, record: Dict[str, Any]) -> int:
        """
        Inserts a new record into a list collection.
        Auto-generates an integer 'id' if missing.
        Returns the record's integer id.
        """
        with self._lock:
            coll = self.get(collection, default=[])
            if not isinstance(coll, list):
                coll = []
                self.get_data()[collection] = coll

            # Auto-assign incrementing ID if not present
            if "id" not in record or not record["id"]:
                max_id = max((item.get("id", 0) for item in coll if isinstance(item, dict) and isinstance(item.get("id"), int)), default=0)
                record["id"] = max_id + 1

            coll.append(record)
            self.save()
            return record.get("id", len(coll))

    def update(
        self,
        collection: str,
        predicate: Callable[[Dict[str, Any]], bool],
        updater: Union[Dict[str, Any], Callable[[Dict[str, Any]], None]]
    ) -> int:
        """Updates all items matching predicate. Returns count of modified records."""
        with self._lock:
            coll = self.get(collection, default=[])
            if not isinstance(coll, list):
                return 0

            count = 0
            for item in coll:
                if isinstance(item, dict) and predicate(item):
                    if callable(updater):
                        updater(item)
                    elif isinstance(updater, dict):
                        item.update(updater)
                    count += 1

            if count > 0:
                self.save()
            return count

    def delete(self, collection: str, predicate: Callable[[Dict[str, Any]], bool]) -> int:
        """Deletes items matching predicate. Returns count of deleted records."""
        with self._lock:
            coll = self.get(collection, default=[])
            if not isinstance(coll, list):
                return 0

            initial_len = len(coll)
            self._data[collection] = [item for item in coll if not (isinstance(item, dict) and predicate(item))]
            deleted_count = initial_len - len(self._data[collection])
            if deleted_count > 0:
                self.save()
            return deleted_count

    def seed_defaults(self, reset: bool = False):
        """Seeds or resets the database to factory defaults."""
        with self._lock:
            if reset or not self._data:
                self._data = get_default_seed_data()
            else:
                defaults = get_default_seed_data()
                for key, val in defaults.items():
                    if key not in self._data or not self._data[key]:
                        self._data[key] = val
            self.save()


def resolve_db_path(db_path: Optional[str] = None) -> str:
    """
    Resolves the database JSON path with strict precedence:
    1. Explicit function argument
    2. Flask application config (if inside app context)
    3. Environment variable 'DATABASE_PATH'
    4. Authoritative default project path (PROJECT_ROOT/data/database.json)
    """
    if db_path:
        return db_path if db_path == ":memory:" else os.path.abspath(db_path)

    if has_app_context() and current_app and "DATABASE_PATH" in current_app.config:
        cfg_path = current_app.config["DATABASE_PATH"]
        if cfg_path:
            return cfg_path if cfg_path == ":memory:" else os.path.abspath(cfg_path)

    env_path = os.environ.get("DATABASE_PATH")
    if env_path:
        return env_path if env_path == ":memory:" else os.path.abspath(env_path)

    return DEFAULT_DB_PATH


def create_connection(db_path: Optional[str] = None) -> JsonDatabase:
    """Creates or returns a JsonDatabase instance."""
    resolved_path = resolve_db_path(db_path)
    if resolved_path == ":memory:":
        return JsonDatabase(":memory:")

    with _REGISTRY_LOCK:
        if resolved_path not in _DB_REGISTRY:
            _DB_REGISTRY[resolved_path] = JsonDatabase(resolved_path)
        return _DB_REGISTRY[resolved_path]


def get_db(db_path: Optional[str] = None) -> JsonDatabase:
    """
    Dual-mode database factory:
    - Inside Flask app context: Binds to flask.g.db.
    - Outside Flask context: Returns JsonDatabase instance.
    """
    if has_app_context() and g is not None:
        if "db" not in g or g.db is None:
            g.db = create_connection(db_path)
        return g.db
    else:
        return create_connection(db_path)


def close_db(e: Optional[BaseException] = None):
    """Flask teardown handler (saves any pending state)."""
    if has_app_context() and g is not None:
        db = g.pop("db", None)
        if db is not None and hasattr(db, "save"):
            try:
                db.save()
            except Exception:
                pass


@contextmanager
def get_db_context(db_path: Optional[str] = None):
    """
    Context manager for background tasks, CLI scripts, and backups.
    """
    db = get_db(db_path)
    try:
        yield db
        db.save()
    except Exception:
        raise


def init_app(app):
    """Attaches database lifecycle hooks and ensures database JSON file is seeded."""
    app.teardown_appcontext(close_db)

    # Initialize and seed database on startup
    with app.app_context():
        db = get_db()
        db.load()
