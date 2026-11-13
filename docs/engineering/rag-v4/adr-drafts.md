# ADR drafts — RAG V4 readiness pass (drafts; owner adoption pending)

Status per draft: `PROPOSED`. Supersedes nothing; no conflict found with
`docs/adr/ADRs.md`. Each follows the repo's existing ADR style (context,
decision, alternatives, consequences).

## ADR-D1 — SSE error frames carry the JSON refusal envelope

- **Context:** a mid-stream provider outage emitted `{code:
  "llm_unavailable"}` while the JSON route's refusal envelope also carries
  `refused_reason`. The web client spreads all error-data fields
  (`done = { __error: true, ...data }`), so parity was free server-side —
  but clients keying on `refused_reason` saw a different contract on the
  two transports.
- **Decision (implemented, `e06d784`):** error frames emit
  `{code, refused_reason}` with the same values as the JSON refusal.
  Vision-path refusal confidence pinned to 0.0 (a refusal is never
  confidence `None`).
- **Alternatives:** client-side mapping (rejected: two sources of truth);
  leaving asymmetry (rejected: contract drift discovered by audit).
- **Consequences:** additive field only; no client change; SSE contract
  tests pin both fields.

## ADR-D2 — Neighbor expansion stays OFF by default (measured)

- **Context:** `RAG_NEIGHBOR_EXPANSION` was default-off and previously
  unmeasurable in the eval CLI (the flag was never consumed there — fixed
  in `aa3d7be`). After the fix, both legs are byte-identical on the golden
  gate: the sample corpus has 0 multi-chunk section buckets, so the stage
  is a structural no-op. The real corpus has 151 multi-chunk buckets, but
  no corpus-bound golden labels exist.
- **Decision:** keep default `false`. Re-evaluate only with a real-corpus
  eval suite (owner-approved labels).
- **Alternatives:** flip on (rejected: unmeasured on real content;
  grounding gate behavior could shift); delete the stage (rejected: real
  buckets show it is meaningful there).
- **Consequences:** no behavior change; the experiment doc records the
  structural explanation so the flag is never "validated" on the sample
  corpus again by mistake.

## ADR-D3 — X-02 canonical return-path policy

- **Context:** boot-401 paths bounced to bare `/login` without `?next=`,
  inconsistently with other redirect sources; deep links were lost.
- **Decision (implemented, `06e6abc`):** one policy — every `/login`
  bounce preserves a validated internal-relative `next`; external URLs,
  protocol-relative paths, encoded/malformed destinations are rejected.
- **Consequences:** deterministic session behavior; covered by e2e
  (expired token, refresh failure, deep link, malformed `next`).

## ADR-D4 — Reranker egress: refuse cleartext endpoints

- **Context:** the dormant cross-encoder stage would POST redacted query +
  corpus text to a configured endpoint; an `http://` endpoint would move
  student-adjacent content unencrypted.
- **Decision (implemented, `33b389f`):** construction refuses cleartext
  endpoints. Redaction at the only production construction site stays.
- **Residual (owner):** no https/host allowlist yet; a data-use gate for
  the endpoint config is proposed before the stage is ever enabled.

## ADR-D5 — Loud exclusion replaces silent drop for non-Bangla content

- **Context:** sources failing the Bangla-ratio screen were previously
  excluded quietly; the English book's absence was invisible to operators
  (the audit had to discover it).
- **Decision (implemented, `e18b00b`):** exclusion is logged loudly at
  build time with the reason; the registry records excluded sources with
  their measured ratio (English book 0.0376 < 0.5).
- **Consequences:** corpus composition is auditable from logs; no serving
  behavior change.

## ADR-D6 — Retention-sweep wording corrected in data_minimization.md

- **Context:** the doc's invite/ai_jobs rows drifted from
  `services/retention.py` (ai_jobs sweep is terminal-status rows only,
  `ai_jobs_retention_days=30`; unused expired student/school/parent invites
  are drained at `expires_at + 30d`, which closes the one plaintext
  contact-field accrual in `student_invites.email`).
- **Decision (implemented, `ddfb115`):** doc re-verified against code and
  corrected; no policy change — windows are untouched design decisions.
- **Consequences:** none behavioral; the doc now matches the sweep tests.
