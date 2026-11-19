# T-27 — LLM application security trust boundaries (map + pinning tests)

Verified 2026-11-20 at `6b62442` (branch `remediation/0.2.0`). Every boundary below names the code that implements the defense AND the test that pins it. No new defect found; no fix needed — this task's value is the map.

| # | Boundary | Defense (code) | Pinning tests |
|---|---|---|---|
| 1 | User input → prompt | question wrapped as untrusted data; system prompt rule (Bangla) declares `<evidence>`/`<user_question>` content quoted-data-never-instructions (`services/tutor.py:188-221`) | `test_injection_guard.py::test_system_prompt_contains_injection_rule`; `test_rag_001_prompt_trust_boundary.py` |
| 2 | Retrieved corpus text → prompt | chunks wrapped in `<evidence>` delimiters; `sanitize_evidence` neutralizes delimiter escapes (`tutor.py:263-272`, applied at :320-321) | `test_injection_guard.py::test_sanitize_neutralizes_delimiter_escape`, `::test_poisoned_chunk_cannot_break_out_of_evidence_block`, `::test_build_evidence_prompt_wraps_each_chunk` |
| 2b | Generator form fields → prompt | quiz-explain/education fields bounded and delimiter-sanitized before prompt assembly | `test_rag_001_prompt_trust_boundary.py::test_poisoned_quiz_explain_fields_cannot_forge_prompt_delimiters`, `::test_quiz_option_text_is_bounded_before_it_reaches_the_prompt`, `::test_education_context_fields_are_bounded_before_they_reach_the_prompt` |
| 3 | Model output → web UI | `safeMarkdown` sanitized rendering (no raw HTML/script injection; links hardened) | `apps/web/src/test/markdown.test.tsx`, `markdownLive.test.tsx`, `safeHref.test.ts` |
| 4 | Model output → API consumer | output screened through the same `screen_question` (`tutor.py:1272`, block logs :1573/:2064, streaming buffer covered) | `tests/test_safety_must_sets.py` (output-direction cases), safety suites |
| 5 | Model output → logs | secret-safe logging gate (`logging_config.set_secret_logging_allowed`, off in production — main.py:745) | `test_w2_log_redaction.py`, `test_qa_sentry_scrub.py`, `test_qa_control_chars.py` |
| 6 | System prompts/settings/keys → API responses or errors | keys never in responses (settings carried server-side); error envelope is coded messages (`_error_contract.py`); prompt-leak scan over EVERY red-team response (`evaluation/cli.py:_LEAK_MARKERS`) | red-team gate `--redteam` (36/36 PASS at `6b62442`); `test_qa_boot_guards` |
| 7 | Personal data → providers | `redact_pii` (phone/email/NID, metered per kind) before egress (`services/pii.py:44-72`) | `test_pii.py` (17 mobile + email/NID cases) |
| 8 | Per-user consumption bounds | per-user monthly budget gate on EVERY generation route (`require_ai_budget` → `check_ai_budget`, deps.py:374-388) + production boot refusal when cap unset (`main.py _validate_ai_budget`) | `test_budget_reserve.py`, `test_teacher_ai_budget.py`, `test_production_guards.py` |
| 9 | Cache isolation (side channel) | content caches keyed by user id (`summary:{user.id}:{date}`, `routers/learn.py:884`) — strictly finer than tenant; a user can only ever generate their own key. Tutor answers are NOT cached (each ask metered). Rate-limit keys scoped per user/ip (config.py:422-431) | `test_cache_v2.py` (shared-cache suite runs against real Redis in CI), tenancy suites |
| 10 | Generation kill switch | `ai_generation_enabled=False` refuses generation before the budget/ledger/provider (`tutor.py` F-031) | `test_qa_kill_switch.py` |

## Result

All ten boundaries have a code-level defense AND a pinning test on this tree. The T-27 card's acceptance ("a test per boundary") is met by the existing suites; this map is the evidence index. No boundary was found undefended; no fix landed under this task.
