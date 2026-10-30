# AI system card — Bangla GPT tutor

Current state at BASE_SHA `7e8525e2` (2026-10-29). Every statement cites a
repository `file:line` or an audit evidence id from `.qa-work/`; what could not
be verified is listed in section 8. Scope: the LLM tutor and the teacher-facing
generators. Non-AI features (quizzes, progress, dashboards) are documented in
`docs/API.md` and `docs/architecture.md`.

## 1. Purpose

- Curriculum-grounded Bangla tutor: a student asks a question and receives an
  answer built only from retrieved NCTB curriculum passages, in Bangla
  (`README.md:3`; prompt rules 1 and 4 in `services/tutor.py:104-122`).
- Teacher tools generate worksheets, question papers and lesson plans from the
  same corpus (`config.py:257-263`; generators under `services/generators/`).
- The answer path is: safety screen, retrieval, coverage gate, provider call,
  server-side source list, optional heuristic citation check
  (`services/tutor.py:272-388`; `services/safety.py:120-135`).

## 2. Intended users and ages

- Five roles: student, teacher, parent, school admin, platform admin
  (`README.md:5-6`; `routers/`).
- Students are school-age minors by design. Registration for `role=student` requires a class level (1-12, enforced at `db/models.py:98-99` and `schemas.py:52`) and recorded guardian consent with version, timestamp and IP (`routers/auth.py:154-172,205-212`).
- No date-of-birth field exists, so no exact age is stored (`.qa-work/audit/PRIV/report.md`, inventory note). Corpus and evaluation coverage is secondary level only; class metadata is replicated to classes 6-10 (`.qa-work/audit/RAG/report.md` F-RAG-4; ARCH notes tests over classes 6-10 only).
- Teachers and parents use adjacent surfaces; teacher AI generation is teacher-facing and rate-limited per user (`config.py:257-267`).

## 3. Out-of-scope uses

- Not a sole source of truth and not for exam reliance: "do not rely on it as the sole source of truth" (`apps/web/src/pages/LegalPage.tsx:71-76`).
- Does not answer outside the corpus: the prompt requires an explicit not-in-textbook statement (rule 4, `services/tutor.py:104-122`) and a coverage gate refuses low-evidence questions (`services/tutor.py:272-388`).
- Not a crisis or medical service: self-harm text receives supportive copy that points to a helpline rather than advice (`services/safety.py:14-18`); the helpline number itself is unverified (section 8).
- Not permitted in production with the mock provider (`main.py:324-345`; probe `.qa-work/evidence/E-AIG-06/`).
- Not an image-reading guarantee: the mock provider answers with an explicit cannot-see-images refusal (`routers/tutor.py:624,735`).

## 4. Models and providers

| Provider | Default model | Notes |
|---|---|---|
| `mock` | none (deterministic local stub) | default `LLM_PROVIDER=mock` (`config.py:64`); refused at production boot without explicit opt-in (`main.py:324-345`) |
| `gemini` | `gemini-3.1-flash-lite` (`config.py:69`) | vision via inline image data (`providers/gemini.py:126-141`); optional fast lane `GEMINI_FAST_MODEL` (`config.py:72`; `providers/__init__.py:43-62`) |
| `openai` | `gpt-4o-mini` (`config.py:75`) | optional `OPENAI_BASE_URL` (`providers/openai.py:312-330`) |

- Provider selection is a config value resolved by a factory
  (`providers/__init__.py:20-35`); an unknown provider name refuses to boot.
- Optional fallback provider plus circuit breaker (`providers/__init__.py:77-125`; ARCH failure-mode table in `.qa-work/audit/ARCH/report.md`).
- Per-call bounds: 30 s timeout, 2 retries, 2048 output tokens (`config.py:81-86`); generation size is additionally capped in the Gemini client (`providers/gemini.py:138`).
- Tutor requests are rate-limited to 30/minute per user (`config.py:229`). No per-user spend ceiling by default (F-LLM-4, `.qa-work/audit/LLM/report.md`).

## 5. Data sources

- Corpus: official NCTB curriculum documents (শিক্ষাক্রম), acquired from nctb.gov.bd-hosted links; the site exposes curriculum documents, not student textbooks, as static downloads (`docs/NCTB_DATA_PIPELINE.md:18-22`).
- Provenance is recorded per artifact (URL, sha256, retrieved-at) in `data/nctb/manifests/acquisition_manifest.jsonl`; each row carries `license_notes`: "Official NCTB public download; copyright NCTB/Government of Bangladesh. Use restricted to curriculum-grounded tutoring research/product."
- Rights: the launch checklist still lists "Real NCTB corpus ingestion rights confirmed" as unchecked (`docs/LAUNCH_READINESS_CHECKLIST.md:53`; F-LEGAL-1). Legal review required; no permission document is in the repository.
- Corpus artifacts are not reproducible from a clean checkout (F-RAG-16); class detection is undetected and chapters are empty on most index chunks (F-RAG-4), so metadata filters are weaker than the docs suggest.
- User data sent to the provider: the redacted question, retrieved passages and limited conversation history, with pasted phone/email/NID patterns stripped first (`services/pii.py:29`; `services/tutor.py:160-198`). Chat images are validated and metadata-stripped before forwarding (`routers/common.py:242-300`; `providers/image_safety.py:98-152`). No user upload enters the retrieval index (audit RAG-17; OCR adapter permission-gated and unwired, `nctb/ocr_ingester.py:30-35`).

