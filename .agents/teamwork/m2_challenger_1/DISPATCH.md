## 2026-11-06T15:39:24Z
You are m2_challenger_1, an adversarial Challenger subagent for Milestone M2 (Flask Backend REST API & Authentication).
Your assigned working directory is: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m2_challenger_1\

MANDATORY FIRST STEP:
Read:
1. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md
2. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\PROJECT.md
3. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\TEST_INFRA.md
4. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\TEST_READY.md
5. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m2_worker\handoff.md

YOUR TASK:
Adversarially challenge and stress-test the REST API endpoints:
1. Write adversarial test scripts in your workspace to test:
   - Malformed payloads: invalid JSON strings, empty bodies, non-dict JSON (lists, primitives), missing fields, extra unexpected fields.
   - Hostile input types: strings instead of numbers, booleans disguised as numbers (`true` / `false` rejected from percentage/litres), NaN, Infinity, negative values, values > 100%.
   - Authentication attacks: empty API keys, wrong keys, header vs body key conflicts, disabled device attempts (is_active=0).
   - Burst ingestion simulation: using `scripts/simulate_esp32.py` logic or concurrent requests to test rapid sequential telemetry posts without data loss.
2. Run test verification and record exact results.
3. Formulate your explicit verdict: APPROVE or REQUEST_CHANGES.

OUTPUT REQUIREMENTS:
- Write challenge.md and handoff.md in your working directory.
- Send completion message to caller via send_message with your verdict and findings summary.
