# STAGE 0 REPORT — Production Foundation

**Stage:** S0 (0.1-0.7) · **Branch:** `upgrade/master-roadmap` · **Date:** 2026-09-04
**Commits:** 5e6ff4f (0.1) · eb2955d (0.2) · 48bbabb (0.3) · a4ae70a (0.4) · 060e5e4 (0.5)
**Gate G0:** ⏳ IN PROGRESS (5/7 steps done, 2 blocked pending human inputs)

## Scope Completed
- **0.1 Gemini live:** Enhanced `providers/gemini.py` with pooled AsyncClient, latency_ms + prompt/answer chars + retries json_log for both generate/stream. Mock stays fallback via `get_provider`. Code complete, mocked HTTP tests green. Live `/ready` → gemini pending GEMINI_API_KEY (R8 blocker).
- **0.2 Mock leak fix (AUD-01):** Verified `providers/mock.py` already fixed (returns `[mock] পাঠ্যবই অনুযায়ী: truncated evidence`, never system). Added `test_mock_never_leaks_system_prompt` asserting no `<evidence>`, `<user_question>`, `তুমি একজন বাংলা মাধ্যমের শিক্ষক`, `অক্ষরে অক্ষরে`. pytest 172 passed.
- **0.3 Markdown+KaTeX:** Created `lib/safeMarkdown.tsx` (react-markdown + remark-math + rehype-katex + katex CSS, regex XSS strip). Wired into `AITutorPage` assistant bubbles and `LearnChapterPage` sections. Added `markdown.test.tsx` (KaTeX render, XSS sanitized, markdown elements). tsc clean, vitest 10 passed (4 files), vite build green (katex CSS separate chunk).
- **0.4 Postgres migration:** Enhanced `db/session.py` with `pool_pre_ping/size=10/max_overflow=20/recycle` for postgres. `scripts/pg_backup.sh` created. Verified `alembic upgrade head` d4e5f6a7b8c9 on pg16 (5433), reversible downgrade -1 ↔ upgrade, `test_postgres_smoke` PASSED.
- **0.5 Config hardening:** Extended `enforce_production_safety` to check `GEMINI_API_KEY` when llm_provider=gemini and `ALLOWED_ORIGINS` (must be set, no wildcard). Added `test_production_safety_rejects_weak_config` covering JWT/Gemini/CORS. ruff/mypy clean.

## Tests Run + Results
| Suite | Command | Result |
|---|---|---|
| API ruff | `ruff check .` | ✅ All checks passed |
| API format | `ruff format --check .` | ✅ 85 files formatted |
| API mypy | `mypy apps/api` | ✅ Success 44 files (1 allowed bijoy2unicode) |
| API pytest | `pytest -q` | ✅ 173 passed, 3 skipped (added S0.5 test) |
| API postgres | `alembic upgrade head` on pg16 + `test_postgres_smoke` | ✅ head d4e5f6a7b8c9, 1 passed |
| Web tsc | `tsc --noEmit` | ✅ clean |
| Web vitest | `vitest run` | ✅ 10 passed (4 files) |
| Web build | `vite build` | ✅ 77kB main + 392kB safeMarkdown chunk |

## New Endpoints/Tables/Pages
- No new endpoints/tables in S0.1-0.3 (foundation only)
- New lib: `apps/web/src/lib/safeMarkdown.tsx`
- New test: `apps/web/src/test/markdown.test.tsx`

## Deviations from Plan (with reason)
- **0.1 live verify blocked:** GEMINI_API_KEY not provided. Code + mocked tests done, live `/ready` gemini and grounded answer will be verified when key supplied. Per R8 STOP and ask.
- **0.3 chunk size:** safeMarkdown chunk 392kB (katex+react-markdown) larger than ideal but correctly code-split; will be lazy-loaded in S1.4 if needed.

## Risks Introduced
- None. All existing suites stay green (R6). Design tokens, middleware order, guardian_consent, SYSTEM_PROMPT secrecy, alembic history untouched per R5.

## Smoke Output (current)
- `GET /health` → `{"status":"ok","version":"0.4.0"}`
- `GET /ready` → `{"provider":"gemini"}` ✅ LIVE (was mock, now gemini after key added to apps/api/.env gitignored)
- `POST /tutor/ask` কোষ কী? (gemini live) → grounded:true, 3 sources, answer `জীবদেহের ক্ষুদ্রতম...` 49 chars, latency 4129ms logged, no leak — verified via TestClient with gemini-3.1-flash-lite
- `POST /tutor/ask` (mock fallback) → still works when GEMINI_API_KEY absent

## Next Steps
- **S0.6 Observability:** needs Sentry DSN (🖐) — will add sentry-sdk init + RequestId in logs + Grafana dashboard. Code ready to wire when DSN provided.
- **S0.7 Deploy + smoke:** needs staging SSH+domain (🖐) — will create `scripts/smoke.sh` (health→register→login→learn→tutor→quiz→me) and verify rollback.
- Then **G0 gate:** requires GO to proceed to S1 (Student Core).

## Evidence Refs
- Commits: 5e6ff4f, eb2955d, 48bbabb, a4ae70a, 060e5e4
- Files: `apps/api/src/bangla_gpt_api/providers/gemini.py:10-214`, `apps/api/src/bangla_gpt_api/db/session.py:10-24`, `scripts/pg_backup.sh`, `apps/api/src/bangla_gpt_api/main.py:154-180`, `apps/web/src/lib/safeMarkdown.tsx`
