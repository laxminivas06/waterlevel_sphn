"""
app/config.py - Application Configuration & Environment Settings

Provides robust absolute path resolution for database and backup storage,
specifically avoiding PythonAnywhere '/var/www' or '/home/<user>' working
directory permission traps during WSGI boots.
"""

import os

# Calculate authoritative project root directory using absolute path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_ROOT = BASE_DIR

# Dedicated persistent directories
DATA_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "data"))
BACKUP_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "backups"))

# Database path resolution: Environment variable takes precedence, followed by canonical path
DATABASE_PATH = os.environ.get("DATABASE_PATH")
if DATABASE_PATH:
    DATABASE_PATH = os.path.abspath(DATABASE_PATH)
else:
    DATABASE_PATH = os.path.abspath(os.path.join(DATA_DIR, "water_leveler.db"))

# Application Security & Defaults
SECRET_KEY = os.environ.get("SECRET_KEY", "water_leveler_default_secret_key_2026")
DEFAULT_DEVICE_ID = os.environ.get("DEFAULT_DEVICE_ID", "esp32_tank_01")
DEFAULT_API_KEY = os.environ.get("DEFAULT_API_KEY", "water_secret_key_2026")

# Telemetry and sensor timeouts
OFFLINE_THRESHOLD_SECONDS = int(os.environ.get("OFFLINE_THRESHOLD_SECONDS", 300))
DEVICE_TIMEOUT_SECONDS = OFFLINE_THRESHOLD_SECONDS


class Config:
    """Base configuration with production-ready defaults."""
    PROJECT_ROOT = PROJECT_ROOT
    DATA_DIR = DATA_DIR
    BACKUP_DIR = BACKUP_DIR
    DATABASE_PATH = DATABASE_PATH
    SECRET_KEY = SECRET_KEY

    # Device defaults
    DEFAULT_DEVICE_ID = DEFAULT_DEVICE_ID
    DEFAULT_API_KEY = DEFAULT_API_KEY
    OFFLINE_THRESHOLD_SECONDS = OFFLINE_THRESHOLD_SECONDS
    DEVICE_TIMEOUT_SECONDS = DEVICE_TIMEOUT_SECONDS

    # Concurrency and timeout
    DB_BUSY_TIMEOUT_MS = 30000

    # Operational modes
    TESTING = False
    DEBUG = False


class DevelopmentConfig(Config):
    """Development environment settings."""
    DEBUG = True


class TestingConfig(Config):
    """Testing environment configuration."""
    TESTING = True
    DATABASE_PATH = ":memory:"
    BACKUP_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "backups", "test"))


class ProductionConfig(Config):
    """Production deployment configuration for PythonAnywhere."""
    DEBUG = False
    TESTING = False


# Environment dictionary for dynamic config selection
config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": Config,
}
