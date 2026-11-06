# Adversarial Challenge Report — Milestone M1: Database & Core Storage Subsystem

**Agent:** `m1_challenger_1` (Empirical Challenger: Critic & Domain Specialist)  
**Date:** 2026-11-06  
**Milestone:** M1 — Database & Core Storage Subsystem  
**Overall Risk Assessment:** **LOW**  
**Final Verdict:** **APPROVE**  

---

## 1. Challenge Summary

Milestone M1 delivers the core SQLite storage engine, connection lifecycle manager, schema initializers, and Data Access Layer (DAL) for the Smart Water Tank Level Monitoring System. As an empirical challenger, my objective was not merely to confirm baseline feature compliance, but to actively attack the subsystem under hostile conditions:
1. Multi-threaded concurrency hammer attacks under SQLite Write-Ahead Logging (WAL) mode.
2. Boundary violation attacks (negative water volume, out-of-range percentages, negative heights/offsets, missing foreign keys, non-singleton configuration rows, malformed date patterns, invalid enum statuses).
3. Comprehensive SQL injection payloads targeting every DAL query entry point.
4. Active lock contention simulations (exclusive write locks holding transactions while concurrent readers query snapshots), busy timeout verification, and crash/rollback integrity preservation.
5. Large blob payload stress and Unicode/emoji encoding resiliency.

**Empirical Result:** 24 dedicated adversarial stress tests in `tests/adversarial/test_m1_adversarial.py` passed with 100% success rate (`24 passed in 5.47s`). Combined with existing unit and persistence tests, **69 out of 69 storage tests pass cleanly**. The storage layer demonstrates outstanding robustness, ACID compliance, and concurrency resilience.

---

## 2. Adversarial Test Matrix & Empirical Execution Log

