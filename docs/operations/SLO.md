# Service Level Objectives — Bangla GPT API

> **Status: DRAFT — FOR OWNER RATIFICATION (I10).** Nothing in this document
> is in force until the owner signs the ratification block at the end. The
> numbers below are *proposals* derived from the instrumented series and the
> audit's measurements; they are deliberately few and each one is attributable
> to a metric that exists today.
>
> Owner decision required because: SLO ratification is an owner-only decision
> (master prompt I10), and the error-budget policy changes what the team may
> deploy during a bad week.

## 1. Scope and windows

| | |
|---|---|
| Service | The HTTP API (`apps/api`), serving the tutor, teacher, school and admin surfaces |
| In scope | All requests counted by `bgpt_http_requests_total`, plus the tutor pipeline signals in §4 |
| Out of scope | The static SPA CDN (Vercel) availability; third-party LLM provider uptime (it is a dependency, measured through our own error rate); the SQLite development deployment |
| Primary window | Rolling 28 days |
| Burn-rate windows | 1h + 5m (page), 6h + 30m (ticket) — see §5 |

Every SLI below is computable from the `/metrics` endpoint alone
(`deploy/prometheus/prometheus.yml` scrapes it). If a series named here is
absent from an environment, that SLI is **UNVERIFIED** in that environment —
say so rather than reporting a green number (truth protocol T2/T7).

## 2. SLI and SLO definitions (proposed)

### SLO-1 — Availability

- **SLI:** share of HTTP requests answered with a non-5xx status, 28-day
  rolling, measured over all routes.
- **PromQL:**
  `sum(rate(bgpt_http_requests_total{status!~"5.."}[28d])) / sum(rate(bgpt_http_requests_total[28d]))`
- **Proposed target: 99.5%** (error budget 0.5% = ~3h 22m of full outage per
  28 days). Rationale: the platform is a single-region beta with a live
  product; 99.9% would require a multi-zone database the owner has not
  approved (see `docs/backup_dr.md` §SPOF).
