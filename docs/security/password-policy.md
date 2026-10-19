# Password policy — NIST SP 800-63B alignment

Scope: how the API stores and accepts passwords. Sources checked 2026-10-19:
NIST SP 800-63B, *Digital Identity Guidelines — Authentication and Lifecycle
Management*, Revision 4, §3.1.1.1–§3.1.1.2 (<https://pages.nist.gov/800-63-4/sp800-63b.html>,
page last modified 2025-08-26; the page states it supersedes SP 800-63B
Rev. 3). File references are to this repository at the commit that adds this
document.

## Requirement → implementation

| SP 800-63B §3.1.1.2 requirement (Rev. 4 wording) | Implementation | Where |
|---|---|---|
| "SHALL compare the prospective secret against a blocklist that contains known commonly used, expected, or compromised passwords" | Embedded offline breach corpus (514 entries) + hand-curated common list, both folded for case/leetspeak/trailing-digit variants | `apps/api/src/bangla_gpt_api/services/breached_passwords.py`; `auth/security.py:is_common_password` |
| "The entire password SHALL be subject to comparison, not substrings" | Comparison uses the whole normalised candidate (folding, never substring search) | `services/breached_passwords.py:fold_variants` |
| "If the chosen password is found on the blocklist … SHALL provide the reason for rejection" | 400 `password_too_common` with an explicit message; breached values get their own wording ("appears in known data breaches") | `routers/auth.py:_reject_common_password` |
| "SHALL NOT impose other composition rules (e.g., requiring mixtures of different character types)" | **No character-class rules exist.** A 17-character all-lowercase passphrase is accepted; pinned by `tests/test_b2_breached_passwords.py::test_nist_length_over_composition` | `apps/api/src/bangla_gpt_api/schemas.py` (length only) |
| "SHALL NOT require subscribers to change passwords periodically" | No forced rotation. There is an admin-seeded `must_change_password` first-login flag only (`settings.force_admin_password_change`), which is a bootstrapped-credential measure, not periodic rotation | `initialize/dependencies.py`, `schemas.py:must_change_password` |
| "SHALL NOT permit the subscriber to store a hint … accessible to an unauthenticated claimant" | No password hints or security questions exist anywhere in the product | n/a (`rg -i 'security question\|password hint' apps/api/src` empty) |
| "SHALL request the password to be provided in full … not truncate it" | Passwords are accepted and hashed in full (max 128 chars is a DoS bound, above the "permit at least 64" SHOULD) | `schemas.py` fields (min 8 / max 128) |
| Check that blocks "repetitive or sequential characters" | Structure rules: ≤3 distinct characters and repeated-unit patterns ("aaaaaaaa", "abababab") | `auth/security.py:is_common_password` (unchanged, F-072) |
| Verification: salted, memory-hard hash; breach-checked on establish/change | Argon2id t=2, m=19 MiB, p=1 (OWASP minimum); verified against legacy PBKDF2 and rehashed in place on login | `auth/security.py:_ARGON2`, `needs_rehash` |
| Rate limiting / throttling against online guessing | Per-IP login rule + per-account progressive lockout (5 failures → 60 s, doubling to 1 h) with `Retry-After` | `routers/auth.py:_LOGIN_LOCKOUT_*`, `ratelimit.py` |

The blocklist is deliberately offline: no network call, no file read, so a
registration cannot be blocked by, or leak the candidate to, a third-party
breach service — a privacy requirement on a children's platform. The trade-off
is corpus size; 514 entries close the audit finding at the top of the public
frequency lists, they are not HaveIBeenPwned's 800M entries.

## Known gaps (documented, not silently accepted)

1. **Minimum length.** Rev. 4 §3.1.1.2 sets the floor at 15 characters for
   passwords used as single-factor authentication and 8 only when the password
   is always paired with a second factor. This service is at 8 with MFA
   *optional* (`schemas.py: password: str = Field(min_length=8, max_length=128)`),
   i.e. the Rev. 3 floor. Raising it to 15 is a schema + copy + UX change
   outside this remediation's file ownership; requested in
   `.audit/handoffs/schemas-b2.md`.
2. **Full breach corpora.** A repository-embedded list cannot match a hosted
   service; the compensating control is the account lockout plus the fact that
   the corpus covers the entries credential-stuffing tools try first.

Owner action: confirm whether the product's risk position adopts the Rev. 4
15-character floor before scale, and whether any hosted breach-check (with a
k-anonymity-preserving lookup) is in scope.
