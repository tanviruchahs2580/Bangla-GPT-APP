# MFA for privileged roles — posture and compensating controls

Status: **documented decision (2026-10-19), not an enforcement change.**
Finding: AUD-B-06 (B register) — "MFA optional for privileged roles with no
compensating-control document".

## What exists (verified)

- TOTP (RFC 6238) MFA is implemented for **every** account role; enrolment is
  `POST /auth/mfa/enroll` → `verify` and login then returns a purpose-bound
  5-minute step-up token that only `POST /auth/mfa/challenge` accepts
  (`apps/api/src/bangla_gpt_api/routers/auth.py`, `auth/mfa.py`). The step-up
  token is single-use (jti burned) and a cache outage fails it closed.
- **Enforcement is optional**: nothing in the login path requires
  `user.totp_secret` for any role. Evidence: the only branch on
  `user.totp_secret` in login is the step-up mint; no role list is consulted
  (`routers/auth.py:354-361`).
- Roles are `student | teacher | parent | admin | school_admin`
  (`schemas.py:479`). Privileged = **admin**, **school_admin**; teacher is
  staff with school-scoped access, not privileged for MFA purposes.

## Compensating controls (in place today)

| Control | Why it bounds the missing enforcement | Where |
|---|---|---|
| Progressive per-account lockout (5 failures → 60 s, doubling to 1 h) + per-IP rule, both with `Retry-After` | Credential stuffing against an admin without a second factor hits a deterministic backoff, and the lock length survives IP rotation | `routers/auth.py:_LOGIN_LOCKOUT_*`, `ratelimit.py` |
| Admin accounts cannot self-register; they are operator-seeded via `ADMIN_EMAIL`/`ADMIN_PASSWORD` boot config | Removes the "register then escalate" path to a privileged account | `initialize/dependencies.py:158-170`; `RegisterRequest.role` Literal excludes admin |
| Short bearer lifetime (60 min) + server-side logout revocation (jti deny-list, strict/fail-closed) | A stolen admin token has a bounded window, unlike the pre-AUD-B-04 localStorage-only logout | `routers/auth.py:logout`, `routers/deps.py:get_current_user` |
| Every privileged mutation writes an audit row; `/admin/audit` is admin-only and unexploitable by students | Detection: an admin action taken under a stolen credential leaves the actor/target trail used in incident response | `db/models.py:AuditLog`, `routers/admin.py` |
| Impersonation guard rails: admin-only start, refuses admin/school_admin targets, 15-min jti-revocable token, refused at `DELETE /users/me`, audited start/stop | The most attractive admin capability cannot be chained into account erasure or privilege escalation | `routers/deps.py:forbid_impersonation`, `routers/users.py` |
| Argon2id storage + common/breached blocklist (AUD-B-06) + single-use hashed reset tokens | Raises the cost of the credential-guessing path that MFA would otherwise cover | `auth/security.py`, `auth/single_use.py` |
| Last-admin protection and role-change guards | A compromised admin cannot lock the operator out of recovery, and role changes are validated (no mass assignment) | `routers/admin.py`, negative suite |

## Decision and owner action

- **Decision (dated 2026-10-19):** MFA stays optional *by design* for this
  release; enforcement without an operational recovery story (lost
  authenticator, support path for a locked-out school principal) would create
  a denial-of-service on the admin console. The compensating controls above
  are the accepted mitigation, and this document is the record the audit
  register asked for.
- **Owner action (before any national-scale rollout):** decide whether to
  enforce MFA at login for `admin` and `school_admin` (a one-place check plus
  an enrolment prompt and a documented recovery procedure), or to keep the
  optional posture. Whichever is chosen, `tests/test_b2_mfa_privileged.py`
  pins the current behaviour so the change is deliberate.

## Verification

`apps/api/tests/test_b2_mfa_privileged.py` proves the flow an operator relies
on: an **admin** account can enrol, and its next login is challenged with a
step-up token that only a valid TOTP code converts into a bearer token.
`tests/test_mfa.py` covers the general lifecycle and RFC 6238 vector.
