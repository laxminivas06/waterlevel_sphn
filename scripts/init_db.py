#!/usr/bin/env python3
"""
scripts/init_db.py - JSON Database Initializer & Migration Tool
HydroSense IoT - Smart Water Tank Monitoring System v2.0 (JSON Edition)

Initializes the persistent JSON database with factory defaults:
1. Users (admin)
2. Tanks (SV_BLOCK_OVER_TANK, GROUND_SUMP_TANK_01)
3. Devices (SV_BLOCK_OVER_TANK, esp32_tank_01)
4. Telemetry collection
5. Alerts collection
6. Backup records collection
7. Legacy tank_settings & water_readings
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import DATABASE_PATH as DEFAULT_DB_PATH
from app.database import get_db, JsonDatabase, get_default_seed_data


def log_message(msg: str, verbose: bool = True, quiet: bool = False):
    if not quiet and verbose:
        print(f"[init_db] {msg}")


def configure_pragmas(db=None, db_path: str = None, verbose: bool = False, quiet: bool = False):
    """Compatibility no-op for legacy caller compatibility."""
    log_message("JSON database engine configured.", verbose, quiet)


def apply_schema(db=None, verbose: bool = False, quiet: bool = False):
    """Initializes or ensures JSON collections structure exists."""
    log_message("Verifying JSON database structure...", verbose, quiet)
    database = db if isinstance(db, JsonDatabase) else get_db()
    data = database.get_data()
    defaults = get_default_seed_data()
    for key, val in defaults.items():
        if key not in data:
            data[key] = val
    database.save()
    log_message("JSON database structure verified.", verbose, quiet)


def seed_database(db=None, verbose: bool = False, quiet: bool = False):
    """Seeds factory default records into the JSON database."""
    log_message("Seeding factory default records...", verbose, quiet)
    database = db if isinstance(db, JsonDatabase) else get_db()
    database.seed_defaults(reset=False)
    log_message("Database seeding complete.", verbose, quiet)


def init_db(
    db_path: str = None,
    reset: bool = False,
    seed: bool = False,
    verbose: bool = False,
    quiet: bool = False,
) -> int:
    resolved_path = db_path or DEFAULT_DB_PATH
    log_message(f"Connecting to JSON database at: {resolved_path}", verbose, quiet)

    try:
        database = get_db(resolved_path)

        if reset:
            log_message("Resetting existing database to factory defaults...", verbose, quiet)
            database.seed_defaults(reset=True)
            log_message("Database reset complete.", verbose, quiet)
        elif seed:
            seed_database(database, verbose, quiet)
        else:
            apply_schema(database, verbose, quiet)

        log_message("JSON Database initialization completed successfully.", verbose, quiet)
        return 0
    except Exception as e:
        print(f"[init_db ERROR] Failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HydroSense IoT JSON Database Initializer")
    parser.add_argument("--db-path", default=None, help="Path to database JSON file")
    parser.add_argument("--reset", action="store_true", help="Reset all data to factory defaults")
    parser.add_argument("--seed", action="store_true", help="Seed default tanks, devices, and admin")
    parser.add_argument("--verbose", "-v", action="store_true", default=True, help="Verbose log output")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")

    args = parser.parse_args()
    exit_code = init_db(
        db_path=args.db_path,
        reset=args.reset,
        seed=args.seed,
        verbose=args.verbose and not args.quiet,
        quiet=args.quiet,
    )
    sys.exit(exit_code)
