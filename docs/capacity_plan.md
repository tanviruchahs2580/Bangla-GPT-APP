# S6.6 — Capacity plan: 10k / 100k / 1M monthly active users

Status: plan-of-record for GATE G6. Local measurements cited where they
exist; every assumption is stated so it can be replaced with a pilot
measurement during S7. No secrets, no PII in this document.

## 1. Measured baselines (this repo, local)

| Fact | Value | Source |
|---|---|---|
| App throughput | 2 uvicorn workers ≈ **120 concurrent quiz journeys**, p95 < 300 ms (DB-bound) | runbook §Capacity, k6 `load/tutor_load.js` |
| LLM path | p95 2–8 s per `/tutor/ask` — **upstream-bound**, not worker-bound | runbook; FINAL validation §44 |
| Cold first-visit JS (main entry) | 281 KB raw → **84 KB on-wire (gzip)** via preview server | measured 2026-09-08 (:4174) |
| All JS chunks on disk | 789 KB (lazy chunks fetched per feature: quiz, chat, admin) | dist/assets |
| CSS | 55 KB raw | dist/assets |
| UI webfonts shipped | 12 woff2 subsets, 317 KB total (all weights × subsets) | dist/assets |
| Bengali UI font on-wire | hind-siliguri-bengali-400: **51.6 KB gzip on-wire** | measured (:4174) |
| KaTeX fonts | ~301 KB, but unicode-range split → only fetched by students who actually see math | dist/assets |
| Full corpus server DB (dev, synthetic) | 1.3 MB SQLite | apps/api/dev.db |

## 2. Workload model (assumptions — replace with pilot data)

- **DAU = 35 % of MAU** during school term (Bangladesh secondary-school
  pattern: weekdays, homework hours).
- **Peak concurrency = 8 % of DAU** in the 4-hour evening peak.
- Per DAU-day: **3 tutor asks + 1 quiz**; a journey ≈ 12 HTTP requests
  (auth, SSE stream frames count as 1 request).
- Per LLM call: ~1.2 k input tokens (system + RAG context) + ~0.6 k
  output tokens.
- 22 school days per month drive LLM volume; retention purge
  (`CHAT_RETENTION_DAYS=180`) bounds DB growth.

## 3. Sizing table

| Metric | 10k MAU | 100k MAU | 1M MAU |
|---|---|---|---|
| DAU | 3 500 | 35 000 | 350 000 |
| Peak concurrent journeys | 280 | 2 800 | 28 000 |
| Avg peak-hour RPS (journeys×12) | ~12 | ~117 | ~1 170 |
| API workers needed (60 journeys/worker measured) | 5 → **3 replicas × 2** | 47 → **6 replicas × 8** | 467 → LB + autoscaled pool; SSE moves to dedicated stream tier |
| Gemini calls / day | ~10 500 | ~105 000 | ~1 050 000 |
| Gemini tokens / month | ~416 M | ~4.2 B | ~41.6 B |
| Est. LLM cost / student / month (paid-tier list price assumption, see §5) | ~$0.024 (≈ ৳3) | same | same |
| Postgres size / year (attempts ~2 KB + msgs ~1 KB) | < 1 GB | ~5 GB | ~40–60 GB (180-day purge keeps steady state ~25 GB) |
| Redis (rate-limit + imp-revocation keys) | < 10 MB | ~35 MB | < 200 MB |
| Bandwidth / peak-hour | ~1 GB | ~10 GB | ~100 GB (CDN-fronted static assets) |

Near-term gate (G6 = 100 schools ≈ 5–10k MAU) therefore fits the
**existing single compose node** (2 vCPU) for the app tier; the LLM tier
is the only thing that needs an upgrade decision before pilot scale.

## 4. Webfont subsetting — measured reduction

Experiment: `scripts/font_subset_report.py` (run from `apps/web`). It
scans every shipped web source file to build the real UI charset (411
codepoints), unions the full Bangla block (0980–09FD — LLM answers are
open-ended, it cannot be trimmed), plus danda/typography/math ranges,
and re-subsets each shipped font to woff2:

| Font (source) | Before | Subset | Saved |
|---|---|---|---|
| Full NotoSansBengali-Regular.ttf (server PDF font) | 130 588 B | 36 784 B | **71.8 %** |
| hind-siliguri bengali 400/600 (UI primary) | 145 860 B | 134 500 B | 7.8 % |
| hind-siliguri latin 400/600 | 29 196 B | 26 764 B | 8.3 % |
| hind-siliguri latin-ext 400/600 | 16 816 B | 4 348 B | **74.1 %** |
| noto-sans-bengali bengali 400/700 (fallback) | 92 140 B | 59 688 B | **35.2 %** |
| noto latin + latin-ext (fallback) | 32 996 B | 18 636 B | 43.5 % |
| **All shipped UI fonts** | **317 008 B** | **243 936 B** | **23.0 %** |

Readings:

- @fontsource already ships per-script subsets with `unicode-range`, so
  a Bengali student's real cold download is ≈ **175 KB fonts** (hind
  bengali 400/600 + hind latin 400/600 — latin subsets only when Latin
  digits render; noto fallback rarely fetched). That is the honest
  baseline to optimize against, not the 317 KB theoretical worst case.
- Remaining headroom is real but bounded: dropping the latin-ext
  subsets (unused; 74–92 % of their glyphs vanish under the UI charset)
  and switching the Noto fallback to the UI-subset variant saves
  ~23 % of the shipped font directory. Decision recorded here: keep
  @fontsource as-is for pilot (correctness over cleverness); revisit
  with real network logs at 100k MAU. The subset script is the
  repeatability evidence, not an open action item.
- The 71.8 % figure is the classic full-font→subset reduction and is
  used only for the server-side PDF font path if PDF payload ever
  matters; today the TTF stays server-side.

## 5. LLM cost model (flagged assumption)

At an assumed paid-tier list price of $0.10/M input + $0.40/M output
tokens: 3 asks/day × 22 days × (1.2 k in + 0.6 k out) ≈ **$0.024
(~৳3) per student per month**; 100k MAU ≈ $2.4k/month. Free tier costs
৳0 but throttles → documented degraded mode (S6.8 drill). **Verify
actual contracted rates at procurement — human sign-off item, do not
budget from this table without it.**

## 6. Scaling path

1. **≤ 10k MAU (pilot, today):** current docker-compose on one VPS +
   Caddy TLS + Postgres + Redis. All green today.
2. **≤ 100k MAU:** managed Postgres (backups/ PITR), 2 app nodes behind
   LB, static assets + fonts to CDN (already content-hashed, 1-year
   immutable cache), paid Gemini tier + key pool for retry budget,
   background job worker isolated from API nodes.
3. **≤ 1M MAU:** k8s (or 3+ node pool) with HPA on SSE connections,
   Postgres read replicas for dashboards/parent views, Redis cluster
   (rate limits are the hot key path), LLM gateway with per-key quotas
   and queue-based quiz generation; aggregate govt reports (S6.5) move
   to read replica — they scan quiz_attempts fully.

Triggers (measure, don't guess): p95 quiz > 500 ms or > 60 concurrent
journeys per worker → step 2; > 500 RPS sustained or Postgres CPU >
70 % → step 3.

## 7. How this plan gets falsified (G6)

- 10× local load game-day (S6.8) against the k6 thresholds;
- degraded-mode drill with LLM disabled;
- pilot-week real DAU/peak replaces §2 assumptions;
- CDN/network logs replace the §4 theoretical payloads.
