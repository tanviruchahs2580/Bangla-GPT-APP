# T-12 summary — password hashing (verification task: F-04 REFUTED)

Executed 2026-11-19 (branch `remediation/0.2.0`). The T-01 verification found Argon2id already at the OWASP floor with the legacy-upgrade path — so this task verified the implementation end-to-end rather than performing BC-1 work.

## Card-step outcomes
1. **Implementation + call sites** (H-1, `@f206ee2`): `auth/security.py:50-57` — `ARGON2_TIME_COST=2, ARGON2_MEMORY_COST_KIB=19*1024, ARGON2_PARALLELISM=1`; `hash_password` :201, `verify_password` :206 (Argon2id or legacy `pbkdf2_sha256`), `needs_rehash` rehash path :222-229. Call sites: register auth.py:223; login verify :457 + rehash-after-success :551-552; change-password :888/:905; reset :950/:859; MFA disable :986; CSV classroom import teacher.py:338. All in synchronous handlers.
2. **Dependency**: `argon2-cffi>=23.1` (pyproject:78); installed 25.1.0 (MIT, maintained).
3. **Parameters + measured cost**: parameters EQUAL the OWASP floor (m=19 MiB, t=2, p=1); measured on this machine (`EV-T12-t12-hash-time-5runs`): **median 57.1 ms/hash, spread 54.0–62.1 ms (5 runs)**, verify asserted in-loop. Login rate limit exists (config.py:422-431: `/auth/login` per-IP budget; MFA legs separately capped).
4. **Legacy handling**: `tests/test_password_hashing.py` — legacy pbkdf2 verifies (:58), rehash flagged (:69), login upgrades in place (:93), current hash untouched (:114).
5. **Constant-time**: legacy comparison via `hmac.compare_digest` (security.py:239); Argon2 verification is library-side.
6. **Unknown-user path**: decoy hash spent on no-such-user logins (security.py:59-63,176-180); pinned by `test_round2_auth_hardening.py:127-136` (decoy IS called) and `test_w2_authz_policy.py:183` (timing equalisation does real work).
7. **NEW (BC-8)**: production boot guard `_validate_password_hash_parameters` (main.py) — refuses Argon2id constants below the OWASP floor; 3 tests in `tests/test_production_guards.py` (accepted-at-floor, memory below floor refused naming `m=8192`, time-cost below 2 refused). All guards green: 69 tests across production_guards + password_hashing + round2_auth_hardening; `mypy src` 141 files clean; ruff clean.

## Acceptance
Existing auth tests unchanged and passing; the new tests pass; hash time measured and stored; hashes never logged (log-redaction suites pass: test_w2_log_redaction, test_qa_sentry_scrub in the standard suite).
