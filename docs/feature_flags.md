# Runtime switches (feature-flag inventory)

This codebase has no staged-rollout flag framework; it has environment-driven
switches that change behaviour at boot. The audit asked for an inventory with
an owner and an exit condition per switch (ARCH-09 / F-069 family), so this
table is the register: **a new behaviour switch gets a row here in the same
change that adds the setting**, with the owner and the condition under which
the switch should be revisited or removed.

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
| `SMTP_ENABLED` | `false` | Email verification and password reset delivery; off means accounts auto-verify | platform operator | Must be `true` before launch (`LAUNCH_READINESS_CHECKLIST.md` §3). |
| `BGPT_OCR_CONFIRMED` | unset | Permission gate for textbook OCR ingestion; anything other than `yes` refuses to run | owner (rights) | Expires when the rights-holder permission is recorded (`F-013`); then remove the gate or record it as a permanent prerequisite. |
| `CHAT_RETENTION_DAYS` | `180` | Purge window for conversations (`POST /admin/maintenance/purge`) | owner + platform operator | Must match the published privacy policy; re-check at each policy revision (`LAUNCH_READINESS_CHECKLIST.md` §1). |

Two switches exist only for development and never belong on a production host:
`ENV` (any non-production value relaxes the boot guards) and `LLM_PROVIDER=mock`
(the default). `SECURITY.md` "Non-production targets" states the same rule.