| # | Challenge Category | Test Function | Workload / Attack Vector | Observed Behavior | Status |
|---|--------------------|---------------|--------------------------|-------------------|:------:|
| 1 | WAL Concurrency Stress | `test_concurrent_writers_and_readers` | 10 writers x 50 inserts (500 writes) + 5 continuous reader threads (60 iters each) | 0 lock errors, all 500 records committed, integrity 'ok' | **PASS** |
| 2 | Concurrent Registration & Config | `test_concurrent_device_registration_and_settings_updates` | ThreadPoolExecutor (8 workers): 20 concurrent device registrations + 20 concurrent settings updates | Zero race conditions, 21 total devices, accurate settings | **PASS** |
| 3 | Physical Constraint Attacks | `test_attack_negative_litres` | Payloads: -0.0001, -1.0, -999.0, -1e6 Litres | Raised `ValueError` in DAL & `sqlite3.IntegrityError` in raw SQL | **PASS** |
| 4 | Boundary Constraint Attacks | `test_attack_out_of_bounds_percentage` | Payloads: -0.01, -100.0, 100.0001, 105.0, 999.0% | Rejected at both Python validation layer and SQLite CHECK | **PASS** |
| 5 | Physical Constraint Attacks | `test_attack_negative_distance_and_level` | Distance -5.0cm, Water level -1.0cm | Rejected with `ValueError` and SQLite constraint rejection | **PASS** |
| 6 | Referential Integrity Attacks | `test_attack_missing_foreign_key` | Unregistered device IDs (`ghost_sensor_999`, `non_existent`) | `sqlite3.IntegrityError: FOREIGN KEY constraint failed` | **PASS** |
| 7 | Singleton Table Attacks | `test_attack_non_singleton_tank_settings` | Attempts to insert tank_settings rows with id=0, 2, 3, -1, 999 | `sqlite3.IntegrityError: CHECK constraint failed: (id = 1)` | **PASS** |
| 8 | Settings Boundary Attacks | `test_attack_tank_settings_physical_boundaries` | Zero/negative capacity, negative height, warning_low > 100%, timeout < 10s | All 10 invalid configurations rejected by DAL/DDL | **PASS** |
| 9 | Temporal Pattern Attacks | `test_attack_malformed_reading_dates` | Non-ISO dates (`2026-1-1`, `26-11-06`, `not-a-date`, `2026/11/06`) | Rejected by CHECK constraint `length(date)=10 AND date LIKE '____-__-__'` | **PASS** |
| 10| Device Integrity Attacks | `test_attack_invalid_devices_constraints` | Empty `device_id`, whitespace name, empty `api_key`, `is_active=5` | All rejected by DDL CHECK constraints | **PASS** |
| 11| Backup Audit Attacks | `test_attack_invalid_backup_logs_constraints` | Empty filename, empty path, invalid format `xml`, negative bytes, negative count | All rejected by DDL CHECK constraints | **PASS** |
| 12| SQL Injection — Device Auth | `test_sql_injection_device_queries` | Payloads: `' OR '1'='1`, `'; DROP TABLE devices; --`, `' UNION SELECT ...` | Treated as literal text; returns `None`/`False`; zero data leaks | **PASS** |
| 13| SQL Injection — Device Writes | `test_sql_injection_device_updates` | Payloads in `update_last_seen` and `register_device` | Parameterized execution; `devices` & `tank_settings` untouched | **PASS** |
| 14| SQL Injection — Telemetry Reads | `test_sql_injection_telemetry_reads` | Payloads injected into `get_latest_reading`, `get_readings_by_date` | Returned `None`/`[]`; table not dropped; parameterized | **PASS** |
| 15| SQL Injection — Analytics Aggs | `test_sql_injection_analytics_queries` | Injections in `get_daily_stats`, `compare_dates`, `get_today_summary` | Sanitized; returned safe empty stats or zero counts | **PASS** |
| 16| SQL Injection — Backup Logs | `test_sql_injection_backup_queries` | Injections in `get_backup_by_filename` | Returned `None`; parameters safely isolated | **PASS** |
| 17| WAL Concurrency Guarantee | `test_wal_readers_not_blocked_by_active_write_transaction` | Uncommitted write holds lock; concurrent reader queries DB | Reader completes immediately (<0.5s) without blocking | **PASS** |
| 18| Lock Contention & Busy Timeout | `test_busy_timeout_writer_contention_and_resolution` | Writer A holds lock for 300ms; Writer B enters transaction concurrently | Writer B waits cleanly on busy_timeout and commits | **PASS** |
| 19| Crash & Rollback Simulation | `test_transaction_rollback_on_failure_preserves_consistency` | Exception raised mid-transaction after partial write | Uncommitted writes rolled back completely; integrity 'ok' | **PASS** |
| 20| Special Character & Unicode | `test_unicode_and_emojis_in_device_and_readings` | Device names with emojis (🌊💧), German umlauts (ökologisch), Spanish/Chinese | Stored and retrieved verbatim without corruption | **PASS** |
| 21| Stored XSS Script Payload | `test_xss_and_html_injection_stored_literally` | `<script>alert('pwned')</script><img src=x onerror=alert(1)>` in device name | Stored literally as safe text; no execution | **PASS** |
| 22| High Volume Blob Storage | `test_large_raw_json_blob_storage` | 20,000-sample JSON array (>150KB) in `raw_reading_json` | Stored and retrieved completely intact | **PASS** |
| 23| Heavy Burst & WAL Checkpoint | `test_high_thread_burst_and_checkpoint` | 20 threads x 25 writes (500 writes) + `PRAGMA wal_checkpoint(TRUNCATE)` | 500 rows verified; checkpoint code 0 (success); integrity 'ok' | **PASS** |
| 24| Empty Database Resilience | `test_empty_readings_table_queries` | All DAL methods executed on completely empty database | Clean zero defaults returned; zero unhandled exceptions | **PASS** |

---

## 3. Deep-Dive Challenge Findings

