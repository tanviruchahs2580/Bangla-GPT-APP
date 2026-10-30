# Environment variable matrix

Every runtime variable this deployment reads, in one place: the application
settings (`Settings`, apps/api/src/bangla_gpt_api/config.py), the two `.env`
templates, the compose interpolations, and the values only the deployment
tooling consumes. Purpose, default, whether the app refuses to boot without
it, where it is documented, and the code that reads it.

Regenerate the tables with `.qa-work/evidence/E-W2-BE-env/gen_env_matrix.py`
(kept with the wave-2 QA evidence); review the diff, do not paste it blindly.

## Application settings

| Variable | Purpose / production guidance | Default | Required | .env.example | .env.production.example | compose | Code |
|---|---|---|---|---|---|---|---|
| ADMIN_EMAIL | Bootstrap admin created at startup ONLY if both are set and no admin exists. In production both are REQUIRED and ADMIN_PASSWORD must be >=12 chars. | None | - | admin@example.com | admin@example.com | yes | config.py:145 |
| ADMIN_PASSWORD | At least 12 characters; forced rotation on first login is enabled by default. | None | - | - | - | yes | config.py:146 |
| AI_GENERATION_ENABLED | F-031 AI kill switch: false stops tutor/chat generation (answers a localized refusal, refused_reason=ai_generation_disabled) while retrieval, /search, the reader and quizzes keep working; set back to true to resume generation. | True | - | true | true | yes | config.py:113 |
| AI_JOBS_RETENTION_DAYS | F-007: finished AI jobs (ready\|failed) age out; in-flight rows never do. | 30 | - | 30 | - | - | config.py:209 |
| AI_JOB_IDEMPOTENCY_WINDOW_MINUTES | How long an Idempotency-Key header on POST /teacher/jobs stays replayable. | 1440 | - | 1440 | - | - | config.py:224 |
| AI_JOB_MAX_ATTEMPTS | AI job lifecycle (F-007) Total runner executions for one POST /teacher/jobs job (>=1); transient provider failures retry with the backoff below, caller-fixable failures fail on the first attempt. | 3 | - | 3 | - | - | config.py:216 |
| AI_JOB_RETRY_BACKOFF_SECONDS | First backoff delay in seconds; doubles per attempt, capped at 4s. | 0.5 | - | 0.5 | - | - | config.py:220 |
| AI_MONTHLY_BUDGET_USD_PER_USER | looping or abusive account would be bounded only by 30 requests/minute. 5 is a conservative starting point for a student account; measure real usage in /admin/ai/quality and raise deliberately. Generation stops with a coded 429 ai_budget_exceeded when the month's ledger reaches the cap. | 0.0 | - | (commented) 0 | 5 | yes | config.py:106 |
| AI_USAGE_RETENTION_DAYS | The AI spend ledger. The budget math only reads the current month, so a year of history is generous for dashboards and audits while keeping the table bounded for accounts that live for years. | 365 | - | 365 | - | - | config.py:204 |
| ALLOWED_ORIGINS | talks to this API directly (docs/mobile_release.md): without them the WebView's CORS preflight is answered 400 and login fails inside the app while the same account works in a desktop browser (measured live, 2026-10-25). Drop the last two if you ship web-only. | '' | - | http://localhost:5173 | https://tutor.example.edu.bd,capacitor://localhost,https://localhost | yes | config.py:150 |
| ALLOW_BUNDLED_SAMPLE_CORPUS_IN_PRODUCTION | boot that way when a billable provider (gemini/openai) is configured, so point NCTB_CORPUS_DIR at the built corpus. Offline demos that deliberately serve the sample (together with LLM_PROVIDER=mock and ALLOW_MOCK_LLM_IN_PRODUCTION=true) set this instead: | False | - | (commented) false | (commented) true | - | config.py:263 |
| ALLOW_DIRECT_PARENT_LINK | Legacy bare-ID parent linking (insecure; invite-code flow is the default) | False | - | false | false | yes | config.py:231 |
| ANALYTICS_RETENTION_DAYS | Product analytics trail (analytics_events). The table is swept on the same schedule; the account-erasure path also drops the user_id attribution. | 180 | - | 180 | 180 | yes | config.py:196 |
| ANSWER_LOG_RETENTION_DAYS | DB-04: the graded-answer record and the AI spend ledger now age on their own clocks (backfilled from the attempt for pre-existing rows). Two school years for the academic record; one year for the spend ledger (the budget math reads only the current month). | 730 | - | 730 | - | - | config.py:200 |
| APP_NAME | Service identity (rarely overridden): | 'Bangla GPT API' | - | (commented) Bangla GPT API | - | - | config.py:74 |
| CHAT_HISTORY_MESSAGES | Past turns replayed into the tutor prompt; bounds prompt cost and context bloat. | 8 | - | 8 | 8 | yes | config.py:185 |
| CHAT_HISTORY_MESSAGE_CHAR_LIMIT | Per-message char cap when past turns are replayed into the prompt | 2000 | - | 2000 | 2000 | yes | config.py:188 |
| CHAT_RETENTION_DAYS | Chat history older than this is purged by the retention sweep. | 180 | - | 180 | 180 | yes | config.py:189 |
| CIRCUIT_BREAKER_FAILURE_THRESHOLD | Consecutive provider failures before the circuit opens and the fallback (if any) is used. | 3 | - | (commented) 3 # consecutive failures before opening the circuit | - | - | config.py:115 |
| CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS | Circuit breaker (AI resilience) CIRCUIT_BREAKER_FAILURE_THRESHOLD=3 # consecutive failures before opening the circuit | 60.0 | - | (commented) 60 # seconds before probing the primary again | - | - | config.py:116 |
| DATABASE_URL | Default posture: PostgreSQL (--profile core --profile postgres). The boot guard refuses file SQLite with more than one worker; the template used to SHIP sqlite here, steering a copy-paste deploy straight into the posture the current outage runs in (audit F8). | 'sqlite:///./bangla_gpt.db' | - | (commented) sqlite:///./bangla_gpt.db | postgresql+psycopg://bgpt:CHANGE-ME@postgres:5432/bgpt | yes | config.py:132 |
| EMBEDDING_MODEL | Real multilingual embedding models are a staging human decision. Empty -> the deterministic local hash-ngram embedder serves the vector lane; naming a model without the staging backend is a config error. | '' | - | (commented) # real multilingual model = staging human input; empty = deterministic local vector lane | (commented) # S4.3: real multilingual model = staging human input; empty = local vector lane | yes | config.py:126 |
| ENV | Runtime environment: development \| test \| production. A production boot runs the strict safety gates. | 'development' | - | development | production | yes | config.py:76 |
| FORCE_ADMIN_PASSWORD_CHANGE | Force password rotation on first admin login (secure default). | True | - | true | - | yes | config.py:147 |
| GEMINI_API_KEY | Google AI Studio key; required when LLM_PROVIDER=gemini. | None | - | - | - | yes | config.py:81 |
| GEMINI_FAST_MODEL | model router: model serving SIMPLE routes. Empty -> the main model serves every route (routes are still decided + logged). | '' | - | (commented) # S4.2 router: model for SIMPLE routes (empty = main model serves all) | (commented) # S4.2 router: model for SIMPLE routes (empty = main model serves all) | yes | config.py:88 |
| GEMINI_MODEL | Verified live 2026-08-26 with new-format ("AQ.") API keys, which cannot access legacy models like gemini-2.5-flash ("no longer available to new users"). Override via GEMINI_MODEL if your account has broader access. | 'gemini-3.1-flash-lite' | - | gemini-3.1-flash-lite # new-format ("AQ.") keys cannot use gemini-2.5-flash | gemini-3.1-flash-lite # keep in sync with apps/api config default | yes | config.py:85 |
| INVITE_TTL_MINUTES | Lifetime of a parent invite code minted by POST /parents/link/invite. | 1440 | - | 1440 | - | yes | config.py:227 |
| JOBS_BACKEND | arq = web workers stop scheduling; run ONE `docker compose --profile worker` instance instead. inline is also safe (job_runs dedupe), but wastes a timer. | 'inline' | - | inline # inline \| arq | arq # inline \| arq | yes | config.py:166 |
| JWT_AUDIENCE | Claim binding verified on every token (SEC-03); must match any other service that consumes these tokens. | 'bangla-gpt-clients' | - | bangla-gpt-clients | bangla-gpt-clients | yes | config.py:141 |
| JWT_EXPIRE_MINUTES | Access-token lifetime in minutes; the SPA renews before expiry. | 60 | - | 60 | 60 | yes | config.py:136 |
| JWT_ISSUER | Claim bindings verified on EVERY token (RFC 8725). A token minted with a different iss/aud pair is refused, so these must be set in production and must match any other service that consumes these tokens. | 'bangla-gpt-api' | - | bangla-gpt-api | bangla-gpt-api | yes | config.py:140 |
| JWT_SECRET | At least 32 random characters, e.g.: python -c "import secrets;print(secrets.token_urlsafe(48))" | DEFAULT_JWT_SECRET | - | (commented) change-me-to-a-long-random-string | - | yes | config.py:135 |
| LLM_FALLBACK_PROVIDER | "gemini" \| "openai" \| "" | '' | - | (commented) # Secondary provider for auto-fallback (e.g. "gemini" or "openai"; empty = no fallback) | - | yes | config.py:96 |
| LLM_MAX_OUTPUT_TOKENS | timeout (60s); raising these together makes the app refuse to boot. Offline demos only: LLM_PROVIDER=mock requires ALLOW_MOCK_LLM_IN_PRODUCTION=true. ALLOW_MOCK_LLM_IN_PRODUCTION= Hard ceiling on generated completion size (0 = no cap; key omitted from provider payload) | 2048 | - | 2048 | 2048 | yes | config.py:102 |
| LLM_MAX_RETRIES | Retries per LLM call; the per-attempt timeout is derived so the whole chain stays inside the gunicorn worker timeout (60 s). | 2 | - | 2 | 2 | yes | config.py:98 |
| LLM_PROVIDER | --- AI providers --- Primary provider: "mock", "gemini", or "openai" | 'mock' | - | mock # mock \| gemini | gemini # mock \| gemini | yes | config.py:80 |
| LLM_TIMEOUT_SECONDS | GEMINI_FAST_MODEL= # S4.2 router: model for SIMPLE routes (empty = main model serves all) | 30.0 | - | 30 | 30 | yes | config.py:97 |
| LOG_LEVEL | Observability / ops | 'INFO' | - | INFO # DEBUG \| INFO \| WARNING \| ERROR \| CRITICAL | INFO | yes | config.py:346 |
| MAX_BODY_BYTES | DATA-001: 4 MB fits the wave-2 vision contract (~2 MB base64 image JSON per chat turn). The previous 65536 413'd every chat turn that attached a photo; compose ships the same value (docker-compose.yml). | 4000000 | - | 4000000 | 4000000 | yes | config.py:154 |
| METRICS_REQUIRE_AUTH | SEC-001: /metrics is never public in production (boot refuses otherwise). | False | - | false | true | yes | config.py:352 |
| METRICS_TOKEN | Bearer token required by /metrics when METRICS_REQUIRE_AUTH=true; must match deploy/prometheus/metrics_token. | None | - | - | # long random bearer token for scrapers | yes | config.py:353 |
| NCTB_CORPUS_DIR | Directory containing the built NCTB corpus (normalized/ + quality_report.json). | None | - | - | - | yes | config.py:255 |
| OPENAI_API_KEY | OpenAI-compatible provider Support both official OpenAI and OpenAI-compatible APIs (OpenRouter, Together, Ollama). | None | - | (commented) | - | yes | config.py:90 |
| OPENAI_BASE_URL | OpenAI-compatible provider Support both official OpenAI and OpenAI-compatible APIs (OpenRouter, Together, Ollama). OPENAI_API_KEY= OPENAI_MODEL=gpt-4o-mini | None | - | (commented) # Override to a compatible endpoint (defaults to api.openai.com) | - | yes | config.py:92 |
| OPENAI_MODEL | OpenAI-compatible provider Support both official OpenAI and OpenAI-compatible APIs (OpenRouter, Together, Ollama). OPENAI_API_KEY= | 'gpt-4o-mini' | - | (commented) gpt-4o-mini | - | yes | config.py:91 |
| PARENT_DIGEST_CHECK_MINUTES | Scheduler loop cadence for the weekly parent digest (Sunday ~22:00 Dhaka, once per ISO week). | 60 | - | 60 | - | - | config.py:245 |
| PARENT_DIGEST_ENABLED | Parent weekly digest (S3.4): Sunday ~22:00 Dhaka, once per week. Bodies carry summary aggregates only -- never conversation content. | True | - | true | - | - | config.py:244 |
| PASSWORD_RESET_TOKEN_MINUTES | Lifetime of a password-reset token (single use). | 30 | - | 30 | 30 | yes | config.py:142 |
| PII_ALLOW_PLAINTEXT | Must stay unset/false in production: plaintext guardian-phone storage. The production boot gate refuses PII_ALLOW_PLAINTEXT=true (audit B-04). | True | - | true | false | yes | config.py:182 |
| PII_ENC_KEY | refuses to boot in production without it. Generate with: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())" Rotating it invalidates existing ciphertext -- re-encrypt with the old key first (see docs/runbook.md). Store alongside JWT_SECRET; never commit it. | None | - | - | - | yes | config.py:175 |
| RATE_LIMIT_BACKEND | memory \| redis | 'memory' | - | memory # memory \| redis | redis # memory \| redis | yes | config.py:161 |
| RATE_LIMIT_FAIL_OPEN | Redis limiter behaviour when the backend is unreachable: false (default) refuses with 503, true allows the request. | False | - | false # true = allow traffic when Redis is down | false | yes | config.py:162 |
| RATE_LIMIT_LOGIN_PER_MINUTE | Anonymous login attempts per IP per minute before the middleware answers 429. | 10 | - | 10 | 10 | yes | config.py:157 |
| RATE_LIMIT_RULES | --- default rate limit rules (merged over per-field settings in middleware_stack) --- NOTE: the chat LLM routes are /tutor/conversations/{id}/messages[/stream]; a "/tutor/chat" key would match no real path. | {'/auth/login': (10, 'ip'), '/auth/mfa/challenge': (5, 'ip'), '/auth/register': (10, 'ip'), '/auth/mfa': (20, 'user'), '/tutor/ask': (30, 'user'), '/tutor/conversations': (30, 'user'), '/tutor': (60, 'ip'), '/auth/renew': (60, 'user'), '/auth/forgot': (10, 'ip'), '/auth/reset': (10, 'ip'), '/auth/ch | - | (commented) # JSON per-route limits, e.g. {"/quizzes": [30, "user"]}. | - | yes | config.py:268 |
| RATE_LIMIT_TUTOR_IP_PER_MINUTE | Generic IP ceiling for remaining /tutor/* routes (conversation listing). | 60 | - | 60 # IP ceiling for other /tutor/* routes | 60 | yes | config.py:160 |
| RATE_LIMIT_TUTOR_PER_MINUTE | Per-user budget for the /tutor/* chat routes; an IP scope would let one school NAT lock out a classroom. | 30 | - | 30 | 30 | yes | config.py:158 |
| REDIS_URL | Shared cache, limiter and token-revocation store; required when RATE_LIMIT_BACKEND=redis or JOBS_BACKEND=arq. | None | - | - | redis://redis:6379/0 | yes | config.py:163 |
| RETRIEVAL_MODE | GEMINI_FAST_MODEL= # S4.2 router: model for SIMPLE routes (empty = main model serves all) | 'hybrid' | - | hybrid | hybrid # S4.3: hybrid = BM25+vector RRF+rerank; bm25 = v1 baseline | yes | config.py:122 |
| SENTRY_DSN | Error tracking (optional; both apps init Sentry when set). Sentinels are stripped from logs either way. | None | - | # https://xxx@xxx.ingest.sentry.io/xxx | - | yes | config.py:347 |
| SENTRY_ENV | Sentry environment tag; set it to production explicitly or events are tagged environment=development (F-OBS-3). | 'development' | - | production | - | yes | config.py:348 |
| SMTP_ENABLED | Turn password-reset e-mail on; when false the reset token is only printed outside production. | False | - | false | true | yes | config.py:234 |
| SMTP_FROM | From: address on password-reset e-mail. | None | - | - | no-reply@example.edu.bd | yes | config.py:239 |
| SMTP_HOST | SMTP server for password-reset e-mail; used when SMTP_ENABLED=true. | None | - | - | smtp.example.edu.bd | yes | config.py:235 |
| SMTP_PASSWORD | SMTP password; never commit a real value. | None | - | - | - | yes | config.py:238 |
| SMTP_PORT | SMTP port (587 = submission with STARTTLS). | 587 | - | 587 | 587 | yes | config.py:236 |
| SMTP_USER | SMTP username for authenticated submission. | None | - | - | - | yes | config.py:237 |
| TRUST_PROXY_HEADERS | flag lets a caller choose its own rate-limit bucket. Non-IP entries are ignored and the transport peer is used instead. apps/api/scripts/check_proxy_contract.py fails CI if this template, the compose default and the Caddy override ever drift apart. | False | - | false | true | yes | config.py:172 |
| VERSION | Service identity (rarely overridden): APP_NAME=Bangla GPT API | _get_version() | - | (commented) # never set: the reported version is read from apps/api/pyproject.toml | - | - | config.py:75 |
| WEAKNESS_REFRESH_CHECK_MINUTES | Scheduler loop cadence for the nightly weakness reconciliation (daily ~03:00 Dhaka). | 60 | - | 60 | - | - | config.py:252 |
| WEAKNESS_REFRESH_ENABLED | Nightly weakness reconciliation (S4.6): daily ~03:00 Dhaka, recomputes per-concept mastery rows from the graded answer log (counts only). | True | - | true | - | - | config.py:251 |

## Infrastructure and deployment variables (no Settings field)

| Variable | Consumed by | Purpose |
|---|---|---|
| ACME_EMAIL | docker-compose.yml:10 - compose interpolation; compose service env; .env.production.example; docs/deploy | Let's Encrypt account address used by the Caddy TLS profile. |
| ALERT_EMAIL_TO | docker-compose.yml:311 - compose interpolation; compose service env; .env.production.example; docs/deploy | Prometheus reads the same token from deploy/prometheus/metrics_token (git-ignored). Create it with: printf '%s' "$METRICS_TOKEN" > deploy/prometheus/metrics_token otherwise every scrape answers 403. Alertmanager delivers to this address over the SMTP_* settings above. |
| API_HOST_BIND | docker-compose.yml:130 - compose interpolation; .env.production.example; docs/deploy | 0.0.0.0 exposes the API to the network. Nothing authenticates a client at that layer, so leave it on loopback unless a remote tunnel forces otherwise. |
| API_HOST_PORT | docker-compose.yml:122 - compose interpolation; .env.production.example; docs/deploy | The API is published to the HOST for a tunnel or debug client running on the host itself. Caddy and nginx reach it as `api:8000` over the Compose network and ignore these. The defaults are loopback + 8000, which is also what the release workflow's 127.0.0.1:8000/health check depends on. |
| API_TAG | docker-compose.yml:24 - compose interpolation; .env.production.example; docs/deploy | Image tags (CD overrides these) Pin a released tag from ghcr.io/tanviruchahs2580/bangla-gpt-app. `local` means "built from this checkout" and must NOT reach a production host (docs/runbook.md). Replace before deploy. |
| BACKUP_DIR | docker-compose.yml:368 - compose service env; docs/deploy | Container path the backup sidecar writes dumps to (default /backups); documented in docs/runbook.md section 4. |
| BACKUP_INTERVAL_SECONDS | docker-compose.yml:369 - compose interpolation; compose service env; .env.production.example; docs/deploy | Seconds between backup runs in the backup profile. |
| BACKUP_KEEP_DAYS | docker-compose.yml:370 - compose interpolation; compose service env; .env.production.example; docs/deploy | Retention window for local dumps before rotation. |
| DOMAIN | docker-compose.yml:10 - compose interpolation; compose service env; .env.production.example; docs/deploy | Public hostname Caddy serves and requests a certificate for. |
| GF_SECURITY_ADMIN_PASSWORD | docker-compose.yml:346 - compose service env | Grafana service env key, set from GRAFANA_ADMIN_PASSWORD; not set directly in .env. |
| GF_SECURITY_ADMIN_USER | docker-compose.yml:345 - compose service env | Grafana service env key, set from GRAFANA_ADMIN_USER; not set directly in .env. |
| GRAFANA_ADMIN_PASSWORD | docker-compose.yml:346 - compose interpolation; .env.production.example; docs/deploy | Grafana admin password; interpolated into the compose grafana service (GF_SECURITY_ADMIN_PASSWORD). Required whenever the monitoring profile is up. |
| GRAFANA_ADMIN_USER | docker-compose.yml:345 - compose interpolation; .env.production.example; docs/deploy | Grafana admin login; interpolated into the compose grafana service (GF_SECURITY_ADMIN_USER). |
| OFFSITE_SYNC_CMD | docker-compose.yml:371 - compose interpolation; compose service env; .env.production.example; docs/deploy | Optional offsite sync command executed after each backup, e.g. rclone: |
| PGBR_STANZA | docker-compose.yml:397 - compose interpolation; compose service env; .env.production.example; docs/deploy | Optional offsite sync command executed after each backup, e.g. rclone: OFFSITE_SYNC_CMD=rclone copy /backups remote:bgpt-backups |
| POSTGRES_DB | docker-compose.yml:265 - compose interpolation; compose service env; .env.production.example; docs/deploy | Database name created by the postgres service; DATABASE_URL must point at it. |
| POSTGRES_PASSWORD | docker-compose.yml:264 - compose interpolation; compose service env; .env.production.example; docs/deploy | Password for POSTGRES_USER; keep it in the untracked .env only. |
| POSTGRES_USER | docker-compose.yml:263 - compose interpolation; compose service env; .env.production.example; docs/deploy | SQLite fallback (single worker only): DATABASE_URL=sqlite:////data/app.db |
| VITE_API_BASE | docker-compose.yml:219 - compose interpolation; .env.example; .env.production.example; docs/deploy | Base URL the web bundle calls; baked in at build time, so a change needs a rebuilt web image. |
| WEB_CONCURRENCY | docker-compose.yml:75 - compose interpolation; compose service env; .env.production.example; docs/deploy | gunicorn worker count passed to the api service; also gates the memory rate-limiter boot guard. |
| WEB_TAG | docker-compose.yml:220 - compose interpolation; .env.production.example; docs/deploy | Image tag for the web service (CD overrides; `local` must never reach production). |

## Coverage of the sources

- Settings fields: 71
- App settings documented in `.env.example`: 71
- App settings documented in `.env.production.example`: 51
- Compose/infra names with no Settings field: 21
- Present in `.env.example` but not in the production template (20): APP_NAME, VERSION, OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL, LLM_FALLBACK_PROVIDER, CIRCUIT_BREAKER_FAILURE_THRESHOLD, CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS, FORCE_ADMIN_PASSWORD_CHANGE, ANSWER_LOG_RETENTION_DAYS, AI_USAGE_RETENTION_DAYS, AI_JOBS_RETENTION_DAYS, AI_JOB_MAX_ATTEMPTS, AI_JOB_RETRY_BACKOFF_SECONDS, AI_JOB_IDEMPOTENCY_WINDOW_MINUTES, PARENT_DIGEST_ENABLED, PARENT_DIGEST_CHECK_MINUTES, WEAKNESS_REFRESH_ENABLED, WEAKNESS_REFRESH_CHECK_MINUTES, RATE_LIMIT_RULES
- Present only in the production template (0): none

## Known gaps and their disposition

- `SENTRY_ENV=production` and `GRAFANA_ADMIN_USER=admin` are now in
  `.env.production.example` (F-122): a production deployment that follows the
  template tags its Sentry events with the real environment, and the Grafana
  login user is documented beside the password. Both are pinned by
  `tests/test_env_parity.py`.
- `ALLOW_MOCK_LLM_IN_PRODUCTION` is deliberately absent from both templates:
  it is an offline-demo escape hatch the production boot gate accepts only
  together with `LLM_PROVIDER=mock` (see the note in .env.production.example).

## Enforcement

- `tests/test_env_example.py`: every `Settings` field appears in `.env.example`.
- `tests/test_env_parity.py`: the two templates, `Settings` and the compose
  interpolations do not drift apart.
- `apps/api/scripts/check_proxy_contract.py`: `TRUST_PROXY_HEADERS` stays consistent
  with the Caddy overwrite whenever it ships true.
- Production boot guards in `main.py` refuse the unsafe combinations named in
  the Required column (for example a default `JWT_SECRET`, plaintext guardian
  phones, or an in-memory database).
