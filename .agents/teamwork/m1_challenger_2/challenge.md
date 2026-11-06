# Empirical Adversarial Challenge Report — Milestone M1

**Agent:** `m1_challenger_2`  
**Milestone:** M1 — Database & Core Storage Subsystem  
**Date:** 2026-11-06  
**Verdict:** **APPROVE**  
**Overall Risk Assessment:** **LOW**

---

## Challenge Summary

As `m1_challenger_2`, empirical adversarial probing was conducted against the SQLite database schema, initialization runner, connection lifecycle, and Data Access Layer (DAL) implemented in Milestone M1 (`app/database.py`, `scripts/init_db.py`, `app/models.py`, `app/config.py`).

Twenty dedicated adversarial tests were authored and executed in `tests/adversarial/test_m1_challenger2_persistence.py`. All 20 tests executed with a **100% pass rate in 0.43 seconds**. In addition, full regression passes across `tests/unit/test_m1_core.py` (25/25 passed), `TestFeature1SqliteSchema` (5/5 passed), and `TestBoundary1DbConstraints` / `TestBoundary14RuntimeEnvironment` (10/10 passed) were empirically confirmed.

The architecture was proven resilient across simulated restarts, repeated re-initializations, extreme date boundaries, foreign key cascading deletions, and SQLite connection isolation modes.

---

## Challenges

### [Low Risk] Challenge 1: Unintentional Data Loss During Application Re-initialization
- **Assumption Challenged**: Deploying updates or restarting containers/processes might invoke database setup routines that inadvertently re-create tables or truncate existing telemetry.
- **Attack Scenario**: Run `scripts/init_db.py` without `--reset` repeatedly (5 sequential times) against an active database with custom registered devices and telemetry records.
- **Blast Radius**: Total loss of historical sensor readings, invalidating Requirement R4 (15-day history retention).
- **Mitigation & Verification**: The DDL uses `CREATE TABLE IF NOT EXISTS` and seed routines utilize `INSERT OR IGNORE`. Test `test_reinit_without_reset_preserves_telemetry` and `test_repeated_reinit_idempotence` confirmed zero telemetry records were deleted, altered, or duplicated.

### [Low Risk] Challenge 2: Date Boundary Edge Cases, Leap Years, and DST Desynchronization
- **Assumption Challenged**: Date formatting discrepancies between ISO-8601 strings (with `T`, `Z`, or timezone offsets), leap years, and extreme epoch timestamps could bypass validation or break SQL string matching in `get_readings_by_date` and `get_daily_stats`.
- **Attack Scenario**: Inject leap day dates (`2024-02-29`, `2028-02-29`, `2000-02-29`), ISO-8601 strings with timezone shifts (`+01:00`, `+02:00`), empty string dates, malformed date patterns (`2026/11/06`), and epoch limits (`1970-01-01`, `2038-01-19`, `9999-12-31`).
- **Blast Radius**: Database corruption or corrupted daily aggregations causing missing or duplicated historical metrics.
- **Mitigation & Verification**: Schema-level CHECK constraint `CHECK (length(date) = 10 AND date LIKE '____-__-__')` strictly rejects malformed dates. Leap years and valid ISO strings normalize properly. `get_daily_stats(days=15)` correctly filters dates older than 15 days, while historical records beyond 15 days remain safely archived and retrievable via `get_readings_by_date`.

### [Low Risk] Challenge 3: Foreign Key Orphaned Records Upon Device Removal
- **Assumption Challenged**: SQLite defaults to `PRAGMA foreign_keys = OFF;` per connection. If foreign keys are not actively enforced on every connection, deleting a device might leave orphaned telemetry records or fail to cascade delete.
- **Attack Scenario**: Insert multi-device telemetry, delete device A, and verify whether device A's readings are deleted while device B's readings remain untouched.
- **Blast Radius**: Database inconsistency, orphaned foreign keys, or unintended cross-device data deletion.
- **Mitigation & Verification**: `app/database.py` enforces `PRAGMA foreign_keys = ON;` on every connection created via `create_connection()`. The table DDL defines `FOREIGN KEY (device_id) REFERENCES devices (device_id) ON DELETE CASCADE`. Test `test_device_deletion_cascades_to_water_readings` confirmed all child readings were cascade-deleted with zero impact on sibling devices.

