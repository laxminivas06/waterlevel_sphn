# E2E Test Infra: Smart Water Tank Level Monitoring System

## Test Philosophy
- Opaque-box, requirement-driven. Derived from `ORIGINAL_REQUEST.md` and `PROJECT.md`, independent of internal implementation code.
- Methodology: Category-Partition + Boundary Value Analysis + Pairwise Interactions + Real-World Workloads.
- Progressive testability: Tests run against public APIs and standalone scripts.

## Feature Inventory & Test Coverage Mapping
| # | Feature | Requirement | Tier 1 (Feature) | Tier 2 (Boundary) | Tier 3 (Cross-Feature) | Tier 4 (Workloads) |
|---|---------|-------------|:----------------:|:-----------------:|:----------------------:|:------------------:|
| 1 | SQLite Schema & Tables | R2 | 5 tests | 5 tests | ✓ | ✓ |
| 2 | Telemetry Ingestion `POST /api/water-level` | R2 | 5 tests | 5 tests | ✓ | ✓ |
| 3 | API Key Authentication & Rejection | R2 | 5 tests | 5 tests | ✓ | ✓ |
| 4 | Physics Range Validation | R2 | 5 tests | 5 tests | ✓ | ✓ |
| 5 | Device Online/Offline Tracking | R2 | 5 tests | 5 tests | ✓ | ✓ |
| 6 | Real-Time Status `GET /api/water-level/current` | R3 | 5 tests | 5 tests | ✓ | ✓ |
| 7 | 15-Day Historical Daily Stats `GET /api/history/daily-stats` | R4 | 5 tests | 5 tests | ✓ | ✓ |
| 8 | Intraday Date Readings `GET /api/history/readings` | R4 | 5 tests | 5 tests | ✓ | ✓ |
| 9 | Day-to-Day Comparison `GET /api/history/compare` | R4 | 5 tests | 5 tests | ✓ | ✓ |
| 10 | Tank Settings Read/Update `GET/PUT /api/settings` | R2 | 5 tests | 5 tests | ✓ | ✓ |
| 11 | Standalone Daily Backup CLI `scripts/backup.py` | R5 | 5 tests | 5 tests | ✓ | ✓ |
| 12 | Backup REST API (trigger, list, download) | R5 | 5 tests | 5 tests | ✓ | ✓ |
| 13 | Path Traversal Protection on Backup Download | R5 | 5 tests | 5 tests | ✓ | ✓ |
| 14 | PythonAnywhere WSGI Compatibility | R6 | 5 tests | 5 tests | ✓ | ✓ |

## Test Architecture
- **Test Runner**: `python -m pytest tests/e2e/ -v` or `python tests/e2e/test_runner.py`
- **Simulated Client**: `scripts/simulate_esp32.py`
- **Directory Layout**:
  - `tests/e2e/test_tier1_features.py`: Feature coverage (isolated happy paths)
  - `tests/e2e/test_tier2_boundaries.py`: Boundary and corner cases (extremes, invalid inputs, edge conditions)
  - `tests/e2e/test_tier3_interactions.py`: Cross-feature combinations and pairwise state interactions
  - `tests/e2e/test_tier4_workloads.py`: Real-world end-to-end multi-day lifecycle simulations

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Target Behavior |
|---|----------|--------------------|-----------------|
| 1 | 15-Day Inflow/Outflow Simulation | Ingestion, Daily Stats, Aggregation, Comparison | Accurate min/max/avg calculation across all 15 dates |
| 2 | Sensor Disconnection & Recovery | Ingestion, Device Tracking, Current Status | Device switches to offline after threshold, recovers to online upon new ping |
| 3 | Automated Daily Backup & Restore Cycle | Backup CLI, CSV/JSON Export, Database Recovery | Backups persist, log accurately, and contain complete historical records |
| 4 | Rapid Burst Telemetry & Concurrency | Ingestion, Database Locks, Indexes | Handles rapid succession without DB lock failure or data corruption |
| 5 | Tank Geometry & Calibration Shift | Settings API, Ingestion, Level/Litres Calculation | Updated settings immediately reflect in subsequent percentage and volume math |

## Coverage Thresholds
- Tier 1: >= 70 tests (>=5 per feature)
- Tier 2: >= 70 tests (>=5 per feature/boundary)
- Tier 3: >= 15 tests (major cross-feature pairs)
- Tier 4: >= 5 tests (end-to-end application scenarios)
- Expected Total: >= 160 test cases

