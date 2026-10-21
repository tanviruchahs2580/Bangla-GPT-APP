# Cost model (A2-20 / A9-02)

Command: `cd apps/api && python scripts/cost_report.py [--budget <USD>]`.
Artifact: `apps/api/eval/cost_report.json`. Pure math lives in
`apps/api/src/bangla_gpt_api/evaluation/cost_model.py` and is tested by
`apps/api/tests/test_eval2_cost.py`.

## Prices: looked up, cited, and pinned to the runtime table

| Model | Provider page | Page last updated | Read | Input USD / 1M | Output USD / 1M |
| --- | --- | --- | --- | --- | --- |
| `gemini-3.1-flash-lite` (config default) | <https://ai.google.dev/gemini-api/docs/pricing> | 2026-10-16 | 2026-10-19 | 0.25 | 1.50 |
| `gemini-2.5-flash-lite` | <https://ai.google.dev/gemini-api/docs/pricing> | 2026-10-16 | 2026-10-19 | 0.10 | 0.40 |
| `gpt-4o-mini` | <https://platform.openai.com/docs/pricing> | — | 2026-10-19 | 0.15 (UNVERIFIED) | 0.60 (UNVERIFIED) |

The OpenAI URL redirects to `developers.openai.com`, which this session did not
fetch: that row is marked `verified: false` in the artifact rather than
presented as read. The two Google rows were read from the page above and match
`apps/api/src/bangla_gpt_api/services/costs.py` exactly
(`price_table_mismatches: []` in the report, asserted by a test): the ledger's
prices and the cited prices cannot drift apart silently.

## Tokens: measured per endpoint, with the gaps named

The report drives each AI-bearing route once through the real API on a
throwaway database and reads the usage ledger the app wrote:

| Route | Ledger prompt tokens | True prompt tokens (trace) | Completion tokens | USD / 1k answers (ledger) | USD / 1k answers (true prompt) |
| --- | --- | --- | --- | --- | --- |
| `tutor.ask` | 8 | 265 | 114 | 0.173 | 0.237 |
| `tutor.chat` | 2 | 219 | 129 | 0.194 | 0.248 |
| `tutor.chat.stream` | 2 | 364 | 129 | 0.194 | 0.285 |
| `teacher/worksheet` | 4 | — | 713 | 1.071 | 1.071 |
| `teacher/rubric` | 4 | — | 241 | 0.363 | 0.363 |
| `teacher/question_paper` | 7 | — | 512 | 0.770 | 0.770 |

Two gaps are recorded instead of smoothed over:

1. **The ledger under-records the prompt for tutor routes by ~32x** (27 vs 863
   tokens across the sample). Tutor routes ledger the *question* while the
   model receives system rules + education context + evidence blocks. Budgets
   and the cost dashboard read the ledger, so today they understate the input
   side. The traced prompt is used for the projection column; fixing the ledger
   is a `routers/` change outside this workstream's ownership.
2. **Teacher routes record a summary prompt string** and emit no generation
   trace, so their prompt side is a floor, not a measurement. The artifact says
   so per route.

Completion tokens come from the mock provider (it quotes retrieved evidence),
so the answer side is a planning figure until a live run replaces it; the run
conditions in the artifact name the provider.

## Per-school monthly projection

Assumptions are planning figures in `cost_model.SCHOOL_ASSUMPTIONS` (400
students, 40 asks/student/month, 20 chat turns/student/month, 80 teacher
generations/month) and are printed with the result:

- `tutor.ask` 16,000 calls: $3.80
- `tutor.chat` 8,000 calls: $1.99
- `tutor.chat.stream` 8,000 calls: $2.28
- teacher routes 240 calls: $0.18
- **total ≈ $8.23 / month, $0.021 per student per month**

Replace the assumptions with observed usage before treating this as a budget.

## Budgets and alerts

- Per-user monthly budget already exists (`AI_MONTHLY_BUDGET_USD_PER_USER`,
  429 `ai_budget_exceeded` at the cap); the Prometheus projection alert
  (`bgpt_ai_monthly_budget_usd` vs projected month-end spend) is in
  `deploy/prometheus/alerts.yml`.
- `cost_model.budget_alert_state` mirrors that rule so it can be checked
  without Prometheus; `--budget <USD>` prints it. With no budget configured the
  gate is off, which the state reports as `budget_unset` rather than "all
  clear".
- Owner action: set `AI_MONTHLY_BUDGET_USD` for the deployment if spend is to
  be governed; an unset budget means the alert can never fire.
