# Cloudflare Workers feasibility — Bangla GPT

**Date:** 2026-11-18 · Status: **DECISION DOCUMENT — engineering recommendation, owner sign-off required for any change**
**Docs retrieved:** developers.cloudflare.com Workers limits + Python Workers (retrieved 2026-11-18; the Python page carries a Sep 2026 date). Limits change — re-verify at decision time; no stale quota is baked into this recommendation.

---

## 1. Executive recommendation

**RETAIN CURRENT PLATFORM** for the API and all student-data processing; continue using
Cloudflare for what it already does (DNS, CDN/proxy in front of the origin). Treat the
**thin edge gateway** (Option B) as **POC ONLY** — a candidate worth measuring only if the
owner wants edge-level routing/WAF logic that the existing Cloudflare proxy config cannot
express. **Do not migrate FastAPI to Workers** (Option D): the compatibility matrix below
shows hard blockers, not merely costs.

Rationale in one line: the platform's hard requirements — synchronous SQLAlchemy/psycopg
against Postgres, Redis-backed sessions/rate-limits, arq background jobs, native-wheel
PDF shaping (uharfbuzz), on-disk font assets — are exactly the things the Workers runtime
does not provide, while the things Workers *is* great at (edge routing, static delivery,
WAF) are already covered by the existing Vercel + Cloudflare setup.

## 2. Workload-by-workload compatibility matrix

Sources for the "current platform" column: `apps/api/pyproject.toml`-level dependency
graph, `apps/api/src/bangla_gpt_api/` services, `docker-compose.yml`, `docs/runbook.md`
(at baseline). Workers facts from the retrieved docs.

| Workload | Verdict | Basis |
|---|---|---|
| Static PWA asset/font/image delivery | **already served** | Vercel serves the PWA; self-hosted fonts are immutable static assets. Workers/Pages would add a second static host for no gain. |
| DNS, CDN, WAF, DDoS, bot management | **already in use** | Cloudflare proxies the origin today (hosting_decision.md). No Workers required. |
| Edge gateway / request routing | **compatible** | Pure routing/header logic is Workers' core strength. Candidate for Option B PoC. |
| Stateless health/status/config endpoints | **compatible** | Trivial fit; but they are already cheap on the origin — no win. |
| Auth/session endpoints & cookies | **compatible with changes** | Session/JTI revocation lives in Redis; a Worker would need Redis reachability (TCP `connect()` or DO-based session store) — unproven with Python clients. |
| FastAPI REST endpoints | **compatible with changes (risky)** | FastAPI itself runs on Python Workers (`python_workers` flag, Pyodide-based). The *stack around it* is the problem — see the next four rows. |
| Sync SQLAlchemy + psycopg → Postgres | **not suitable (today)** | Sync drivers need real TCP sockets; Workers exposes limited outbound sockets and Hyperdrive targets JS drivers. No evidence path for psycopg-over-Hyperdrive in Python Workers docs retrieved. |
| Redis (rate limiting, JTI revocation) | **not yet proven** | Same socket constraint; Python `redis` client unproven. Upstash-style REST would be a redesign, not a port. |
| arq/Redis background jobs (long generation, digests, retention) | **not suitable** | Workers has no long-lived process model; cron caps at 15 min and queue-consumer support for Python is not established. arq is asyncio-Redis — same socket issue. |
| SSE tutor streaming | **compatible** | Streaming responses are supported (no body-size limit; wall-clock unlimited while connected). The *upstream* LLM call is fine; the persistence around it is not. |
| RAG retrieval / embeddings / corpus | **not suitable (today)** | Vectorize exists, but the corpus pipeline, NCTB grounding policy and refusal rules are product-critical; re-platforming them is out of scope by design. |
| File/image uploads, PDF/font processing | **not suitable** | `fpdf2` + `uharfbuzz` (native wheels) and on-disk TTF assets have no Workers path; 128 MB isolate memory is tight for shaping workloads. |
| Scheduled retention/email-digest/maintenance | **compatible with changes** | Cron Triggers exist (15 min cap, 5/250 per account) but the jobs themselves need Postgres/Redis (see above). |
| Logs, metrics, traces, Sentry | **compatible with changes** | Workers has its own observability model; Sentry integration would need re-validation. |