### [Low Risk] Challenge 4: In-Memory Connection Leakage and Isolation Breakdown
- **Assumption Challenged**: In-memory databases (`:memory:`) might inadvertently share state across connections, or crash when file-dependent PRAGMAs (like WAL mode) are executed.
- **Attack Scenario**: Open two distinct `:memory:` connections and verify strict isolation. In parallel, verify that separate disk connections properly share committed data and support concurrent reads during uncommitted writes via WAL snapshot isolation.
- **Blast Radius**: Cross-test state leakage, false test results, or lock contention crashes.
- **Mitigation & Verification**: `scripts/init_db.py` and `app/database.py` detect `:memory:` paths and avoid configuring file-based WAL modes. Separate `:memory:` connections remain completely isolated, while disk connections successfully utilize WAL snapshot isolation.

---

## Stress Test Results

| Test ID | Scenario | Expected Behavior | Actual Behavior | Result |
|---------|----------|-------------------|-----------------|:------:|
| 1.1 | Telemetry persistence across `init_db` without `--reset` | Custom device & telemetry preserved intact | Both device & readings preserved with 0 loss | **PASS** |
| 1.2 | Repeated sequential `init_db` execution (5x) | Idempotent execution, no duplicate records | Execution succeeded with 0 data duplication | **PASS** |
| 1.3 | Simulated server restart with WAL mode | Data committed before restart readable after | All 10 readings verified post-restart | **PASS** |
| 1.4 | Schema reset via `init_db --reset` | Drops and recreates schema cleanly | Tables reset without Windows lock error | **PASS** |
| 2.1 | Leap year February 29 (`2024-02-29`, `2028-02-29`) | Valid date accepted and queryable | Readings inserted and retrieved cleanly | **PASS** |
| 2.2 | ISO-8601 timestamps with 'T', 'Z', and offsets | Timestamp and date parsed properly | Accepted without schema errors | **PASS** |
| 2.3 | Empty / None date and timestamp | Fallback to current timestamp / date | Defaults applied properly | **PASS** |
| 2.4 | Malformed date formats (`2026/11/06`, etc.) | Rejected by CHECK constraint | `sqlite3.IntegrityError` raised | **PASS** |
| 2.5 | 15-day history cutoff filtering | Excludes >15-day-old records from stats | Strictly filters cutoff, records queryable | **PASS** |
| 2.6 | Epoch edge cases (`1970`, `2038`, `9999`) | Accepted and stored accurately | Stored and retrieved accurately | **PASS** |
| 3.1 | Device deletion with cascade delete | Child telemetry cascade-deleted | Deleted device readings 0, sibling preserved | **PASS** |
| 3.2 | Foreign key enforcement on all connections | Rejects insert with non-existent device | `sqlite3.IntegrityError` raised | **PASS** |
| 3.3 | Device deactivation (`is_active = 0`) | Telemetry retained for audit | Child telemetry preserved intact | **PASS** |
| 4.1 | In-memory `:memory:` connection isolation | Connection B cannot see Connection A | Zero state sharing between instances | **PASS** |
| 4.2 | Disk database connection sharing | Connection B immediately sees Connection A | Committed data immediately visible | **PASS** |
| 4.3 | WAL snapshot isolation concurrent read/write | Reader sees committed state without blocking | Reader observed 1 row, non-blocking | **PASS** |
| 5.1 | Singleton tank settings (`id != 1`) | Rejects insert with id=2 | `sqlite3.IntegrityError` raised | **PASS** |
| 5.2 | Negative tank settings values | Rejected by validation layer | `ValueError` raised | **PASS** |
| 5.3 | Physical telemetry bounds (pct > 100, dist < 0) | Rejected by model validation layer | `ValueError` raised | **PASS** |
| 5.4 | SQL injection attacks on DAL methods | Escaped safely via parameterization | All injection attempts neutralized | **PASS** |

**Summary**: 20/20 Passed (100% Pass Rate).

---

## Unchallenged Areas

- **Live HTTP Ingestion Endpoint (`POST /api/water-level`)**: Out of scope for M1 (scheduled for Milestone M2).
- **Physical ESP32 Sensor Hardware Microcontroller Clock Drift**: Out of scope for database subsystem (scheduled for Milestone M5).
- **Automated Scheduled Backup Cron Runner Execution**: Out of scope for M1 (scheduled for Milestone M3).

---

## Conclusion & Verdict

**VERDICT: APPROVE**

Milestone M1 satisfies all requirements for data persistence, schema resilience, date/timestamp handling, referential integrity cascades, and connection isolation. No blockers or vulnerabilities were found.
