# BRIEFING — 2026-11-06T14:34:00Z

## Mission
Supervise execution of Smart Water Tank Level Monitoring System via teamwork_orchestrator.

## 🔒 My Identity
- Archetype: sentinel
- Working directory: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\
- Orchestrator: e67aac6c-272b-4420-b5de-866caa2cc5fb
- Victory Auditor: to be spawned on victory claim

## 🔒 Key Constraints
- No technical decisions — relay only
- Victory Audit is MANDATORY before reporting completion
- Strictly for monitoring: do not control pumps or motors
- PythonAnywhere compatible: no persistent background daemons, use standalone scheduled task for backups
- SQLite database with water_readings, devices, tank_settings, backup_logs tables
- Protect sensor endpoints with device API key

## User Context
- **Last user request**: Approved task prompt for Smart Water Tank Level Monitoring System
- **Pending clarifications**: None
- **Delivered results**: Execution started

## Project Status
- **Phase**: in progress
- **Route**: General -> teamwork_orchestrator
- **Routing Rationale**: Full-stack IoT system involving hardware firmware, backend API, database, UI/charts, and deployment configurations.
- **Monitoring Tasks**:
  - Cron 1 (Progress Reporting, */8 * * * *): task-20
  - Cron 2 (Liveness Check, */10 * * * *): task-22

## Victory Audit Status
- **Triggered**: no
- **Verdict**: pending
- **Retry count**: 0

## Artifact Index
- .agents/teamwork/ORIGINAL_REQUEST.md — Authoritative record of user intent
