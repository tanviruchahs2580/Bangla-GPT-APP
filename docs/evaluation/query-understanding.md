# Lexical analysis, query understanding and the abstention gate (A4-03, A4-04, A4-06)

Commands (from `apps/api`):

```bash
python apps/api/scripts/evaluate_nctb_retrieval.py        # lexicon audit + Banglish subset, real corpus
python -m bangla_gpt_api.evaluation.cli          # the gate itself, hermetic
```

Artifacts: `data/nctb/retrieval_eval.json` (`lexicon_audit`,
`banglish_subset`, `gate_threshold_calibration`, `serve_stats`). Code:
`retrieval/hybrid.py` (stemmer, stop-words, expansions, roman lane),
`retrieval/query_analysis.py`, `retrieval/langid.py`, `services/tutor.py`
(`_gate`, `_coverage_details`, `_conversation_retrieval_query`). Tests:
`tests/test_query_lanes.py`, `tests/test_query_analysis.py`,
`tests/test_eval3_retrieval_ops.py`.

## Lexical analysis provenance (A4-03)

| Piece | Where | Provenance |
| --- | --- | --- |
| Tokenizer | `retrieval/hybrid.py` (`tokenize`) | character-class rules; Bengali+ASCII digits fold to one canonical form (`_DIGIT_FOLD`), zero-width characters stripped at the AI boundary |
| Light stemmer | `retrieval/hybrid.py` (`light_stem`) | suffix-stripping curated by inflection family (plural/case/verb endings), minimum stem length 3 |
| Stop-words | `retrieval/query_analysis.py` (`BANGLA_STOP_WORDS`, `ROMAN_STOP_WORDS`) | curated by *grammatical function* (copulas, conjunctions, postpositions, pronouns, interrogatives), never by frequency — a frequency list on a 78-chunk corpus absorbs content words ("কোষ" is among the most frequent tokens in the book). Stop-words are removed from coverage accounting only; they still participate in BM25 |
| Query expansions | `retrieval/hybrid.py` (`QUERY_EXPANSIONS`) | curated synonym/topic map; coverage audited per build in `lexicon_audit` |
| Roman/Banglish lane | `retrieval/transliteration.py` + `retrieval/vocabulary.py` (`match_roman`) | phonetic skeleton + trigram match against the corpus vocabulary; the roman lane is a *retrieval* lane, not a rewrite |
| Spelling variants | `CorpusVocabulary.match_spelling` | trigram similarity floor 0.6 (pinned by tests) |

Unit tests on inflections, compounds and verb forms live in
`tests/test_query_lanes.py` and `tests/test_query_analysis.py` (transliteration
round trips, roman lane hits, stop-word behaviour, spelling repair, coverage
weights). The curated lists carry no external dictionary citation; the
provenance that can be stated is the linguistic rule per entry and the
in-source comments — this document does not upgrade that into a citation.

### Over-stemming collision rate (measured, not estimated)

`lexicon_audit` in `data/nctb/retrieval_eval.json` (real corpus, 1 565 served
chunks, 2026-10-20 rebuild):

| Measurement | Value |
| --- | --- |
| stem groups | 6 345 |
| collision groups (one stem, >1 surface form) | 490 |
| collision ratio | **0.0772** |
| expansion targets curated | 42 distinct targets |
| expansion targets absent from the served corpus | **25 of 42** (listed by term in the artifact) |

The collision ratio rose from the audit's earlier 4.4% (425 / 9 690) through
0.0727 (1 390 chunks, 2026-10-19) to 0.0772 today: the numerator is similar
while the denominator shrank from 2 504 chunks (pre-dedupe) to the served
1 390 then 1 565, so the same stemming behaviour reads worse per chunk. Both numbers are artifacts of their corpus, which
is why the measurement is regenerated with every retrieval change rather than
quoted from this page. Collisions are listed with examples in the artifact
(e.g. অংশ → অংশ / অংশের / অংশটি / অংশগুলো) — they are the light stemmer's
expected behaviour (number/case/plural forms sharing a stem), not errors.

### Expansion topic-drift check

The audit's concern was that curated expansions could pull retrieval toward a
different topic. The check that runs per build is `expansion_targets_absent_*` in
`lexicon_audit`: an expansion whose target does not occur anywhere in the
served corpus cannot help retrieval and is drift — or a corpus gap. On
2026-10-19, **26 of 42 curated targets are absent** from the served corpus
(অক্সিজেন, অতিভুজ, আকর্ষণ, ওহম, ক্লোরোফিল, চুম্বক, দর্পণ, নিউক্লিয়াস, … —
the full list is in the artifact). That is the honest drift finding: the
curated map was written against the secondary science syllabus while the
served corpus is the curriculum documents, which do not carry every topic
word. An absent target is inert (it expands to nothing), so the cost is a
missed expansion rather than a wrong one — but the map needs a review pass
against the served corpus, and this count is the trigger.

## Query understanding (A4-04)