## 3. Options compared

| Option | What it is | Assessment |
|---|---|---|
| **A. Current architecture, Cloudflare for edge services** (recommended) | FastAPI/Compose/Postgres/Redis stays the origin; Cloudflare keeps DNS/CDN/WAF; static stays on Vercel | Zero migration risk; matches the data-residency posture already documented; nothing to build. |
| **B. Thin edge gateway** (POC ONLY) | A Worker does routing/security/header logic and forwards dynamic API requests to the FastAPI origin; **no caching of any authenticated response** | Technically compatible. Value over the existing Cloudflare proxy rules is unproven — only worth a PoC if the owner wants logic the zone's rules cannot express. |
| **C. Narrow Python Worker service** | One stateless, low-latency, independently bounded endpoint ported after proof | No current candidate endpoint is both stateless *and* independent of Postgres/Redis. Re-evaluate if one appears. |
| **D. Full/major API migration** | Replace the serving stack | **Rejected on evidence**: sync DB drivers, Redis, arq, native PDF wheels, filesystem fonts, and 15-min cron ceilings are all blockers or forced redesigns; data-residency posture would need full re-review under Act 63 of 2026. |

Weighted criteria (1–5): data-protection fit ×5, operational risk ×4, engineering cost ×3,
performance ×2, cost ×2. Option A wins on every axis; B is neutral-to-positive on
performance, negative on operational surface until proven.

## 4. Performance/cost assumptions (no PoC run)

**No PoC was executed in this workstream.** Reasons, recorded honestly: running one
requires a Cloudflare account (owner authorization) and a reachable origin; neither is
available in this environment, and F5 forbids pointing a PoC at production. The PoC
criteria below are ready for whoever runs it.

Cost framing (to verify against current pricing at decision time): Workers free tier is
100k requests/day; paid is $5/mo base + usage. At pilot volumes (≈ tens of thousands of
requests/day) the **edge-gateway** cost is negligible; the comparison was never about
cost — it is about capability fit, which §2 settles.

## 5. Data protection / vendor / cross-border assessment

- Any new Cloudflare data path is a **DPIA and vendor-register change** requiring
  owner/counsel approval before production (DPIA §16). Cloudflare would join the register
  with data seen = request metadata (IP, URLs, headers) at minimum; retention and
  sub-processing terms are `UNKNOWN` until the vendor questionnaire in the DPIA is answered.
- **Hard rules for any future gateway PoC:** never cache authenticated API responses, chat,
  quiz submissions, progress, guardian data, consent evidence or tokens at the shared edge;
  `Cache-Control: private, no-store` on sensitive dynamic responses; no PII/tokens/prompts
  in Worker logs or analytics; cache only public immutable assets after verifying no
  user-specific content.

## 6. PoC criteria (if the owner approves Option B)

Directory `experiments/cloudflare-workers/`; pinned Wrangler + explicit compatibility
date/flags; no real student data, no production credentials, no production hostname, no
production DB. Measure cold start, p50/p95/p99, CPU duration, subrequests, failure modes;
contract-parity tests against the origin; teardown steps; DPA/lock-in notes. Only then
would Option B be a decision rather than a hypothesis.

## 7. Operational changes and rollback

Option A requires none. If a gateway were later adopted, rollback is DNS/proxy-config
reversion (the origin never stops serving), which is the main reason B is the only
defensible Workers role here.

## 8. In-scope / out-of-scope summary

- **In scope (adopted):** keep Cloudflare for DNS/CDN/WAF as today; document the decision.
- **Out of scope (rejected/not proven):** FastAPI-on-Workers (D), any stateful endpoint on
  Workers (C, no candidate), any student-data caching at the edge (never).
- **Human decisions outstanding:** owner approval to run the Option-B PoC (only if wanted);
  vendor terms confirmation feeding the DPIA register.
