"""
app/database.py - SQLite Connection Lifecycle & Dual-Mode Factory

Provides thread-safe SQLite connection management supporting both Flask request
contexts (via flask.g.db with automatic teardown hooks) and standalone CLI/background
task contexts (via get_db_context context manager). Enforces mandatory PRAGMAs
(foreign keys, busy timeout, WAL mode) and sqlite3.Row factory across all connections.
"""

from contextlib import contextmanager
import os
import sqlite3
import sys
from typing import Optional

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
    DEFAULT_DB_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "data", "water_leveler.db"))


def resolve_db_path(db_path: Optional[str] = None) -> str:
    """
    Resolves the SQLite database path with strict precedence:
    1. Explicit function argument
    2. Flask application config (if inside app context)
    3. Environment variable 'DATABASE_PATH'
    4. Authoritative default project path (PROJECT_ROOT/data/water_leveler.db)
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


def create_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Creates and configures a new SQLite connection with mandatory enterprise PRAGMAs:
    - Foreign keys ON
    - Busy timeout 30000ms
    - WAL mode (on persistent databases)
    - Row factory sqlite3.Row
    """
    resolved_path = resolve_db_path(db_path)

    # Ensure parent directory exists before connecting
    if resolved_path != ":memory:":
        parent_dir = os.path.dirname(resolved_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(resolved_path, timeout=30.0)
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    # 1. Enforce foreign key constraints on every connection
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 2. Prevent "database is locked" errors under concurrent writes
    cursor.execute("PRAGMA busy_timeout = 30000;")

    # 3. WAL mode and normal synchronization for non-memory databases
    if resolved_path != ":memory:":
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")

    # 4. Auto-initialize schema & seed default tanks if database is fresh
    try:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tanks';")
        if not cursor.fetchone():
            from scripts.init_db import apply_schema, seed_database
            apply_schema(conn, quiet=True)
            seed_database(conn, quiet=True)
    except Exception:
        pass

    return conn


def get_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Dual-mode connection factory.
    - Inside Flask app context: Binds to flask.g.db (cached per-request).
    - Outside Flask context: Returns a fresh standalone connection.
    """
    if has_app_context() and g is not None:
        # Check if database path was overridden or different from current g.db
        if "db" not in g or g.db is None:
            g.db = create_connection(db_path)
        return g.db
    else:
        # Standalone invocation (CLI script, background runner, unit test)
        return create_connection(db_path)


def close_db(e: Optional[BaseException] = None):
    """
    Closes the request-bound database connection registered on Flask teardown.
    """
    if has_app_context() and g is not None:
        db = g.pop("db", None)
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


@contextmanager
def get_db_context(db_path: Optional[str] = None):
    """
    Context manager for standalone scripts (backup runner, simulator, migrations).
    Automatically commits on normal exit, rolls back on exception, and guarantees
    connection closure.

    Example:
        with get_db_context() as db:
            db.execute("INSERT INTO ...")
    """
    conn = create_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_app(app):
    """
    Attaches database lifecycle hooks to a Flask application instance.
    """
    app.teardown_appcontext(close_db)