## 6. Evaluation results — baseline-measured 2026-10-29 (mock provider)

From the repository's own eval commands (`.qa-work/audit/RAG/report.md:26-31`;
RAG-20, LLM-03, evidence E-RAG-20; sample corpus, mock provider):

| Metric | Result |
|---|---|
| Golden v2 gate (grounded_rate / coverage_true / coverage_false) | 1.00 / 1.00 / 1.00 — GATE PASS |
| Faithfulness (local_overlap) | 0.8549 |
| Grammar | 0.9878 |
| Red-team probes refused without leak markers | 23 / 23 |
| Self-sentence retrieval recall@1 / @5 | 0.98 / 0.98 |
| Chapter-title retrieval recall@1 / @5 | 0.675 / 0.95 |
| Adversarial (out-of-corpus) refusal rate | 0.25 |
| Index build time; search p50 / p95 | 59.4 s; 357.6 ms / 851.7 ms |

- These are hermetic, mock-provider measurements on the sample corpus; they are not live-model quality numbers and not a production baseline.
- The repository reports no confidence intervals anywhere (audit RAG-22). The one interval available is audit-computed: out-of-corpus false-answer rate 3/4 = 0.75, Wilson 95% CI [0.30, 0.95] (n = 4; `.qa-work/audit/RAG/report.md` section 5).
- Evaluation questions are partly generated from indexed text (511/634 stems found verbatim; F-RAG-6), which limits what the gate proves.

## 7. Known limitations (each with its open finding)

- Coverage gate can serve out-of-corpus questions (3/4 false answers; F-RAG-2, S1) and `verify_citation` passes fabricated content (F-RAG-7).
- Tutor answers are not output-screened, only teacher-path outputs are (F-LLM-2); no hate or bullying category exists, and Romanized variants exist only for self-harm (F-LLM-1); text inside an uploaded image is not declared untrusted data (F-LLM-3).
- Confidence is a heuristic blend shown as a percentage without calibration (`services/safety.py:223-241`; F-LLM-7).
- No fairness or bias probes exist (AIG-04, F-LLM-13); no answer-side Bangla-script guard (F-LLM-8).
- No runtime kill switch; the config-only disable also removes the retrieval index (`/search` 503) instead of degrading to retrieval-only (F-LLM-14; evidence `.qa-work/evidence/E-AIG-06/`).
- The index is rebuilt in-process at boot (`initialize/dependencies.py:240-311`).

## 8. Not verified

- Live-model behaviour of any kind: answer quality, prompt-injection resistance, image/vision behaviour, structured-output reliability, latency. The audit ran `LLM_PROVIDER=mock` only; the real-model eval leg is deliberately non-blocking (`.github/workflows/eval-gate.yml:65-71`). Treat as UNVERIFIED-LIVE.
- The helpline numbers shown in self-harm refusals are no longer an open risk: the copy carries only services the Directorate General of Health Services publishes itself (16263 health call centre, 999 emergency; source URLs and retrieval date in the `SAFE_HELPLINES` comment of `services/safety.py`, retrieved 2026-10-29). `apps/api/tests/test_qa_helpline_policy.py` fails any edit that adds an unlisted number. An owner who obtains a verified mental-health-specific line extends `SAFE_HELPLINES` with its source first (F-001, closed by substitution).
- NCTB usage rights (F-LEGAL-1, owner decision; legal review required).
- Whether the deployed environment sets a spend budget (F-LLM-4) or Sentry scrubbing (F-PRIV-7); deployment configuration is not in the repository.

## 9. Update policy

- Re-run the eval gate and the red-team suite when the system prompt, provider, model id or corpus changes (`.venv/Scripts/python.exe -m bangla_gpt_api.evaluation.cli`, from `apps/api`); update this card in the same change when any number or scope statement moves.
- Review this card together with `docs/ai/risk-register.md` and `docs/ai/incident-response.md`; the register tracks each limitation's mitigation status.
- Owner of this document: engineering lead. Findings referenced here are tracked in `.qa-work/findings.csv` until the QA run closes.
