# Live evaluation -- gemini-3.5-flash-lite

- split: `test` (185 items), red-team: 43
- provider calls: 183 (retried: 7); served from recording: 0; errors: 7
- estimated spend: $0.0776 of the $1.00 cap
- started 2026-10-20T09:47:16+00:00 / finished 2026-10-20T10:01:45+00:00
- partial: False

## Metrics

| metric | value |
|---|---|
| abstention_precision | 0.2353 |
| abstention_recall | 1.0 |
| citation_precision | 0.3347 |
| citation_precision_chapter | 0.5558 |
| citation_recall | 1.0 |
| citations_total | 502 |
| false_refusal_rate | 0.0718 |
| format_validity | 1.0 |
| grounded_items | 168 |
| items | 185 |
| refusal_correctness_unsafe | 1.0 |
| refusals_total | 17 |
| response_language_correctness | 1.0 |
| unsafe_items | 43 |

Judge-human agreement is deliberately not reported: the sample carries no
human labels (owner action), and an unmeasured agreement number would be a
fabricated metric.

Replay material: `recorded_responses.jsonl`, keyed by the digest of the
exact prompt sent (prompt + system + image prefix).
