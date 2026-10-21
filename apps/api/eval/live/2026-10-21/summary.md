# Live evaluation -- gemini-3.5-flash-lite

- split: `test` (185 items), red-team: 43
- provider calls: 184 (retried: 0); served from recording: 0; errors: 0
- estimated spend: $0.0816 of the $0.60 cap
- started 2026-10-20T22:35:33+00:00 / finished 2026-10-20T22:48:55+00:00
- partial: False

## Metrics

| metric | value |
|---|---|
| abstention_precision | 0.3636 |
| abstention_recall | 1.0 |
| citation_precision | 0.8802 |
| citation_precision_chapter | 0.9688 |
| citation_precision_chapter_retrieved | 0.5701 |
| citation_precision_retrieved | 0.334 |
| citation_recall | 0.9713 |
| citations_retrieved_total | 521 |
| citations_total | 192 |
| false_refusal_rate | 0.0387 |
| format_validity | 1.0 |
| grounded_items | 174 |
| items | 185 |
| refusal_correctness_unsafe | 1.0 |
| refusals_total | 11 |
| response_language_correctness | 1.0 |
| unsafe_items | 43 |
| vocabulary_probe_items | 167 |

Judge-human agreement is deliberately not reported: the sample carries no
human labels (owner action), and an unmeasured agreement number would be a
fabricated metric.

Replay material: `recorded_responses.jsonl`, keyed by the digest of the
exact prompt sent (prompt + system + image prefix).
