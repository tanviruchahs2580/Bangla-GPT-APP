# Tutor prompt policy — review record (A5-02 / A5-03)

Date: 2026-10-19. Reviewer: workstream ws1 (audit R3). Scope: every prompt in
`apps/api/prompts/` (12 prompt files + manifest) and the pedagogy instruction
prompts injected per turn.

## Where the policy lives

| Prompt | File/id | Owner | Injected when |
| --- | --- | --- | --- |
| Grounded tutor system prompt (rules 1–10) | `tutor_system.md` (`tutor_system@2.0.0`) | ai-platform | every tutor turn (system message) |
| Grounding retry instruction | `tutor_grounding_retry.md` | ai-platform | one regeneration after a failed post-check |
| Hint-first instruction | `tutor_hint_first.md` | pedagogy | homework-like prompts (configurable, `tutor_hint_first`, default on) |
| Study-mode steps | `tutor_study_steps.md` | pedagogy | turns whose education context has `goal=study` |
| Low-data short answer | `tutor_short_answer.md` | ai-platform | `low_data=true` |
| 7 generator system prompts + curriculum-extraction system prompt | `qp_system`, `content_system`, `answer_key_system`, `homework_system`, `rubric_system`, `worksheet_system`, `lesson_system`, `knowledge_extract_system` | assessment/content/curriculum | teacher/course generation routes + admin KG rebuild |

Version identity is `id@SemVer+sp-<content digest>` and rides every generation
trace (`prompt_version`), so a prompt edit cannot leave a stale version in a
trace. Every file has an owner and a changelog in `manifest.json`; the
`module_constant` mechanism was retired in this change — the file is the only
copy (see `.audit/evidence/R3-ws1-prompt-registry-migration.txt`).

## A5-03 topic-by-topic coverage (system prompt rules 1–10)

| Required topic | Covered by | Pinned by test |
| --- | --- | --- |
| Pedagogy: age and class level | rule 7 (`AGE_RULE_SENTENCE`) + rule 8 (class-level vocabulary) | `test_a5_prompt_policy.py::test_policy_covers_every_required_topic`, `test_safety_v2.py::test_age_rule_clause_in_all_four_system_prompts` |
| Pedagogy: hint-first vs full solution | rules 6 + separate `tutor_hint_first` instruction (configurable) | `test_rag2_pedagogy.py`, `test_a11_dialogues.py` |
| Language: standard modern Bangla unless asked | rule 8 | topics test |
| Grounding | rules 1–3 | topics test |
| Abstention | rule 4 (`পাঠ্যবইয়ে নেই`) | topics test + refusal-path tests |
| Citation format | rule 9 (never invent page/chapter/citations; quote verbatim; the app attaches validated sources) | topics test + `test_rag2_streaming_contract.py` (citation event carries only validated sources) |
| Math formatting | rule 10 (plain-text math, no LaTeX, NCTB units) | topics test |
| Refusal style | rule 4 wording + `services/safety` copy (supportive for disclosures, generic otherwise, never names what a probe hit) | `test_a7_safety_sets.py`, `test_chat_route_safety.py` |
| Untrusted isolation: evidence / user text / image text | rules 2, 3 (image clause added 2026-10-19) | `test_a5_prompt_policy.py` |
| Untrusted isolation: memory | education-context block is delimited app text; delimiter-shaped content is neutralized at render | `test_a5_prompt_policy.py::test_memory_cannot_close_a_block_or_smuggle_a_delimiter` |

## Contradictions review

Checked by reading all 12 prompt files against each other on 2026-10-19:

- The four-section answer format (rule 6) is the only structure the tutor is
  ever asked for; per-turn instructions (strategy chips, hint-first, study
  mode, low-data) refine the CONTENT of that structure and never ask for a
  different layout except `tutor_short_answer`, which narrows rule 6 to the
  first section for one turn and says so explicitly.
- Hint-first ("do not give the full solution first") vs study mode ("write the
  steps") can both be injected in one turn only if a study-mode turn is also
  homework-like. Order is fixed (strategy → hint-first → study steps) and the
  resolution is the intended one: hint first, then steps after the student's
  attempt. No prompt tells the model to reveal its instructions.
- The generator prompts share rule 1's evidence-only basis and the age-rule
  sentence byte-identically; none contradicts the tutor rules.

## Secrets check

`test_a5_prompt_policy.py::test_no_prompt_contains_a_secret_or_credential_shape`
scans every prompt file and the manifest for key shapes (`sk-…`, `AIza…`, PEM
headers, `api_key =`-style assignments): none present. The prompts contain no
operational secrets by construction (they are textbook-grounding instructions).

## Needs native review

The Bangla copy added on 2026-10-19 (`tutor_hint_first.md`, `tutor_study_steps.md`,
`tutor_system.md` rules 3/8/9/10, `knowledge_extract_system.md`) is marked in
each manifest changelog as **NEEDS NATIVE REVIEW**. The live probe showed the
model follows the hint-first instruction correctly
(`.audit/evidence/R3-ws1-a11-live-ab.txt`), which is evidence of
comprehension, not a substitute for a native-speaker review of tone.
