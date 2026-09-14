# ADR-0001: Modular Monolith Architecture

## Context

The original `main.py` was ~7000 lines with all business logic, middleware, and bootstrap code in a single file. This made the codebase unmaintainable and violated separation of concerns.

## Decision

Refactor into a modular monolith with:
- Thin `main.py` (332 lines) delegating to `initialize/` subpackage
- 13 domain routers in `routers/`
- 45+ service modules in `services/`
- Self-contained infrastructure modules (`providers/`, `retrieval/`)

The entrypoint imports and re-exports test dependencies for monkeypatching.

## Alternatives Considered

1. **Monolithic single-file** — Simple but unmaintainable at scale
2. **Microservices** — Overkill for a single-team educational platform; introduces distributed systems complexity unnecessarily
3. **Plugin architecture** — Adds complexity without proven benefit

## Consequences

- **+** Every domain has clear ownership (router → service → infrastructure)
- **+** `main.py` is now a thin bootstrap file
- **+** Tests can monkeypatch individual services
- **+** New domain modules can be added without touching entrypoint
- **-** Requires discipline to maintain dependency direction (enforced by convention)

## Status

Accepted — Implemented across waves 1-5.

---

# ADR-0002: LLM Provider Abstraction with Mock Default

## Context

The platform must support multiple AI providers (Gemini, OpenAI, OpenRouter, Ollama) but cannot require an API key for basic functionality.

## Decision

Define an `LLMProvider` protocol with factory pattern:
- `mock` provider is the default and always available
- Real providers are loaded only when their API key is set
- `/ready` endpoint returns 503 if configured provider is unavailable
- Provider error propagation through `ProviderError` with retry/circuit breaker

## Alternatives Considered

1. **Always require a real provider** — Poor developer experience for local testing
2. **Hardcode one provider** — Vendor lock-in, no fallback option

## Consequences

- **+** Works offline with mock provider
- **+** Easy to add new providers (implement protocol)
- **+** Graceful degradation when provider is unavailable
- **-** Mock provider doesn't match real model behavior (must test with real provider in staging)

## Status

Accepted — Used across all AI/RAG flows.

---

# ADR-0003: Hybrid Retrieval with BM25 + Vector Fusion

## Context

Pure BM25 retrieval misses semantic matches; pure vector retrieval misses exact term matches. For NCTB academic content, both matter.

## Decision

Implement hybrid retrieval (`RetrievalMode.hybrid`) combining:
1. **BM25 lane** — Lexical matching with Bangla-aware tokenizer (U+0980-U+09FF)
2. **Vector lane** — Deterministic local embeddings (or real multilingual model)
3. **Fusion** — Reciprocal Rank Fusion (RRF) with configurable weights
4. **Reranking** — Trigram similarity fallback blended into BM25 score

`RetrievalMode.bm25` (legacy) is still supported for backward compatibility.

## Alternatives Considered

1. **BM25 only** — Misses semantic relationships between Bangla synonyms
2. **Vector only** — Expensive, misses exact curriculum references
3. **Three-lane (BM25 + vector + metadata filter)** — Deferred until real embeddings are available

## Consequences

- **+** Best of both lexical and semantic matching
- **+** Curriculum-aware filtering at retrieval time
- **+** Configurable per deployment
- **-** RRF weights need tuning per corpus size

## Status

Accepted — Default mode in production.

---

# ADR-0004: Safety Screening Before Retrieval

## Context

Unsafe queries should never reach the retrieval pipeline or LLM provider to prevent prompt injection, data exfiltration, and inappropriate content processing.

## Decision

1. Apply NFKC normalization first (`normalize_query()`)
2. Run Bengali keyword regex patterns (`_screen_safety()`)
3. If unsafe: return refusal immediately without retrieval or LLM call
4. If safe: proceed to retrieval + PII redaction at evidence boundary

Coverage: self-harm, weapons, drugs, sexual content, violence, personal data.

## Alternatives Considered

1. **After LLM generation** — Risk: unsafe prompt still reaches LLM provider (cost, policy violation)
2. **Before normalization** — Risk: mobile keyboard variants bypass keyword filters

## Consequences

- **+** Never calls LLM for unsafe queries (cost savings, policy compliance)
- **+** NFKC normalization prevents variant bypass
- **+** PII redaction on evidence text, not user input
- **-** Keyword-based approach has false positives (academic science terms get flagged)

## Status

Accepted — Safety is a release gate per master prompt Rule 7.

---

# ADR-0005: SQLite Default with Production Refusal

## Context

Local development needs zero-configuration setup; production needs persistent, concurrent-safe database.

## Decision