- **Exclusions:** planned maintenance announced ≥ 24h ahead; a provider-side
  outage that degrades *answers* but returns 200 is not an availability event
  (it is SLO-3's problem).

### SLO-2 — Latency

- **SLI (a):** p95 of `bgpt_http_request_duration_seconds` over all routes,
  28-day rolling window.
- **PromQL:**
  `histogram_quantile(0.95, sum(rate(bgpt_http_request_duration_seconds_bucket[28d])) by (le))`
- **Proposed target: p95 ≤ 1 s.** Rationale: matches the existing
  `HighP95Latency` alert threshold, so alert and objective cannot disagree.
- **SLI (b), tutor streaming:** live-model time-to-first-token is **not
  instrumented as a histogram today** (only total request duration, which for
  SSE includes the whole stream). Target proposal for when the histogram lands:
  TTFT p95 ≤ 3 s per the audit's A9-01 proposal. **Status: UNVERIFIED / not
  measurable in this build** — listed so it is not silently dropped.

### SLO-3 — Answer quality proxy (refusal behaviour)

- **SLI:** share of answered tutoring turns that are refusals, over gated
  retrieval traffic, 7-day rolling.
- **PromQL:**
  `sum(rate(bgpt_ai_answers_total{outcome="refused"}[7d])) / sum(rate(bgpt_ai_answers_total[7d]))`
  (cross-check with `bgpt_rag_gate_outcomes_total{gate="refuse"}` /
  `bgpt_rag_gate_refusals_total`).
- **Proposed target: ≤ 30% refusal share**, with a **floor** monitor at 5%
  (a refusal share near zero on out-of-corpus traffic would mean the coverage
  gate stopped gating). Rationale: this is a *proxy* — it cannot tell a
  correct refusal from a wrong one. The honest quality measurement is the
  held-out evaluation (Domain A); until that gate exists in CI, this SLI is
  the only production-visible guard against silent corpus degradation.
- **Not a quality SLO.** Do not present the refusal share as accuracy.

### SLO-4 — Async generation jobs

- **SLI:** share of terminal async jobs that reached `ready`, 7-day rolling.
- **PromQL:**
  `sum(rate(bgpt_ai_jobs_total{status="ready"}[7d])) / sum(rate(bgpt_ai_jobs_total[7d]))`
- **Proposed target: ≥ 95%.** Rationale: a failed job is a teacher-visible
  dead end; the retry story is manual today.

### SLO-5 — Cost budget

- **SLI:** projected month-end LLM spend (ledger estimate) versus the
  configured `AI_MONTHLY_BUDGET_USD`.
- **PromQL:**
  `sum(increase(bgpt_ai_cost_usd_total[30d])) * 30 / clamp_min(day_of_month(), 1)`
- **Proposed target: projected spend ≤ 100% of budget**, warning at 80%.
  Rationale: cost is an availability concern for a grant-funded deployment.
  The figures are estimates from `services/costs.py` (list prices, cited
  there); the vendor invoice is authoritative (T5/T7).

## 3. Error budget

- Error budget (Availability) = 0.5% of requests per 28-day window.
- Latency budget = the share of the window in which p95 > 1 s (monitored,
  not a hard budget until the owner sets one).
- Budget state is reported monthly by the owner's delegate from the Alertmanager
  history; there is no automated budget ledger yet (**gap, listed as an owner
  action** — the burn-rate alerts below page on *rate*, not on cumulative
  budget depletion).

## 4. Burn-rate alerting (committed)

The rules live in `deploy/prometheus/alerts.yml`; the math is the standard
multi-window burn-rate construction (long window proves the trend, short
"reset" window proves it is still burning):

| Burn rate | Long window | Short window | Action | Rule |
|---|---|---|---|---|
| 14.4x (2% of budget/hour) | 1h | 5m | **Page** the on-call engineer | `AvailabilityErrorBudgetBurnFast` |
| 6x (10% of budget/28h) | 6h | 30m | Ticket; investigate in business hours | `AvailabilityErrorBudgetBurnSlow` |
| Latency p95 > 1 s sustained | 6h | — | Ticket | `LatencyErrorBudgetBurnSlow` |
| Projected spend > budget | 30d | — | Ticket; owner decides throttle vs raise | `AIMonthlyBudgetBurnRateHigh` |
| Job failure share > 20% | 1h | — | Ticket | `AIJobFailureRateHigh` |

### Error-budget policy (proposed)

1. **Budget healthy (> 50% remaining):** normal delivery; risky changes ship
   behind flags.
2. **Budget below 50% remaining:** only reliability fixes and already-approved
   releases; new surface area waits.
3. **Budget exhausted:** feature freeze for the API; the owner names the
   resumption criterion (a full window under budget, or a fixed defect list).
4. **Two consecutive windows exhausted:** mandatory post-incident review with
   the owner before the next feature release.
5. The policy never authorises skipping the release gates (G0–G12); it only
   narrows what ships.

## 5. Measurement sources and known gaps

| SLI | Series | Source of truth |
|---|---|---|
| Availability | `bgpt_http_requests_total{status}` | `metrics.py`, middleware |
| Latency | `bgpt_http_request_duration_seconds` | `metrics.py`, middleware |
| Retrieval latency | `bgpt_rag_retrieval_latency_seconds` | `services/tutor.py` |
| Refusals | `bgpt_ai_answers_total`, `bgpt_rag_gate_*` | `services/tutor.py` |
| Cost / tokens | `bgpt_ai_cost_usd_total`, `bgpt_ai_tokens_total` | `services/costs.py` |
| Jobs | `bgpt_ai_jobs_total` | `routers/workspace.py` |

Gaps, stated rather than papered over:

- No TTFT histogram (SLO-2b unmeasurable today).
- No cumulative error-budget ledger; burn-rate only.
- No per-tenant SLIs (school-scoped reporting is an owner decision).
- The refusal-share SLI cannot separate correct from incorrect refusals.

## 6. Owner ratification

- [ ] SLO-1 availability target (proposed 99.5% / 28d)
- [ ] SLO-2 latency target (proposed p95 ≤ 1 s) and the TTFT gap accepted
- [ ] SLO-3 refusal-share monitor (proposed ≤ 30%, floor 5%) accepted *as a proxy*
- [ ] SLO-4 job success target (proposed ≥ 95%)
- [ ] SLO-5 budget target and the alert routing
- [ ] Error-budget policy §4 (freeze rules) and the named on-call owner
- [ ] Escalation contacts (see `docs/runbook.md` → "Escalation contacts", currently owner actions)

Signed: ______________________  Date: __________
