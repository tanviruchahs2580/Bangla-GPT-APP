# RAG V5.5 — tutor efficiency wave plan (2026-11-15)

Owner authorization on record: full permission for the remaining tasks,
SWE SOP governing every step, no existing feature may break. Production
serving default stays unchanged unless a change passes every gate.

## 1. Assessment of the v0.12.0 report (honest)

**Landed and verified.** Generation registry + atomic activation
(migration `c7d9e1f3a5b7`, both engines), `PgVectorStore` (exact cosine,
filters, validation, isolation, retirement), `NeuralEmbedder` (explicit,
non-default, boot-guarded), evidence-verification off/shadow/enforce,
9 design docs, full CI/live/APK pipeline green.

**What the slice did not do (this wave's targets):**

1. No index generation was ever **built from the real corpus** — the V5
   tests exercise the primitives with synthetic fixtures; the pipeline has
   never ingested the actual 847 chunks end to end.
2. The serving path does not consume pgvector, and no staging Postgres
   exists on this machine to prove the lane outside CI.
3. The tutor prompt (`tutor-prompt-v1`) has never been reviewed against
   modern tutoring-prompt practice; no persona/quality review exists.
4. The tutor+RAG loop has never been exercised as a user against the live
   API with a recorded ask matrix (grounded / Banglish / refusal / safety).
5. No in-repo RAG reference base; the design decisions cite nothing.

**Blocked gates that remain blocked (owner-level, not lifted by blanket
permission):** neural model selection needs human-reviewed labels
(`BLOCKED_OWNER_DATA`); production pgvector serving needs a Postgres host
(`BLOCKED_INFRA` — production is SQLite); Class 6 ingestion needs the
approved `.docx` (`BLOCKED_SOURCE_OR_RIGHTS`). This wave does staging
work only; production serving stays `hybrid` on SQLite.

## 2. Goals / non-goals

**Goals.** (a) Download authoritative RAG references into the repo with
provenance. (b) Write the complete RAG system design (modern-stack
mapping, live/dormant/blocked gate map). (c) Stand up a local pgvector
staging lane, implement the resumable build CLI, build + validate +
activate a **real generation** from the 847-chunk corpus with the default
HashingEmbedder, and record an honest retrieval report. (d) Review the
tutor design and personality; land prompt changes only behind the eval
gate. (e) Exercise tutor+RAG end to end (live ask matrix). (f) Run every
gate; ship v0.13.0 through the full pipeline.

**Non-goals.** No neural model activation, no baseline regeneration, no
grounding-gate/top-k change, no new corpus sources, no schema change
beyond what V5 already shipped, no CSS/state-library introduction.

## 3. Approaches considered

- **A. Docs-only wave** — safe but leaves the pipeline unexercised; the
  audit's core finding (never built against real data) stands. Rejected.
- **B. Wire pgvector into the serving path now** — blocked: production is
  SQLite; a serving change with no host to run it on is dead code.
  Rejected for this wave; the design doc marks it as the next wave.
- **C. Staging-first vertical proof (chosen)** — build the real generation
  on a local pgvector staging container, measure retrieval honestly, keep
  serving untouched. Proves the architecture with real data at zero risk
  to the serving contract.

## 4. Step-by-step execution guide

| Step | Work | Gate |
|---|---|---|
| B | Download 5–6 authoritative RAG references → `docs/references/rag/` with URL + date + why-it-matters | none (docs) |
| C | `system-design.md`: ingest→chunk→embed→index→retrieve→rerank→verify→generate→cite→eval→observe; modern-stack mapping | none (docs) |
| D1 | Staging container `bgpt-pgvector-staging` (pgvector/pgvector:pg16, port 5433, namespaced volume) | port-isolation rule |
| D2 | `test_pgvector_store.py` green against staging (`BGPT_PGVECTOR_TEST_URL`) | real-extension proof |
| D3 | `apps/api/scripts/build_index_generation.py` (TDD): digest → create_building → batch embed+upsert → validate → mark_validated → optional `--activate` (staging only; refuses SQLite) | new tests + ruff/mypy |
| D4 | Build the real generation (847 chunks, hash-ngram-local, 384-dim); validate; activate in staging | store.validate clean |
| D5 | Retrieval report: dense-only vs BM25 vs hybrid on heading-probe + assistant-authored Bangla queries; labelled PROVISIONAL (not gate-grade) | honesty rules |
| E1 | `tutor-personality-review.md` against modern tutoring practice | docs |
| E2 | Live ask matrix (grounded / Banglish / out-of-corpus / safety) through the production API as the demo student | as-a-user |
| E3 | Prompt v2 only if a high-confidence improvement survives the eval gate + 24Q gate + redteam; else v1 stands with the review recorded | eval gate |
| F | Full local gate set + eval CLI + 24Q + redteam + web suite + e2e smoke + alembic check | §12 gates |
| G | PR → CI → merge → tag v0.13.0 → Release & Deploy + Android → live swap (snapshot→restore→swap→upgrade→smoke) → APK → final report | §14 pre-authorized |

## 5. Success criteria

Every gate green; a real generation active in staging with clean
validation; the retrieval report published with honest labels; the tutor
review recorded; the ask matrix demonstrates grounded answers, honest
refusals and the safety envelope on the live system; v0.13.0 live with
the APK delivered. Any step that cannot meet its gate is reported as
not-done, never papered over.