- Default: `sqlite:///./bangla_gpt.db` (file-based, survives restarts)
- Production boot: `enforce_production_safety()` + `validate_database_url()` refuse `sqlite://` / `sqlite:///:memory:` / any URL containing `:memory:`
- Migration path: Set `DATABASE_URL=postgresql+psycopg://...` for any non-dev deployment

## Alternatives Considered

1. **Always PostgreSQL** — Requires local PostgreSQL install for dev
2. **Always SQLite** — Not suitable for concurrent production access

## Consequences

- **+** Zero-config local development
- **+** Production safety enforced at boot (fail-fast)
- **+** Tests can still use in-memory DB
- **-** `bangla_gpt.db` must be gitignored

## Status

Accepted — Implemented with migration in uncommitted changes.

---

# ADR-0006: NFKC Normalization at AI Boundary

## Context

Bangla mobile keyboards produce both precomposed and decomposed Unicode forms for the same character. Without normalization, queries may fail to match indexed content.

## Decision

Apply `unicodedata.normalize("NFKC", text)` at the AI boundary — specifically in `normalize_query()` called in both `TutorService.ask()` and `TutorService.ask_stream()` before safety screening and retrieval. Also applied in BM25 tokenizer.

## Alternatives Considered

1. **Case-insensitive only** — Doesn't solve precomposed/decomposed Bangla
2. **Full Unicode normalization (NFC + NFD + NFKC + NFKD)** — Over-normalization changes meaning

## Consequences

- **+** Mobile keyboard input matches indexed content
- **+** Symmetric normalization (index + query both NFKC)
- **+** Pure NFKC only — preserves original casing and spacing
- **-** Very small edge cases where NFKC changes meaning (e.g. compatibility characters)

## Status

Accepted — Implemented in uncommitted changes.

---

# ADR-0007: Two-Service Deployment Topology

## Context

The platform has a static frontend SPA and a long-running API server with SSE streaming, job queues, and persistent database connections. These have different deployment requirements.

## Decision

Split deployment into two services:
1. **Vercel** — Static SPA with `/api/*` proxy rewrite to API origin
2. **API origin** — Any long-running host (VM, Docker, PaaS) with Cloudflare tunnel or direct DNS

The API cannot run on Vercel serverless (ephemeral filesystem, no long-running worker, no persistent DB connections).

## Alternatives Considered

1. **Single Vercel deployment** — Serverless can't handle SSE streaming, job queues, or persistent DB
2. **Two separate domains** — Breaks same-origin cookie auth, requires CORS everywhere

## Consequences

- **+** Each service uses its optimal platform
- **+** Same-origin API proxy avoids CORS complexity
- **-** Two deploy targets (need to manage both)
- **-** API host must be always-on (not serverless)

## Status

Accepted — Live deployment documented in `docs/VERCEL_DEPLOY_RECORD_2026-09-13.md`.

---

# ADR-0008: PBKDF2 Password Hashing with Per-Token JWT Revocation

## Context

Student accounts must be secure. Password reset tokens must be revocable if compromised.

## Decision

- Passwords: PBKDF2 with 200,000 iterations (SHA-256)
- JWT: Per-token `jti` (JWT ID) stored in cache
- Logout: Add `jti` to cache → next request rejects token
- Password reset: Generate cryptographically secure token, hash before storing

## Alternatives Considered

1. **bcrypt** — Slower, doesn't support per-token revocation without database lookup
2. **Session-based auth** — Not suitable for SPA + mobile API pattern

## Consequences

- **+** Strong password hashing (OWASP recommended)
- **+** Logout actually revokes token (not just client-side clear)
- **+** No server-side session store needed (stateless JWT)
- **-** Cache (Redis/memory) needed for revocation list

## Status

Accepted — Implemented in `auth/security.py`.

---

# ADR-0009: Fernet PII Encryption at Rest

## Context

Student PII (phone numbers, emails) stored in database must be encrypted at rest to comply with data protection requirements.

## Decision

Use Fernet symmetric encryption (from `cryptography` library):
- `PIIField` in models handles transparent encrypt/decrypt
- Encryption key from env var (`PIENCRYPT_KEY` or generated)
- Audit logging of all PII access

## Alternatives Considered

1. **Application-level hashing** — Can't retrieve original PII for display
2. **Database-level encryption** — Tied to specific DB vendor

## Consequences

- **+** Transparent encrypt/decrypt in ORM layer
- **+** Vendor-neutral (Python-level encryption)
- **+** Audit trail of PII access
- **-** Performance overhead on PII reads/writes

## Status

Accepted — Implemented in `security.py`.
