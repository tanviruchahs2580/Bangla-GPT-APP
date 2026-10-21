# Pedagogy guardrails — hint-first dialogues and strategy-chip evidence (A11-03/A11-04)

Date: 2026-10-19. Workstream ws1 (audit R3). Two halves, both recorded:

## 1. Hermetic evidence (runs in CI, no key)

- `tests/test_a11_dialogues.py`
  - three-turn homework dialogue: the hint-first instruction is in every
    request of the exchange (turn 1 homework paste, turn 2 "I tried" follow-up
    — the guardrail used to expire on that follow-up), the first answer is the
    scripted hint and never the full evidence text, and the study-mode step
    instruction arrives for `goal=study` turns;
  - tone: no shaming words in any pedagogy or refusal copy;
  - route-level A/B: two different strategy chips through the real chat
    endpoints store different answers, and if the first answer is regenerated
    by the grounding check, the chip's instruction survives the retry prompt
    (fixed in this change — it used to be replaced).
- `tests/test_rag2_pedagogy.py` pins the request-layer rotation and
  configuration resolution (hint-first off means off).

## 2. Live A/B (one-off, needs a key; not in CI)

Command: `.venv/Scripts/python.exe .audit/tmp/ws1_live_probe.py`
(evidence: `.audit/evidence/R3-ws1-a11-live-ab.txt`).

Method: the same grounded question ("কোষ কী?") against one live model
(`gemini-3.6-flash` — the configured model and three alternates were 503
during the window; every call retried), prompts built exactly like the tutor
builds them (strategy instruction / hint-first instruction prepended to an
`<evidence>` block + `<user_question>`), `max_output_tokens=512`.

Measured results:

| Condition | Result |
| --- | --- |
| strategy chips (steps / example / simple) | 3/3 distinct answers, each in the instructed register (step list; worked example; plain-language explanation) |
| hint-first ON on a homework-like prompt | answer is a hint plus a "have you tried / what do you think?" question; **0.00** of the evidence sentences appear verbatim |
| hint-first OFF, same prompt | model answers immediately with the full textbook sentence; **0.20** of the evidence sentences appear verbatim |

Interpretation: the chips demonstrably change behaviour (not just the
request), and the hint-first guardrail measurably withholds the full solution
on a live model. The one-shot nature and the small n are the honest limits:
this is a smoke A/B, not a statistically powered eval. A small permanent
eval (n≥20 per arm, scored for "hint vs solution") belongs in the golden
harness once a CI key exists; the prompt-copy review is flagged NEEDS NATIVE
REVIEW.

## Live evidence for the touched APIs

- A5-01 (context budget tokenizer calibration):
  `.audit/evidence/R3-ws1-a5-01-tokenizer-calibration.txt` — the shipped
  conservative counter counts 1.27x–1.58x the vendor's own token count, i.e.
  it is an upper bound (a budget that passes cannot fail upstream on size).
- A7-02 (safety sets + false-positive rate):
  `.audit/evidence/R3-ws1-a7-safety-sets.txt` — 8 required categories x 3
  languages refused with the right reason; legitimate curriculum questions
  refused: 0/30.
- A7-04 (provider terms):
  `.audit/evidence/R3-ws1-a7-04-provider-terms-2026-10-19.md` — Gemini/OpenAI
  data-use and retention excerpts with dates; the billing tier in use is an
  OWNER ACTION.
