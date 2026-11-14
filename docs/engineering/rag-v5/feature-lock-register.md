# RAG V5 feature-lock register — 2026-11-15

Legend: `UNCHANGED` · `ADDITIVE_BACKWARD_COMPATIBLE` · `OWNER_APPROVED_CHANGE` · `REGRESSION`.
Per V5 §2.2; "100% unchanged" is deliberately not claimed.

| Surface | Baseline behavior | Lock status | Evidence plan |
|---|---|---|---|
| `POST /tutor/ask` JSON envelope | answer/grounded/sources/refused_reason/confidence/citation_verified | `ADDITIVE_BACKWARD_COMPATIBLE` — optional `verification_status` field only when verification mode ≠ off | apiContract/openapi fixture regen; errorCodeParity; SSE parity tests |
| SSE ask events | error frames carry `code`+`refused_reason`; parity with JSON | `UNCHANGED` (new optional field passes through the existing spread only if present) | existing SSE contract tests |
| Retrieval mode | single `hybrid` (BM25 ∥ hashing vectors, RRF k=60, lexical rerank) | `UNCHANGED` as the default; new modes are explicit, non-default, boot-guarded | existing hybrid/retrieval tests green; new mode tests assert default selection unchanged |
| Grounding gate + top-3 evidence | IDF-weighted coverage gate; bounded top-3 | `UNCHANGED` | existing grounding tests |
| Safety/consent/PII/authorization | pre-retrieval screening; RBAC on admin ops | `UNCHANGED`; new admin/index ops ride existing deps (`AdminUser`) | full API suite |
| Corpus loader/manifest | startup load, embedder identity gate | `UNCHANGED`; generation registry sits beside it, does not replace it | manifest gates + NCTB tests |
| Frontend answer/source rendering | existing source chips, verification label | `UNCHANGED` this wave (no UI change; additive backend field tolerated by old clients) | web suite 115 files |
| Retention/export/erasure | existing sweeps; new tables hold NO student/personal data (curriculum vectors only) | `UNCHANGED` for existing tables; new tables carry curriculum embeddings only — recorded in data minimization doc | full API suite + doc check |
| Migrations | 38 files, single linear chain | `ADDITIVE_BACKWARD_COMPATIBLE` — new engine-conditional migration; chain pin advanced | `alembic check` + chain test |
| Class/subject/chapter filters | established meanings | `UNCHANGED`; pgvector lane applies the same filters server-side | new filter tests |
| Live production runtime | SQLite, hashing hybrid default | `UNCHANGED` behavior; only additive schema (SQLite: registry tables) lands via migration | post-swap smoke |
