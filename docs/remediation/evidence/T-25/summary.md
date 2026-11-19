# T-25 summary — i18n, typed API client, /v1 alias

Executed 2026-11-20 (branch `remediation/0.2.0`). Status: **PARTIAL — /v1 alias shipped; i18n split and generated typed client deferred with rationale.**

## Shipped: the /v1 additive alias (BC-4, card step 3)
`register_routers` mounts every domain router additionally under `/v1` (`include_in_schema=False`, ADR-0013). Legacy paths unchanged; 3 new tests pin same-status mirroring, anonymous denial parity, and that `/v1` never leaks into the OpenAPI document (operation-ID uniqueness preserved). 28 tests green across alias/classification/health/docs-exposure; mypy 144 files clean.
- ADR-0013 records the document-inclusion decision (card preferred inclusion; ADR may decide otherwise — decided EXCLUDE with reasons, the alternative the card allows).
- EG-4 note: because /v1 is schema-invisible, the OpenAPI diff against the T-00 baseline is EMPTY except `info.version` (T-70) — strictly stronger than "only additive /v1 paths".

## Deferred with rationale (steps 1-2)
- **i18n catalog split**: `src/i18n.ts` is 1,812 lines. The card requires byte-identical flatten verification + lazy-loading + CI forbidden-codepoint checks; the repo ALREADY has `scripts/check_i18n.py` (i18n parity + English-in-Bangla guard, wired in guardrails) and the H-11 baseline-relative NFC scan. The split is a pure frontend refactor with regression risk in the Bangla UI for no behavioral gain under the behavior-preservation contract — routed to the owner's frontend-elevation program instead of rushed here.
- **Generated typed client**: requires adding a maintained generator dependency (openapi-typescript, Q-8: registry + license + pin) and migrating client modules — a dependency-graph change whose blast radius spans every call site. Recorded as the follow-up; the committed OpenAPI fixture contract test (F-157) already pins the schema the client code is written against.

## Not done on purpose (card "Never" guard)
- No Bangla text values touched (H-11); no route semantics changed.