### Challenge Area 1: Multi-Threaded WAL Concurrency & Lock Contention
- **Hypothesis**: In SQLite on Windows, concurrent writes or active transactions will encounter `OperationalError: database is locked` or crash when readers and writers access the file concurrently.
- **Empirical Findings**:
  - In `TestWalConcurrencyStress.test_concurrent_writers_and_readers`, 10 writer threads each inserted 50 rows (500 rows total) while 5 reader threads continuously executed read queries. All 500 records were stored with zero lost updates and zero lock errors.
  - In `TestLockContentionAndCrashRecovery.test_wal_readers_not_blocked_by_active_write_transaction`, a writer acquired `BEGIN IMMEDIATE` and held an uncommitted write. A reader thread querying the database in parallel completed in under 0.01 seconds without waiting, successfully demonstrating SQLite WAL reader-writer isolation.
  - In `TestLockContentionAndCrashRecovery.test_busy_timeout_writer_contention_and_resolution`, two concurrent writers competed for write locks; Writer B queued on the 30,000ms busy timeout and executed immediately upon Writer A's commit.
  - Post-stress verification using `PRAGMA integrity_check;` returned `ok`.

### Challenge Area 2: Domain Constraints & Malicious Input Rejection
- **Hypothesis**: Direct SQL execution or DAL model calls can bypass physical domain constraints (negative litres, out-of-range percentages, negative heights, malformed dates).
- **Empirical Findings**:
  - The implementation enforces a **dual-layer defense**: DAL Python validations reject impossible inputs before reaching SQLite, and database-level `CHECK` constraints reject any direct SQL bypass attempts.
  - Negative litres (`-0.0001` through `-1e6`) are rejected by both Python `ValueError` and SQLite `CHECK (water_litres >= 0.0)`.
  - Out-of-bounds percentages (`-0.01%`, `100.0001%`, `105%`, `999%`) are strictly rejected.
  - Foreign key referential integrity (`PRAGMA foreign_keys = ON;`) reliably rejects orphaned readings.
  - Singleton constraint (`CHECK (id = 1)`) prevents creation of secondary or unauthorized tank configuration profiles.
  - Reading date strings are strictly constrained to valid 10-character `YYYY-MM-DD` formatting.

### Challenge Area 3: SQL Injection Hardening Across DAL Models
- **Hypothesis**: Dynamic query formatting or string concatenation in DAL functions enables SQL injection, data exfiltration, or table dropping.
- **Empirical Findings**:
  - Tested 9 distinct SQL injection attack strings (including tautologies, stacked `DROP TABLE` queries, `UNION SELECT` extraction, and comment truncation) across all functions in `app/models.py`.
  - Every single query uses parameterized `?` placeholders.
  - No tables were dropped, no data leaked, and all injection strings were safely treated as inert literal text.

### Challenge Area 4: High-Volume Payload, Unicode, & Empty-State Resilience
- **Hypothesis**: Complex Unicode, multi-byte emojis, or oversized JSON payloads will cause encoding errors, truncation, or memory corruption.
- **Empirical Findings**:
  - Device names with multi-lingual characters and emojis (`🌊`, `💧`, `Español`, `中文`, `ökologisch`) serialize and deserialize cleanly.
  - Raw JSON telemetry blobs exceeding 150KB store and retrieve with exact byte-for-byte fidelity.
  - On completely empty databases (zero telemetry records), all analytics functions (`get_daily_stats`, `compare_dates`, `get_today_summary`, `get_latest_reading`) return safe default dictionaries/lists rather than raising `TypeError`, `IndexError`, or `ZeroDivisionError`.

---

## 4. Unchallenged Areas

- **HTTP REST Endpoint Ingestion & Authentication**: Milestone M2 implements the Flask REST routes (`POST /api/water-level`, `GET /api/water-level/current`, etc.) and API key authentication headers/body parsing. The storage layer's authentication DAL helper (`authenticate_device`) was verified, but live HTTP endpoints will be tested in M2.
- **Firmware Physical Timing**: ESP32 sensor ultrasonic echo microsecond timing and digital filtering belong to Milestone M5.

---

## 5. Explicit Verdict & Recommendation

### **Verdict: APPROVE**

**Justification:**
1. Milestone M1 meets and exceeds all requirements defined in `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `TEST_INFRA.md`.
2. All 24 adversarial challenge tests passed cleanly under empirical verification.
3. High-concurrency multi-threaded stress under WAL mode completed with zero lock errors, zero data corruption, and 100% snapshot consistency.
4. Defense-in-depth domain validation and 100% parameterized SQL queries provide ironclad protection against constraint violations and injection vectors.
5. The core storage subsystem is production-ready for Milestone M2 integration.