| Capability | Implementation | Evidence |
| --- | --- | --- |
| Script/language detection (Bangla, English, romanised Bangla, mixed) | `retrieval/langid.py` (`script_of`, `is_banglish`, `classify_query`) | unit tests in `tests/test_a1_docs_and_ledger.py` (explicit script detection, Banglish does not claim plain English) + the per-family labels in `banglish_subset` |
| Banglish normalization measured on a dedicated subset | family D = family A romanised, same chunks | `banglish_subset`: n=100 pairs; recall@5 **0.97 Bangla → 0.86 Banglish**; paired delta **−0.11**, CI95 **[−0.18, −0.05]** — the roman lane's cost is measured and resolvable. Detector labels: family A 99 bangla / 1 mixed; family D 25 banglish / 75 mixed |
| Spelling variants | `match_spelling` trigram lane | `tests/test_query_lanes.py` |
| Numeral normalization | Bengali digits fold to ASCII in `tokenize` (`_DIGIT_FOLD`), so "১২৩" and "123" are one token | unit test on `tokenize` in `tests/test_query_lanes.py` |
| Unit normalization | **not implemented** | recorded as the residual: "৩ কিলোমিটার" and "3 km" remain distinct token sequences. This is a real gap for physics/maths questions; it touches the retrieval tokenizer (`retrieval/hybrid.py`, outside this document's change set) and is listed as the owner-facing residual below |
| Follow-up condensation (pronoun/ellipsis) | `TutorService._conversation_retrieval_query`: a follow-up with ≤1 content term inherits the prior user turn's content terms; ≥2 terms is never rewritten | `tests/test_rag_runtime.py` (condensation cases), and the method's contract is quoted in its docstring |

## Threshold and abstention calibration (A4-06)

`gate_threshold_calibration` in `data/nctb/retrieval_eval.json` is the
precision-recall-shaped calibration of the served gate:

- answerable mean coverage: **0.9962** (family A, real corpus)
- adversarial mean coverage: **0.75**
- pass rates by candidate threshold:

| threshold | answerable pass rate | adversarial pass rate |
| --- | --- | --- |
| 0.30 | 1.00 | 0.75 |
| 0.40 | 1.00 | 0.75 |
| 0.50 (served) | 1.00 | 0.75 |
| 0.60 | 1.00 | 0.75 |
| 0.70 | 1.00 | 0.75 |

The honest reading (recorded before the fix): on these four adversarial
questions **no threshold in the calibrated range separates the classes** — the
gate's coverage rule is not what refused them. That measurement is the
evidence that closed the gap: the documented ≥2-absent-terms count was
measured and declined (it refuses 37-38% of ANSWERABLE chapter-title and
Banglish questions on this corpus), and the implemented rule is the
**majority form** — a question whose content terms are MOSTLY absent from the
served index (more df==0 terms than known terms) refuses outright, in
`TutorService._coverage_details`, with the honest not-in-textbook answer.
Pinned by `tests/test_r4_ood_gate.py` (unit tests on the gate + a
served-corpus test on the 4 curated adversarial questions). The
`threshold`-calibration table above stays as the evidence for why a
threshold tweak alone could not do this.

Empty and low-confidence retrieval behaviours are defined and exercised:
`empty retrieval → refusal` (no hits ⇒ gate refuses), low coverage →
refusal carrying `insufficient_evidence`, and family C's refusal rate is
recorded per run (`family_C_adversarial_refusal_rate` = **1.0** on the real
corpus after the majority-absent rule; 1.0 on the synthetic test corpus). The
**tests** on this behaviour are `tests/test_query_analysis.py` (coverage
accounting), `tests/test_r4_ood_gate.py` (the rule), the eval gate's
refusal cases, and `tests/test_eval3_targets_report.py` for the report-side
contract.

## Residuals (owner-facing)

1. ~~**Unit normalization** is absent (A4-04's one unbuilt piece)~~ — CLOSED
   2026-10-19: the retrieval tokenizer folds the common curriculum units to
   one canonical form (the full Bangla term), exact-token, both corpus and
   query: "৩ km", "৩ কিমি", "3 kilometre" and "৩ কিলোমিটার" tokenize
   identically (kilometre/metre/centimetre/kilogram/gram/litre/second/minute/
   hour tables in `retrieval/hybrid.py:UNIT_ALIASES`, Bengali→ASCII digits
   already folded by `_DIGIT_FOLD`). Pinned by `tests/test_r4_token_units.py`.
2. ~~**Out-of-domain refusal on the real corpus** (0.25)~~ — CLOSED
   2026-10-19: the majority-absent rule refuses all 4 curated adversarial
   questions on the real corpus (`family_C_adversarial_refusal_rate` = 1.0)
   with **zero new refusals** on answerable families (probe: 0/317 across
   A/B/D). The divergence-register row in `docs/RAG_ARCHITECTURE.md` records
   the decision.
3. **Banglish recall gap of 11 points** is measured, not fixed: improving the
   roman lane or the pronunciation map is a retrieval change gated by the
   pre-registered tolerance.
