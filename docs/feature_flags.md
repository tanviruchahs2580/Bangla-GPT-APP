# Runtime switches (feature-flag inventory)

This codebase has no staged-rollout flag framework; it has environment-driven
switches that change behaviour at boot. The audit asked for an inventory with
an owner and an exit condition per switch (ARCH-09 / F-069 family), so this
table is the register: **a new behaviour switch gets a row here in the same
change that adds the setting**, with the owner and the condition under which
the switch should be revisited or removed.

CI-FIX-011: that rule had been broken silently — 9 of the 14 boolean
`Settings` fields were absent from the table until 2026-11-10 (all nine are
added below, including the two the production boot guard treats as
security-relevant: `PII_ALLOW_PLAINTEXT` and `LLM_DATA_USE_ACKNOWLEDGED`).
To check the inventory rather than trust it, list the boolean fields and
compare against the `Switch` column:

```bash
grep -n ": bool = " apps/api/src/bangla_gpt_api/config.py   # 14 fields, 2026-11-10
```

Defaults are read from `apps/api/src/bangla_gpt_api/config.py` and the boot
guards in `main.py`; the compose/example files that override them are named
where they differ.

| Switch | Default | Effect | Owner | Exit condition / review |
|---|---|---|---|---|
| `AI_GENERATION_ENABLED` | `true` | Kill switch: `/tutor/ask` and both chat-turn routes answer 200 with a localized refusal (`refused_reason=ai_generation_disabled`); retrieval, search and quizzes keep working | platform operator | Permanent operational control (runbook §11, `docs/ai/incident-response.md` §8). Review at each launch gate. |
| `ALLOW_MOCK_LLM_IN_PRODUCTION` | unset | Lets the mock provider boot in production (`main.py` boot guard escape) | owner | Must stay unset for any real deployment; re-check before every release tag. |
| `ALLOW_BUNDLED_SAMPLE_CORPUS_IN_PRODUCTION` | `false` | Lets the 78-chunk synthetic corpus serve in production when a billable provider is configured | owner | Delete when the real NCTB corpus is deployed (`LAUNCH_READINESS_CHECKLIST.md` §3). |
| `METRICS_REQUIRE_AUTH` | `false` in Settings; `true` in `docker-compose.yml` and `.env.production.example` | Production boot refuses to start unless true; `/metrics` then requires the bearer token | platform operator | Keep `true` in production; the Settings default only serves dev/test. |
| `RATE_LIMIT_FAIL_OPEN` | `false` | `false` answers 503 on rate-limited routes when Redis is down (fail closed) | platform operator | Permanent security posture; changing it is an incident-level decision (runbook §8). |
| `JOBS_BACKEND` | `inline` | `inline` runs the weekly digest / nightly rollup in every web process; `arq` silences them and expects one worker (`apps/api/worker.py`) | platform operator | Keep `arq` for multi-instance deployments; revisit if the worker profile is dropped. |
| `RETRIEVAL_MODE` | `hybrid` | `hybrid` = BM25 + vector + RRF + lexical rerank; `bm25` is the smoke/debug lane | RAG owner | Review after the dense-retrieval benchmark (`docs/rag/target-architecture.md`); `hybrid` stays the target. |
| `RETRIEVAL_ONLY_FALLBACK_ENABLED` | `false` | When the provider fails, answers the retrieval excerpt (coded refusal path kept) instead of the 502 `llm_unavailable` envelope — `refused_reason=provider_unavailable` | RAG owner | Decide with the student-UX review: an excerpt instead of an error. Default stays `false` (the pinned 502 contract) until that decision is recorded. |
| `LLM_DATA_USE_ACKNOWLEDGED` | `false` | Acknowledgement that the vendor tier's data-use/retention terms were looked up and recorded (`docs/playstore/data-safety.md`). A production boot with `LLM_DATA_USE_TIER=free` refuses without it | owner (privacy) | Must be `true` (with a dated record) before serving children's questions on a free tier; never set it without reading the terms. |
| `SMTP_ENABLED` | `false` | Email verification and password reset delivery; off means accounts auto-verify | platform operator | Must be `true` before launch (`LAUNCH_READINESS_CHECKLIST.md` §3). |
| `SMTP_REQUIRE_STARTTLS` | `true` | Verification/reset e-mail must not cross the wire in clear; `false` is for a local sink without TLS (mailpit on 1025) and upgrades opportunistically | platform operator | Keep `true` for any real relay; `false` is a dev-lane setting. |
| `FORCE_ADMIN_PASSWORD_CHANGE` | `true` | Forces admin password rotation on first login (the bootstrap `ADMIN_PASSWORD` is therefore one-time) | platform operator | Permanent secure default; only a documented break-glass rotation flow may disable it. |
| `TRUST_PROXY_HEADERS` | `false` | Lets the rate limiter/audit read the client IP from `X-Forwarded-For`; safe only behind a proxy that OVERWRITES the header (`apps/api/scripts/check_proxy_contract.py` pins the bundle) | platform operator | Keep `false` unless the deployment's proxy rewrites the header; re-check whenever the proxy topology changes. |
| `PII_ALLOW_PLAINTEXT` | `true` in Settings; `false` in both `.env` templates | Plaintext guardian-phone storage fallback. The production boot gate **refuses** `true`; a missing `PII_ENC_KEY` with it false makes the write fail with a coded 503 instead of storing PII in clear | platform operator | Keep `false` in production; the `true` default only serves dev/test. Delete the fallback when no lane needs it. |
| `ALLOW_DIRECT_PARENT_LINK` | `false` | Legacy bare-`student_id` parent linking (any parent could link any student); the invite-code flow is the default | platform operator | Enable only for controlled migrations/tests; delete once no migration needs it. |
| `PARENT_DIGEST_ENABLED` | `true` | Weekly parent digest (Sunday ~22:00 Dhaka), summary aggregates only — never conversation content | platform operator | Review with the privacy policy; any change to what the digest carries is a policy change (runbook retention section). |
| `WEAKNESS_REFRESH_ENABLED` | `true` | Nightly per-concept mastery reconciliation from the graded answer log (aggregate counts only) | platform operator | Permanent data-hygiene job; disable only while debugging the rollup, never in production steady state. |
| `BGPT_OCR_CONFIRMED` | unset | Permission gate for textbook OCR ingestion; anything other than `yes` refuses to run | owner (rights) | Expires when the rights-holder permission is recorded (`F-013`); then remove the gate or record it as a permanent prerequisite. |
| `CHAT_RETENTION_DAYS` | `180` | Purge window for conversations (`POST /admin/maintenance/purge`) | owner + platform operator | Must match the published privacy policy; re-check at each policy revision (`LAUNCH_READINESS_CHECKLIST.md` §1). |

Two switches exist only for development and never belong on a production host:
`ENV` (any non-production value relaxes the boot guards) and `LLM_PROVIDER=mock`
(the default). `SECURITY.md` "Non-production targets" states the same rule.
