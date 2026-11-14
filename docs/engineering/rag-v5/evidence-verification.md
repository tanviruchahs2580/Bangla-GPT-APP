# RAG V5 — evidence verification (as-built, shadow-first)

## Contract

`AskResponse.verification_status` (additive, optional, default `None`) —

| mode | behavior |
|---|---|
| `off` (default) | field is `None`; payload identical to pre-V5 (feature-lock: byte-compatible) |
| `shadow` | deterministic citation verdict mapped to `verified`/`unverified`; **never blocking**; shadow results are never displayed to students as verified (V5 §9.3) |
| `enforce` | boot-guarded behind `EVIDENCE_VERIFICATION_ENFORCE_APPROVED=true`; no calibrated verifier exists, so production cannot reach this mode by accident |

## What each verdict means today (separate dimensions per §9.2)

- Citation resolution: `citation_check` — every marker resolves to the
  retrieved set, declarative sentences supported by one chunk (already
  metered + traced; pinned by `test_citation_check_metered_and_warned_on_fail`).
- Source metadata validity: server-side construction from the active
  evidence set (the model never authors source fields) — existing contract.
- Deterministic checks: the above; claim-level support and a semantic
  verifier are **not implemented** (calibration data absent).
- Claim-level mapping: `NOT_RUN` — requires human-reviewed Class 6
  examples (false-accept calibration is a hard precondition of enforce
  mode; V5 §9.3).

## Outage semantics

Verification is deterministic and in-process — there is no verifier
service to go down in this slice. Shadow mode with any internal failure
falls back to `None` (unavailable), never `verified`. Enforce-mode outage
behavior beyond the deterministic path is defined in the failure matrix
of the Master Prompt §8 and lands with the calibrated verifier wave.

## Calibration status

`BLOCKED_OWNER_DATA`: false-accept/false-reject rates require adjudicated
Bangla Class 6 examples (qualified educator review). Until then:
- semantic entailment verifier: not built;
- enforce mode: boot-refused without explicit owner approval;
- shadow: safe (non-blocking, labelled).
