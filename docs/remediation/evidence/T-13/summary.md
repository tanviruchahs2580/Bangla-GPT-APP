# T-13 summary — session/token revocation and MFA enforcement

Executed 2026-11-19/20 (commits through `b6e80f8`, branch `remediation/0.2.0`).

## Card-step outcomes
1. **ADR-0011** (`docs/adr/ADRs.md`) documents from code: HS256, 60-min expiry (`jwt_expire_minutes: int = 60`, config.py:250), issuer/audience binding, `jti` deny-list (logout: per-token `revoke:` under shared cache; impersonation: separate `imp_revoke:` namespace; fail-CLOSED on store outage — deps.py:235-259), per-account epoch (`sessions_invalidated_at` vs token `iat`, second-precision; no-refresh-token single-token design), storage locations (web/Capacitor JS-accessible storage) with options + recommendation.
2. **Characterization tests** (`tests/test_role_change_revocation.py`, red-first): pre-change token after role change reproduced N-01 (200 on the unmodified tree) → after fix, 401 `session_expired` (the established epoch code); fresh login works; DB role check denies old-role routes; per-account isolation (unrelated user's token survives — past-mint technique, no sleeps).
3. **N-01 fix**: `admin_update_role` stamps `sessions_invalidated_at` in the same transaction as the `role_change` audit event (admin.py). Account deletion needs no stamp (erased row fails closed).
4. **Additive claim**: epoch/`iat` mechanism already validates legacy tokens (tokens without `iat` fail closed; pre-deployment tokens valid until natural expiry — BC-2 preserved).
5. **[needs F-06] MFA enforcement**: `MFA_REQUIRED_ROLES` setting (empty default = current behaviour; Q-18), `deps._mfa_enrollment_allowed` restricted waiver (enroll/verify/logout + session-less basics), enforced in `get_current_user` after the epoch check. 5 tests (`tests/test_mfa_enforcement.py`) incl. default-off proof, restricted-surface proof, enroll→verify→challenge round trip, non-required-role untouched, whitespace parsing. **Flipping the default = STOP S-3 (recorded below).**
6. **Token storage**: unchanged (S-3); options + recommendation in ADR-0011 §Decision.3.

## Gates
ruff check + format clean; `mypy src` 141 files clean; 38 tests green across revocation/MFA/tenancy/authz-policy/impersonation suites.

## STOP S-3 records (owner decisions, not applied)
- S-3a: set `MFA_REQUIRED_ROLES=admin,school_admin` in production (user-visible default change).
- S-3b: implement httpOnly-cookie sessions (web) and/or platform secure storage (Android).
