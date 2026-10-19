# Change management: model, prompt, index and embedding changes

Scope: anything that can change what a student sees without a code review of a
function body — a model id, a prompt file, a retrieval index build, an
embedding model, retrieval parameters. Owner: ai-platform. Related findings:
AUD-A2-13 (A10-03), AUD-A2-06 (A5-02), AUD-A2-08 (A6-06).

## 1. Versioned artefacts (what is versioned and how it is visible)

| Artefact | Version identity | Where it appears |
|---|---|---|
| Prompt | `prompts/manifest.json` `version` + content digest -> `id@version+sp-<digest>` | generation traces (`prompt_version`), `tests/test_rag2_prompt_registry.py` |
| Model | provider config (`GEMINI_MODEL`, `OPENAI_MODEL`, fast model) | `ai_call` log line (`model`), token/cost counters, per-model quality board |
| Retrieval index | corpus fingerprint (sha256 of chunk ids) or an explicit `index_version` | `index_version` on retrieval/generation traces, `/status` components, cache keys |
| Embedding model | `EMBEDDING_MODEL` (empty = local hash-ngram embedder) | boot log (`rag_index_built`), retrieval evaluation artifacts |
| Evaluation baseline | `apps/api/eval/*.json` with `dataset_hash`/`test_split_hash` | eval gate output; the gate compares against the frozen baseline |

## 2. Procedure (every change follows all seven steps)

1. **Classify.** Prompt / model / index / embedding / retrieval parameter. A
   model or embedding change is never "just config": it needs the same evidence
   as a code change.
2. **Change on a branch, with the version bumped in the same commit.** Prompt:
   file + manifest version + changelog entry in one commit. Index: new
   immutable index artifact name (`index_version`), never an in-place rebuild
   that keeps the old name.
3. **Evaluation gate before rollout.** Run the evaluation on the frozen
   dev split (`python -m bangla_gpt_api.evaluation.cli`, `make rag-eval` or the
   golden-eval CI job). The change ships only if the primary metrics are
   inside the pre-registered tolerance (`apps/api/eval/thresholds_v1.json`).
   A metric drop beyond tolerance means the change is not ready — the
   threshold is never lowered in the same change.
4. **Shadow or canary.** For a model or prompt change: serve the new version
   to a small share (a school, a class, or an internal account) with the
   version visible in traces, and compare refusal rate, citation-check
   failures, latency and cost against the running version. The admin
   AI-quality board (`/admin/ai-quality`) is the review surface; it must show
   the prompt/model versions (see "Wiring" below).
5. **Rollout.** Production change = config/registry change + restart, so the
   rollback is the same artefact the previous version was. Record the change
   in this file's exercise log (below) with the versions before and after.
6. **Rollback.** Prompt: revert the file and the manifest to the previous
   version (the previous text is in git, and the digest identifies it).
   Model: revert the config value. Index: point the loader back at the
   previous immutable artifact name; the cache key space follows the index
   version, so no stale passage can be served from the old index.
   Embedding: reverting requires the old artifact too — that is why an
   embedding change always ships as a NEW index with a side-by-side
   comparison (step 3) rather than an in-place re-embed.
7. **Record.** Append to the exercise log with date, artefact, versions and
   evidence (test/eval command output).

## 3. Wiring status (honest, 2026-10-19)

* Prompt versions ride generation traces (`services/tutor.py`).
* Index version rides retrieval/generation traces and the retrieval cache key.
* Model ids ride every `ai_call` line and the token/cost counters.
* The admin AI-quality board exposes per-model and per-prompt aggregates; the
  `prompt_version` dimension is the follow-up wiring named in
  `.audit/handoffs/api-rag2.md` (the endpoint itself lives in
  `routers/admin.py`, outside this change's ownership).

## 4. Exercise log

| Date | Artefact | Before | After | Evidence |
|---|---|---|---|---|
| 2026-10-19 | prompt `tutor_hint_first` (new prompt introducing hint-first pedagogy, A11-03) | — (absent) | `tutor_hint_first@1.0.1+sp-32d9d46ed6fa` | registry + pedagogy tests (28 passed), trace-visible version; E-R2-rag2-017 |
| 2026-10-19 | prompt `tutor_system` (migration of an inline constant into the registry, no text change) | `sp-54f3e1b19ebb` (inline constant) | `tutor_system@1.0.1+sp-54f3e1b19ebb` | digest unchanged by construction and pinned by `test_system_prompt_text_did_not_change_in_the_migration`; E-R2-rag2-001 vs E-R2-rag2-020 |
| 2026-10-19 | evidence-context label placement (part of the A5-01 context-budget change) | label INSIDE `<evidence>` -> model quoted it -> `faithfulness_avg` 0.7603 (gate FAIL, 9.44pp) | label moved BEFORE the block -> `faithfulness_avg` 0.8553 (gate PASS) | E-R2-rag2-018 (before) and E-R2-rag2-019 (after) |

Rows 1 and 3 are a real exercise of steps 1–3, 6 and 7 on this tree: the
prompt was added as a versioned file, its version bumped once during review
(1.0.0 -> 1.0.1 copy clarification, NEEDS NATIVE REVIEW), the trace-visible
version captured; then the evaluation gate caught a genuine regression caused
by the new context labels and the artefact was fixed and re-gated (rollback was
not needed because the fix was the correct form of the same change). Steps 4–5
(canary, gradual rollout) need a deployment and a live model key; they are
documented here and remain owner-executed, not claimed.
