# Security Policy

Bangla GPT APP holds personal data about **children**: student names, class
levels, guardian phone numbers, quiz answers and full tutor conversation
history. A disclosure here is a disclosure about a child, so treat every
report accordingly and do not paste real student data into an issue.

## Reporting a vulnerability

**Do not open a public issue describing the vulnerability.** Public issues
are visible to everyone, including people who would use the knowledge.

Two private channels:

- **Email `tanvir.uchahs2580@gmail.com`** (the maintainer's address as
  published in this repository's commit history). This works today.
- GitHub private reporting: Repository → **Security** → **Advisories** →
  **Report a vulnerability** (preferred where available: it gives you a
  private thread and a tracking id). Private vulnerability reporting is
  currently **disabled** on this repository, so this form only appears after
  the maintainer enables it (Settings → Code security and analysis).
  If the form is absent, use the email above instead.

If neither channel is usable, open a minimal public issue that asks the
maintainer for a private channel **without disclosing any vulnerability
details**, and you will be contacted privately.

Please include:

- what an attacker can do, in one sentence;
- the request or code path that does it, with `file:line` if you have it;
- how you verified it;
- whether any real student data is involved (**say so plainly if it is**).

## What to expect

| Stage | Target |
|---|---|
| Acknowledgement | 3 working days |
| Triage (is it real, how bad) | 10 working days |
| Fix or accepted-risk decision | 30 working days |

We will tell you when a report is a duplicate, and we credit reporters in
the release notes unless you ask us not to.

## Scope

In scope: authentication, authorization and tenancy, the tutor and its
retrieval pipeline, children's data access, export and erasure, the deploy
pipeline, secrets handling, and the dependency surface.

Out of scope: findings that require an already-compromised host or an
already-valid admin session, automated scanner output with no working
reproduction, and denial of service against a development machine you own.

## Reporting a data incident

If you find that real children's data has been exposed, say **"data
incident"** in the subject line so it is triaged as urgent rather than
alongside everything else.

## What we already do

So you can judge whether something you found is a gap or a known limit:

- Argon2id password hashing at the OWASP minimum (19 MiB, t=2, p=1) with
  transparent upgrade of legacy hashes on login.
- JWTs pinned to HS256 with `iss`/`aud` required, per-token `jti` on every
  token, a deny-list for privileged sessions, and a token epoch that
  invalidates every token issued before a password change.
- Multi-tenancy anchored on `User.school_id` with a deny-by-default
  authorization matrix asserted in `tests/test_openapi_auth_matrix.py`.
- k-anonymity on aggregate reporting, with the threshold floored in the
  service rather than accepted from the caller.
- Self-service export **and** self-service erasure, both cascade-complete.
- `ruff`, `mypy`, `pytest`, `pip-audit`, `npm audit`, Trivy and gitleaks in
  CI on every pull request.

Known gaps are tracked in `docs/LAUNCH_READINESS_CHECKLIST.md`; if you find
one that is not listed there, that is useful to us.

## Accepted risks and dated design decisions

Reviewed on 2026-10-18. Each entry names what we know, the control that
bounds it, and what would make us revisit it. A "not fixed" here is a
decision, not an oversight.

### Bearer tokens live in `localStorage`, and logout now revokes server-side

The SPA keeps its access token in `localStorage` (`apps/web/src/api.ts`); it
is not an HttpOnly cookie, so an XSS that earned script execution could read
it. Compensating controls: the SPA ships no HTML sink
(`dangerouslySetInnerHTML`/`innerHTML` are absent and pinned by tests), only
`react-markdown` without `rehype-raw` renders model output, and the API CSP
is `script-src 'self'` with a per-response nonce. `POST /auth/logout` now
writes the caller token's `jti` into the shared deny-list that every request
checks, so logout retires the token instead of leaving it live for the rest
of its 60-minute TTL. No refresh token exists; the TTL is the exposure
window. Revisit if the SPA moves to cookie auth or the TTL needs shortening.

### Registration answers 409 `email_taken` for an address that exists

`POST /auth/register` (`apps/api/src/bangla_gpt_api/routers/auth.py`)
discloses account existence, while login and password reset do not. Making
it neutral means an email-verified registration flow (no session until the
address is confirmed) plus SPA changes, which is a product change, not a
patch. The register endpoint is capped at 10/minute per IP and the login
side of enumeration is closed (decoy hash, no status oracle). Revisit with
the mailer/registration rework; until then this is a documented, rate-bounded
oracle.

### Passwords are blocklist-checked, not breach-corpus-checked

Registration, reset and change refuse common passwords with leet folding and
structure rules (`apps/api/src/bangla_gpt_api/auth/security.py`), but there
is no offline breach-corpus check (for example a k-anonymity HIBP lookup).
Compensating controls: Argon2id at the OWASP parameters, a 5-failure account
lockout with exponential backoff, and per-IP login limits. MFA (TOTP) exists
and is optional for privileged roles; a written compensating-control
statement for admin/school_admin is still an owner action. Revisit by adding
the breach check behind a config flag (it needs an outbound call and a
provider-terms review).

### Error responses use the coded `{"detail": ...}` envelope, not RFC 9457

The contract lives in
`apps/api/src/bangla_gpt_api/routers/_error_contract.py` and every coded
error is asserted in tests. Adopting `application/problem+json` would be a
breaking change for every existing client for no security benefit, so the
deviation is accepted. 500 responses carry a fixed code, never the exception
text, and always include `X-Request-ID`.

### The audit log is append-only by convention, not yet tamper-evident

`audit_log` has one writer
(`apps/api/src/bangla_gpt_api/auth/security.py:write_audit`), is served
read-only through `/admin/audit` (admin-only) and is never deleted; account
erasure deliberately anonymises exactly one row so the erasure event
survives the account. There is no hash chain and no database-level
UPDATE/DELETE restriction yet -- that needs a migration plus a change to the
erasure path, and is tracked as a gap in this round. Planned: a
`prev_hash`/`row_hash` pair written by `write_audit` plus a verification
script run in the weekly drill.

### Four GET handlers write rows (analytics/audit), by design

`GET /parents/me/children/{student_id}/report`, `GET /school/analytics`,
`GET /users/me/export` and `GET /admin/reports/aggregate` commit
analytics/audit rows. None mutates user-owned data; the observable effect of
a prefetch or crawler is a counter/audit entry. They remain GETs because the
SPA treats them as reads and changing the verb would break clients; the set
is frozen by a test that enumerates write-on-GET handlers, so a new
side-effecting GET fails CI and must be argued for.

### Historic secret in a deleted smoke script

The full-history gitleaks scan found a hardcoded `jwt_secret` and a local
admin password in the deleted `apps/api/scripts/smoke_verify.py`. The values
appear nowhere in the tracked tree and in no live configuration (digest
comparison over 121 literals; `.audit/evidence/E-B-159`). History rewriting
is not authorized. **Owner action:** confirm the values were never used in a
deployed environment; if they were, rotate `JWT_SECRET` and the admin
password.

### Chat images reach the vision provider with their EXIF intact

Inline chat images are validated (mime allow-list, strict base64, size cap,
magic-byte sniffing) but forwarded byte-for-byte, so GPS/EXIF metadata can
travel to the LLM provider. The provider is the same one that already
receives the prompt text, retention is the provider's default, and images
are not stored by this application. Re-encoding via Pillow to strip EXIF is
the planned fix and needs a declared runtime dependency (`routes/common.py`
owns the payload; see the handoff note in `.audit/handoffs/hi-from-b.md`).
Revisit before any release that keeps images server-side.

## Non-production targets

`ENV=test`, `LLM_PROVIDER=mock` and `ALLOW_MOCK_LLM_IN_PRODUCTION=true` are
development affordances. Findings that only exist under them are still
welcome, but they will not block a release.
