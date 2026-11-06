#!/usr/bin/env python3
"""
ESP32 Telemetry Simulation Script for Smart Water Tank Level Monitoring System.

Simulates single or continuous sensor telemetry POST requests from an ESP32 NodeMCU
to the Flask backend API (/api/water-level) with configurable parameters, authentication
modes, tank volumetric math, and sensor jitter.
"""

import argparse
import json
import random
import sys
import time
from typing import Any, Dict, Optional, Tuple

# Support both requests library and standard urllib for resilience
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.error
    import urllib.request
    HAS_REQUESTS = False


DEFAULT_URL = "http://127.0.0.1:5000/api/water-level"
DEFAULT_DEVICE_ID = "esp32_tank_01"
DEFAULT_API_KEY = "water_secret_key_2026"
DEFAULT_TANK_HEIGHT = 200.0     # cm
DEFAULT_SENSOR_OFFSET = 15.0    # cm
DEFAULT_CAPACITY_LITRES = 1000.0 # L


def calculate_tank_metrics(
    distance_cm: float,
    tank_height_cm: float = DEFAULT_TANK_HEIGHT,
    sensor_offset_cm: float = DEFAULT_SENSOR_OFFSET,
    total_capacity_litres: float = DEFAULT_CAPACITY_LITRES,
) -> Tuple[float, float, float]:
    """
    Calculate water_level_cm, water_percentage, and water_litres from distance_cm.

    Physics model:
      - Sensor is mounted at tank_height_cm + sensor_offset_cm from the tank bottom.
      - When distance_cm <= sensor_offset_cm: tank is 100% full (water touched/reached sensor offset).
      - Effective air gap = max(0.0, distance_cm - sensor_offset_cm).
      - water_level_cm = max(0.0, min(tank_height_cm, tank_height_cm - effective_air_gap)).
      - water_percentage = max(0.0, min(100.0, (water_level_cm / tank_height_cm) * 100.0)).
      - water_litres = max(0.0, (water_percentage / 100.0) * total_capacity_litres).
    """
    effective_air_gap = max(0.0, float(distance_cm) - float(sensor_offset_cm))
    water_level = max(0.0, min(float(tank_height_cm), float(tank_height_cm) - effective_air_gap))
    water_percentage = max(0.0, min(100.0, (water_level / float(tank_height_cm)) * 100.0))
    water_litres = max(0.0, (water_percentage / 100.0) * float(total_capacity_litres))

    return round(water_level, 2), round(water_percentage, 2), round(water_litres, 2)


def build_payload(
    device_id: str = DEFAULT_DEVICE_ID,
    distance_cm: float = 42.5,
    water_level_cm: float = 157.5,
    water_percentage: float = 78.75,
    water_litres: float = 787.5,
    api_key: Optional[str] = DEFAULT_API_KEY,
    auth_mode: str = "header",
) -> Dict[str, Any]:
    """
    Construct JSON telemetry dictionary.
    Auth mode controls whether api_key is included in payload body.
    """
    payload: Dict[str, Any] = {
        "device_id": str(device_id),
        "distance_cm": float(distance_cm),
        "water_level_cm": float(water_level_cm),
        "water_percentage": float(water_percentage),
        "water_litres": float(water_litres),
    }

    if auth_mode in ("body", "both") and api_key is not None:
        payload["api_key"] = api_key

    return payload


