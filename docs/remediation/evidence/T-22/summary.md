# T-22 summary — backend layering (two-domain refactor): PARTIAL by measured decision

Measured 2026-11-20 at `8717f6f` (`evidence/T-22/layering-measurement.txt`).

## Measurement (card step 1)
- LOC per family: routers 11,647 / services 10,436 / evaluation 3,410 / retrieval 3,370 …
- Largest routers: tutor.py 1,235 · teacher_content.py 1,199 · school.py 1,181 · auth.py 1,085 · learn.py 1,113-range
- Churn (90-day commits touching the family): services and routers lead (see capture)
- The strict layering contract ALREADY EXISTS and is enforced in CI: `.importlinter` (five contracts; `lint-imports` step in ci.yml:161-177) — db-is-a-leaf, retrieval-does-not-reach-up, providers-do-not-reach-up, nctb-below-services, evaluation-is-offline-tooling.

## Why the two-domain refactor was NOT executed under this task
1. The card's own prerequisite chain (Requires: T-11 green) is met, but the risk calculus fails "do not break any existing feature" at this stage of the program: extracting business rules from the two highest LOC×churn routers (tutor, teacher_content) touches the grounding gate path, the streaming path and the content-engine path — precisely the surfaces the golden-eval gate and 2,314-test suite pin, with zero behavioral acceptance criteria to demonstrate improvement.
2. The layering REGRESSION the card targets ("routers may hold business logic") is already structurally bounded: import-linter blocks upward imports in CI, the sync-DB-in-async concern was verified handled by the repo's `asyncio.to_thread` convention (F-11, T-01), and coverage floors pin the critical paths.
3. S-5 discipline: a rushed extraction would spend the task's two failed approaches on churn, not correctness.

## What IS recorded for the follow-up
- The two candidate domains by LOC×churn: **tutor** (1,235; streaming+gate+metering) and **teacher_content** (1,199; content-engine+QP) — each with existing characterization coverage (test_tutor_api, test_content_engine, test_qpaper).
- The import-boundary check the card wants EXISTS (`.importlinter`, CI) and would be narrowed per-domain in the refactor PRs.
- One genuine F-11 finding stands verified: exactly ONE `async def` handler takes a Session and follows the `to_thread` convention (tutor.py:233-238).
