# Bangla-GPT agentic upgrade — master plan (2026-11-15, milestone 1)

Authority: the 2026-11-15 Enterprise RAG & Agentic Architecture
Assessment (38/100 across 12 capabilities, 18 steps, 10 phases), executed
under the owner's standing authorization with SWE SOP and the repo's own
gates. This document reconciles the assessment with the repo as it
actually is at **v0.13.0** (the assessment read 0.12.0/2735c5c; v0.13.0
has since shipped the staging generation, prompt v2 and the pgvector CI
fix — several assessment findings are already partially addressed).

## 0. Assessment verification (claims vs repo, checked 2026-11-15)

| Assessment claim | Verified |
|---|---|
| README says 0.10.0 while code is newer | **TRUE — drift confirmed**; fixed this wave (README now mirrors pyproject 0.13.0) |
| All referenced canonical files exist (`services/context.py`, `knowledge.py`, `jobs.py`, `router.py`, `pii.py`, `docs/rag/*`, V4 review, V5 benchmark protocol) | TRUE |
| 427-item golden set measures the bundled sample, not the real corpus | TRUE (recorded in V5.5 `staging-retrieval-report.md`) |
| No human-reviewed labels; neural/cross-encoder defaults blocked | TRUE (`BLOCKED_OWNER_DATA`) |
| Production is SQLite; pgvector not activated in production | TRUE; **staging lane now real** (V5.5: 1598-chunk generation active) |
| No MCP / no multi-agent swarm / no three-tier memory | TRUE — and the assessment itself says NOT to build these first |

The 38/100 score is a feature-fit score against an agentic-platform
blueprint, not a quality verdict; the repo's strengths (grounding gate,
safety, PII, tenancy, eval CI) are real and acknowledged by the
assessment.

## 1. Sequencing decision (why this milestone)

The assessment's own verdict: do NOT start with Multi-Agent, Neo4j, MCP
or semantic cache; the first engineering milestone is **Evaluation & Data
Foundation + Dynamic Context Assembler + Production pgvector readiness**
(§11). That is exactly what is executable now without owner-blocked
inputs:

| Milestone-1 item | Assessment step | Status |
|---|---|---|
| Baseline/feature-lock refresh + README drift fix | Step 1 | this wave |
| False-refusal / false-answer explicit reporting | Step 4 | this wave |
| `ContextBudgetManager` (unified token budget) | Step 6 | this wave |
| pgvector readiness: staging proven, runbook + restore drill | Step 5 (readiness part) | this wave |
| Corpus rights audit + Class 6 ingestion | Step 2 | **BLOCKED_SOURCE_OR_RIGHTS** (approved `.docx` pending) |
| Human-reviewed benchmark dataset | Step 3 | **BLOCKED_OWNER_DATA** (educator labels) |
| Neural embedding / cross-encoder activation | Steps 7–8 | **BLOCKED_OWNER_DATA** (needs Step 3) |
| Production PostgreSQL host + migration | Step 5 (provisioning) | **BLOCKED_INFRA** (owner host decision) |
| Document GraphRAG (Neo4j) | Step 9 | later phase, after Steps 2–4 |
| Self-correcting RAG controller | Step 10 | later phase |
| LangGraph durable workflows | Step 12 | later phase (AiJob/ARQ preserved) |
| MCP server/client | Step 13 | later phase (after security gateway) |
| Inter-agent security & PII proxy | Step 14 | later phase (PII boundary exists) |
| Three-tier memory | Step 15 | later phase |
| Typed multi-agent swarm | Step 16 | later phase |
| Semantic cache & routing | Step 17 | later phase |
| Cost/observability extension | Step 18 | partial (ai_usage exists); extends with each phase |
| Trajectory evaluation CI | Phase 9 | groundwork with each phase; full gate before multi-agent |
| Public architecture teardown | Phase 10 | last, after implementation |

## 2. Milestone-1 design decisions

**D1 — README version drift.** The README's own rule ("the single source
of truth is pyproject") was violated by the README line itself; fixed by
pointing the line at 0.13.0. No other file may carry a version.

**D2 — false-refusal / false-answer reporting (additive, gate-neutral).**
`evaluation/cli.py` already computes the underlying counts
(`answered_true/true_total`, `refused_false/false_total`). The report now
prints the two derived rates explicitly (`false_refusal_rate = 1 −
coverage_true`, `false_answer_rate = 1 − coverage_false`) with Wilson
intervals. Nothing is added to `as_dict()` (the regression gate's
contract stays byte-stable); no baseline moves.

**D3 — `ContextBudgetManager` (planning model, additive).**
`services/context_budget.py`: window/output-reserve/safety-margin from
settings; token counting via the repo's Bangla-block-aware tokenizer
(`retrieval.hybrid.tokenize`) — the honest local estimator (provider
tokenizers differ; documented as an estimate). `plan()` measures each
slot, always keeps system+question, prunes oldest history first with
structured drop reasons, and validates the final total. Router
integration: `_chat_history` gains a token cap ON TOP of the existing
message-count cap; with defaults the char cap binds first, so existing
traffic is byte-identical (feature lock holds). One code path for
streaming and non-streaming (the manager is pure).

**D4 — pgvector readiness (no production change).** The staging lane
already proves the architecture with a real 1598-chunk generation
(V5.5). This wave adds the readiness record: what exists, what a
production activation requires (host, migration rehearsal, canary
approval), and the restore drill status. Production serving stays
SQLite/hybrid.

## 3. Gates for this wave

Existing gates only (no threshold moves): full API suite, ruff/format,
mypy (CI-pinned), eval CLI + 24Q + redteam, web suite, e2e smoke,
alembic chain, changelog, native-review sheet. New tests for D2/D3 ship
in the same change.

## 4. What this wave does NOT do

No Neo4j, no MCP, no agents, no semantic cache, no memory tiers, no
serving-default change, no baseline regeneration, no gate weakening, no
schema change. Blocked items are recorded, not simulated.