def send_telemetry(
    url: str,
    payload: Dict[str, Any],
    api_key: Optional[str] = DEFAULT_API_KEY,
    auth_mode: str = "header",
    timeout: float = 10.0,
) -> Tuple[int, Dict[str, Any]]:
    """
    Send HTTP POST telemetry payload to the specified URL.
    Returns (status_code, response_data).
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if auth_mode in ("header", "both") and api_key is not None:
        headers["X-API-Key"] = api_key

    if HAS_REQUESTS:
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            try:
                resp_data = resp.json()
            except ValueError:
                resp_data = {"raw_text": resp.text}
            return resp.status_code, resp_data
        except requests.RequestException as e:
            return 0, {"error": f"Request failed: {e}"}
    else:
        # Standard library urllib fallback
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8")
                try:
                    resp_data = json.loads(body)
                except ValueError:
                    resp_data = {"raw_text": body}
                return status_code, resp_data
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            try:
                resp_data = json.loads(body)
            except ValueError:
                resp_data = {"raw_text": body}
            return e.code, resp_data
        except Exception as e:
            return 0, {"error": f"Request failed: {e}"}


def parse_arguments(args=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ESP32 Telemetry Simulator for Smart Water Tank Monitoring System"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Target ingestion URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--device-id",
        "-d",
        default=DEFAULT_DEVICE_ID,
        help=f"Device identifier (default: {DEFAULT_DEVICE_ID})",
    )
    parser.add_argument(
        "--api-key",
        "-k",
        default=DEFAULT_API_KEY,
        help=f"Device API key (default: {DEFAULT_API_KEY})",
    )
    parser.add_argument(
        "--auth-mode",
        choices=["header", "body", "both", "none"],
        default="header",
        help="Where to transmit API key: header (X-API-Key), body (api_key in JSON), both, or none (default: header)",
    )
    parser.add_argument(
        "--distance",
        "--distance-cm",
        type=float,
        default=42.5,
        dest="distance_cm",
        help="Raw ultrasonic distance in cm (default: 42.5)",
    )
    parser.add_argument(
        "--water-level",
        "--water-level-cm",
        type=float,
        default=None,
        dest="water_level_cm",
        help="Calculated water level in cm (default: computed if --auto-calc, else 157.5)",
    )
    parser.add_argument(
        "--percentage",
        "--water-percentage",
        type=float,
        default=None,
        dest="water_percentage",
        help="Water level percentage 0-100 (default: computed if --auto-calc, else 78.75)",
    )
    parser.add_argument(
        "--litres",
        "--water-litres",
        type=float,
        default=None,
        dest="water_litres",
        help="Water volume in litres (default: computed if --auto-calc, else 787.5)",
    )
    parser.add_argument(
        "--auto-calc",
        action="store_true",
        default=False,
        help="Automatically compute water level, percentage, and litres from distance and tank geometry",
    )
    parser.add_argument(
        "--tank-height",
        type=float,
        default=DEFAULT_TANK_HEIGHT,
        help=f"Tank height in cm for geometry math (default: {DEFAULT_TANK_HEIGHT})",
    )
    parser.add_argument(
        "--sensor-offset",
        type=float,
        default=DEFAULT_SENSOR_OFFSET,
        help=f"Sensor offset in cm from water max line (default: {DEFAULT_SENSOR_OFFSET})",
    )
    parser.add_argument(
        "--tank-capacity",
        type=float,
        default=DEFAULT_CAPACITY_LITRES,
        help=f"Total tank capacity in litres (default: {DEFAULT_CAPACITY_LITRES})",
    )
    parser.add_argument(
        "--continuous",
        "-c",
        action="store_true",
        default=False,
        help="Run continuously sending telemetry at intervals",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=float,
        default=5.0,
        help="Interval in seconds between transmissions during continuous mode (default: 5.0)",
    )
    parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=None,
        help="Number of transmissions to perform (default: 1 in single mode, infinite in continuous mode)",
    )
    parser.add_argument(
        "--variance",
        type=float,
        default=0.0,
        help="Sensor jitter variance percentage (+/- X%%) applied to distance in continuous mode",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print generated payload without sending HTTP POST request",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP request timeout in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        default=False,
        help="Suppress informational stdout output",
    )

    return parser.parse_args(args)


def run_simulation(args: argparse.Namespace) -> int:
    """
    Executes telemetry simulation according to parsed arguments.
    Returns exit code (0 = success, non-zero = failure).
    """
    total_transmissions = args.count if args.count is not None else (1 if not args.continuous else float("inf"))
    transmissions_done = 0
    failures = 0

    distance_base = args.distance_cm
    api_key_to_use = None if args.auth_mode == "none" else args.api_key

    if not args.quiet:
        mode_str = "CONTINUOUS" if args.continuous else "SINGLE"
        print(f"[{mode_str} ESP32 SIMULATION] Target: {args.url} | Device: {args.device_id} | Auth: {args.auth_mode}")

    try:
        while transmissions_done < total_transmissions:
            # Apply jitter if variance requested
            cur_distance = distance_base
            if args.variance > 0.0:
                delta = (random.random() * 2.0 - 1.0) * (args.variance / 100.0) * distance_base
                cur_distance = max(0.0, distance_base + delta)

            # Determine level, percentage, and litres
            if args.auto_calc or args.water_level_cm is None:
                lvl, pct, lit = calculate_tank_metrics(
                    distance_cm=cur_distance,
                    tank_height_cm=args.tank_height,
                    sensor_offset_cm=args.sensor_offset,
                    total_capacity_litres=args.tank_capacity,
                )
            else:
                lvl = args.water_level_cm
                pct = args.water_percentage if args.water_percentage is not None else 78.75
                lit = args.water_litres if args.water_litres is not None else 787.5

            payload = build_payload(
                device_id=args.device_id,
                distance_cm=cur_distance,
                water_level_cm=lvl,
                water_percentage=pct,
                water_litres=lit,
                api_key=api_key_to_use,
                auth_mode=args.auth_mode,
            )

            if args.dry_run:
                print(f"[DRY RUN #{transmissions_done + 1}] Payload: {json.dumps(payload, indent=2)}")
                transmissions_done += 1
                if args.continuous and transmissions_done < total_transmissions:
                    time.sleep(args.interval)
                continue

            status_code, resp_data = send_telemetry(
                url=args.url,
                payload=payload,
                api_key=api_key_to_use,
                auth_mode=args.auth_mode,
                timeout=args.timeout,
            )

            transmissions_done += 1

            if 200 <= status_code < 300:
                if not args.quiet:
                    print(
                        f"[{transmissions_done}] HTTP {status_code} SUCCESS -> "
                        f"dist={cur_distance:.1f}cm, lvl={lvl:.1f}cm, pct={pct:.1f}%, vol={lit:.1f}L | "
                        f"Response: {resp_data}"
                    )
            else:
                failures += 1
                if not args.quiet:
                    print(
                        f"[{transmissions_done}] HTTP {status_code} ERROR -> "
                        f"Payload: {payload} | Response: {resp_data}",
                        file=sys.stderr,
                    )

            if args.continuous and transmissions_done < total_transmissions:
                time.sleep(args.interval)

    except KeyboardInterrupt:
        if not args.quiet:
            print("\nSimulation aborted by user.")

    if not args.quiet and total_transmissions > 1:
        print(f"Simulation summary: {transmissions_done} transmitted, {failures} failures.")

    return 0 if failures == 0 else 1


def main():
    args = parse_arguments()
    sys.exit(run_simulation(args))


if __name__ == "__main__":
    main()
