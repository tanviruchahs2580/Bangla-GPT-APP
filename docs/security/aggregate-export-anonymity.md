# Aggregate export — k-anonymity and differencing review notes

Finding: AUD-B-11 (B register) — "differencing/linkage risk undocumented".
Scope: `GET /admin/reports/aggregate` and `services/govt_report.py`.
Review date: 2026-10-19. This is an engineering risk review, not a legal
conclusion; the statutory side is tracked in
`docs/compliance/bangladesh-law-mapping.md` ("requirements to confirm with
counsel").

## What the export guarantees

1. **Aggregates only.** The query selects distinct-student counts, attempt
   counts and score means per `(class_level, subject)`; no name, email,
   phone, user id or attempt id ever leaves the aggregation step
   (`services/govt_report.py:aggregate`). Pinned by
   `tests/test_b2_k_anonymity_export.py::test_rows_carry_aggregate_keys_only`.
2. **k-anonymity threshold, requester cannot lower it.** Default/floor
   `MIN_CELL_FLOOR = 5`; the route refuses `min_cell < 5` with 422 and the
   service clamps direct callers (`effective_min_cell`). Cells below the
   threshold are dropped AND counted (`suppressed_cells`).
3. **Per-cohort suppression for the tutor metric.** `active_tutor_students`
   is checked against the same threshold on its own class-level cohort; a
   cohort below it is blank rather than zero, and the suppression is counted.
4. **Belt-and-braces PII gate.** Every export is scanned for email/phone
   shapes before it is written; a hit fails the request closed (500, logged
   as `aggregate_report_pii_blocked`).
5. **Access is audited.** Every successful export writes one `govt_export`
   audit row (actor, target, format, district, window, threshold, row and
   student counts) so pattern-of-use is reconstructable after the fact.

## Residual differencing / linkage risks (accepted, monitored)

| Risk | Why it survives the threshold | Control in place |
|---|---|---|
| **Repeated queries over shrinking windows.** `since_days` is caller-chosen; two exports over [0-30d] and [0-60d] let a requester subtract the cohorts. | The threshold is per-cell, not per-query; subtraction can isolate the delta cohort even when each export is individually suppressed. | Every export is audited (`govt_export` rows carry `since_days`, `min_cell`, counts); the audit trail is the detection mechanism. Owner action below tightens this further. |
| **Boundary release.** A cell with exactly `min_cell` students discloses that "at least 5, and by convention exactly 5+" — with a known class roster, that is often a specific 5. | k-anonymity is a count guarantee, not a semantics guarantee. | The floor is 5 and cannot be lowered; raising `min_cell` is allowed and suppresses more; dashboard consumers are schools/authorities, not the public. |
| **Cross-dataset linkage.** Class level + subject + score mean + attempt count combine with a school's own records (or another export) to narrow individuals. | Aggregation cannot control what other datasets the recipient holds. | Exports carry no geographic or per-student identifiers; `district` is only a label the requester supplies (it is not used as a filter — verified in `aggregate()`), so it cannot be used to slice smaller cohorts. |
| **Composition with other endpoints.** The same admin role can also read school dashboards; the aggregate endpoint is not the only count surface. | Differential privacy would need a query budget across all surfaces. | `GET` handlers that write rows are enumerated and frozen (`tests/test_b_get_side_effects.py`); the aggregate export is admin-only (135-route authz matrix). |
| **Tutor-metric timing.** `active_tutor_students` is all-time, unlike the attempt window; an all-time count beside a windowed one can reveal "how many started recently". | Mixed denominators. | It is threshold-suppressed independently; the review flags it as the item to re-examine if windows become requester-tunable per metric. |

## Review conclusion

The enforced mechanics (threshold floor, suppression counting, PII gate,
mandatory audit) match what the register asked to verify, and the residual
risks are small-cell/query-composition risks that the audit trail makes
detectable. They are **accepted for the current access model** (authenticated
admin, authority-driven exports) rather than solved.

Owner action: if exports ever run on a self-service cadence, add a per-actor
query budget or a documented approval step; and fold the "composition across
surfaces" question into the counsel review of government-export duties.
