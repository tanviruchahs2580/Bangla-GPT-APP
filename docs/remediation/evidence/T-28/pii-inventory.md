# T-28 — child-data / PII engineering inventory

Built 2026-11-20 at `6b62442` from the models, the encryption helper, the retention jobs, the audit log and the provider path (H-1 reads this session). No new data collection; no fix landed under this task — the controls verified below already exist, and their tests are named.

## Entities and fields

| Entity (models.py) | Child-related fields | Protection | Retention |
|---|---|---|---|
| `users` (child/teacher/staff/parent) | email, name, `parent.phone_enc` (Fernet, `security.py::encrypt_pii_strict`; refuses plaintext when `PII_ENC_KEY` unset), `totp_secret` (Fernet ciphertext `totp1:`), password_hash (Argon2id), `sessions_invalidated_at` | field-level encryption; Argon2id hashes; plaintext refusal is the control | account lifetime |
| `conversations` / `chat_messages` | child questions + AI answers | retained by design ("a child's academic record needs an age"); no third-party egress without `redact_pii` | **730 days** (`services/retention.py:120,244`) |
| `ai_usage` ledger | per-user tokens/cost (no content) | pseudonymous user ids | **365 days** (`retention.py:122,245`) |
| `ai_jobs` | generation payloads | idempotency ledger | **30 days** |
| `answer_log` | graded answers | rubric-grounded scoring | **730 days** |
| `password_resets` / `email_verifications` / `parent_invites` | single-use tokens | stored as SHA-256 hashes only (`token_hash`, `code_hash`) — never clear | 30-day grace |
| `audit_log` | five privileged events (`role_change`, `data_export`, `purge`, `qp_finalize`, `impersonation`) | append-only; `detail` carries ids/outcome only — never message content, never PII | account erasure anonymises actor id to NULL (documented exception) |
| `consent_*` evidence | `consent_ip`, `consent_at`, `consent_version` | versioned consent (`CONSENT_VERSION`, deps.py:190), re-confirm flow | evidence lifetime |

## Control verification (code + tests, all green on this tree)

| Control | Code | Tests |
|---|---|---|
| PII never reaches a third-party model unredacted | `services/pii.py::redact_pii` (phone/email/NID, metered) | `test_pii.py` |
| Export/erasure parity | `services/gdpr.py::build_data_export` (:624) / `erase_account_everything` (:833) | `test_export_completeness.py` (guards every new student-data table joining export AND erasure AND the retention sweep), `test_data_export.py`, `test_round2_erasure_fk.py` |
| Retention sweeps delete what the code says | `services/retention.py::run_retention_sweep` (:213) with chunked deletes (:311) | `test_dat_001_chat_retention_window.py` |
| Consent recorded and respected | `CONSENT_VERSION` re-confirm semantics; consent refused pre-generation | `test_compliance_v2.py`, `test_dat_003_export_consent_ip.py`, tutor consent gate (`tutor.py:236-238`) |
| Access to child records leaves an audit entry | `write_audit` on the five privileged events; impersonation attribution (SEC-002) | `test_qa_auth_logging.py`, `test_sec_002_impersonated_audit_attribution.py` |
| Logs/traces/metrics carry no personal data | secret-safe logging gate; keyed-hash discipline; Sentry scrub | `test_w2_log_redaction.py`, `test_qa_sentry_scrub.py`, `test_qa_event_prop_values.py` |
| Guardian phone never plaintext | `encrypt_pii_strict` refuses to store without a key | `test_totp_encryption.py` + encryption suites |
| No data minimization gap toward providers | redaction before egress; no name/email/school-id fields sent in tutor prompts (boundaries map, T-27 #7) | `test_pii.py`, `test_rag_001_prompt_trust_boundary.py` |

## Gap routing

- Every engineering control the card probes exists and is tested. The **policy** items (retention durations, DPIA) are owner decisions: the DPIA gap is already recorded in AGENTS.md §15 and stays HO-3 (legal), with the DPIA evidence map + PDPA gazette noted in the mobile-hardening wave memory.
- No new collection, no new storage of raw child text — none proposed here.
