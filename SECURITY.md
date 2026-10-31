# Security Policy

Bangla GPT APP holds personal data about **children**: student names, class
levels, guardian phone numbers, quiz answers and full tutor conversation
history. A disclosure here is a disclosure about a child, so treat every
report accordingly and do not paste real student data into an issue.

## Reporting a vulnerability

**Do not open a public issue.** Public issues are visible to everyone,
including people who would use the knowledge.

Use GitHub's private reporting — it is the monitored channel:

- Repository → **Security** → **Advisories** → **Report a vulnerability**
  (it gives you a private thread and a tracking id)

There is no separate security mailbox. If GitHub is itself unavailable, open
a minimal public issue asking for a private channel and disclose nothing in
it.

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

## Non-production targets

`ENV=test`, `LLM_PROVIDER=mock` and `ALLOW_MOCK_LLM_IN_PRODUCTION=true` are
development affordances. Findings that only exist under them are still
welcome, but they will not block a release.
