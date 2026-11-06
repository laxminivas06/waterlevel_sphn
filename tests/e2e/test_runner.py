#!/usr/bin/env python3
"""
Standalone E2E Test Suite Runner for Smart Water Tank Level Monitoring System.

Discovers and runs the 4-tier opaque-box test suite:
  - Tier 1: Feature Coverage (70 tests)
  - Tier 2: Boundary & Corner Cases (70 tests)
  - Tier 3: Pairwise Cross-Feature Interactions (16 tests)
  - Tier 4: Real-World Workload Scenarios (5 tests)

Supports running against either an in-process Flask app or an external live HTTP server.
"""

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional
import pytest

TEST_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))

TIER_FILES = {
    1: ("Tier 1 - Feature Coverage", os.path.join(TEST_DIR, "test_tier1_features.py")),
    2: ("Tier 2 - Boundary & Corner Cases", os.path.join(TEST_DIR, "test_tier2_boundaries.py")),
    3: ("Tier 3 - Cross-Feature Interactions", os.path.join(TEST_DIR, "test_tier3_interactions.py")),
    4: ("Tier 4 - Real-World Application Workloads", os.path.join(TEST_DIR, "test_tier4_workloads.py")),
}


class TierResultCollector:
    """Pytest plugin to count test results by category."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = 0
        self.skipped = 0
        self.total = 0

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            self.total += 1
            if report.passed:
                self.passed += 1
            elif report.failed:
                self.failed += 1
            elif report.skipped:
                self.skipped += 1
        elif report.when == "setup" and report.failed:
            # Fixture / setup failure (e.g. app not yet implemented)
            self.total += 1
            self.errors += 1


def run_tier(tier_num: int, tier_name: str, tier_file: str, verbose: bool = False) -> Dict[str, Any]:
    """Runs a single tier using pytest and returns execution metrics."""
    collector = TierResultCollector()
    args = [tier_file]
    if verbose:
        args.append("-v")
    else:
        args.append("-q")

    start_time = time.time()
    exit_code = pytest.main(args, plugins=[collector])
    elapsed = time.time() - start_time

    return {
        "tier": tier_num,
        "name": tier_name,
        "file": tier_file,
        "exit_code": exit_code,
        "passed": collector.passed,
        "failed": collector.failed,
        "errors": collector.errors,
        "skipped": collector.skipped,
        "total": collector.total,
        "elapsed_sec": elapsed,
    }


def print_summary_table(results: List[Dict[str, Any]]):
    """Prints a structured ASCII report table."""
    print("\n" + "=" * 80)
    print("           SMART WATER TANK LEVEL MONITORING SYSTEM — E2E TEST REPORT")
    print("=" * 80)
    print(f"{'Tier':<8} | {'Tier Name':<38} | {'Total':<6} | {'Pass':<6} | {'Fail/Err':<9} | {'Time (s)':<8}")
    print("-" * 80)

    grand_total = 0
    grand_passed = 0
    grand_failed_err = 0
    grand_time = 0.0

    for r in results:
        fail_err = r["failed"] + r["errors"]
        grand_total += r["total"]
        grand_passed += r["passed"]
        grand_failed_err += fail_err
        grand_time += r["elapsed_sec"]

        status_marker = "✓" if fail_err == 0 and r["total"] > 0 else "!"
        tier_label = f"Tier {r['tier']} {status_marker}"
        print(f"{tier_label:<8} | {r['name']:<38} | {r['total']:<6} | {r['passed']:<6} | {fail_err:<9} | {r['elapsed_sec']:<8.2f}")

    print("-" * 80)
    print(f"{'TOTAL':<8} | {'All 4 Tiers Combined':<38} | {grand_total:<6} | {grand_passed:<6} | {grand_failed_err:<9} | {grand_time:<8.2f}")
    print("=" * 80)

    if grand_failed_err > 0:
        print("\nNote: Failures or fixture setup errors for unimplemented endpoints are normal")
        print("prior to completion of backend milestones M1-M5. Tests will progressively pass")
        print("as each implementation milestone is merged.")
    else:
        print("\nAll executed test cases passed successfully.")
    print("=" * 80 + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="Water Leveler E2E Test Suite Runner")
    parser.add_argument(
        "--tier",
        "-t",
        choices=["1", "2", "3", "4", "all"],
        default="all",
        help="Specific test tier to run (1, 2, 3, 4, or all; default: all)",
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help="Base URL of live running backend server (sets TEST_SERVER_URL)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable verbose pytest output",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.server_url:
        os.environ["TEST_SERVER_URL"] = args.server_url
        print(f"[TEST RUNNER] Running against live server at {args.server_url}")
    else:
        print("[TEST RUNNER] Running in-process / against local test harnesses")

    tiers_to_run = [1, 2, 3, 4] if args.tier == "all" else [int(args.tier)]
    results = []

    for tier_num in tiers_to_run:
        name, file_path = TIER_FILES[tier_num]
        print(f"\n[RUNNING] Tier {tier_num}: {name}...")
        res = run_tier(tier_num, name, file_path, verbose=args.verbose)
        results.append(res)

    print_summary_table(results)

    # Return 0 if all tests passed, 1 if any failed
    has_failures = any(r["failed"] > 0 or r["errors"] > 0 for r in results)
    sys.exit(1 if has_failures else 0)


if __name__ == "__main__":
    main()
