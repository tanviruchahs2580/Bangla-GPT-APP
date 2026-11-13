# End-to-end traces — 3 representative questions (V4 Phase 4)

Date: 2026-11-13 · Hermetic stack (`Settings(env="test")`, mock provider,
sample corpus, hash embedder) via `TutorService.ask` with
`AnswerTraceStore` attached. Evidence ids are the trace store's `chunk_ids`
(the corpus chunk ids the gate read); sources are the served `SourceRef`s.

| # | Class | Question | grounded | refused_reason | Top sources (chapter, score) | Trace outcome | chunk_ids (top 3) | Latency total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | in-corpus | কোষ কী? | True | None | কোষ 13.437 / কোষ 9.305 / পানিচক্র 2.552 | answered | `6a181432c4d967f0`, `622888ce5d3760db`, `b552fd03a2039970` | 82 ms |
| 2 | Banglish | `kosh ki? bhitore ki thake` | True | None | কোষ 5.428 / উদ্ভিদ ও খাদ্য প্রস্তুতি 3.995 / কোষ 3.074 | answered | `622888ce5d3760db`, `fc4751e1bfbde9e9`, `6a181432c4d967f0` | 63 ms |
| 3 | out-of-corpus | ক্রিকেট বিশ্বকাপ ২০২৩ সালে কে জিতেছিল? | False | `insufficient_evidence` | — (empty) | insufficient_evidence | (candidates existed: `4d4af27b4b214589`, `58d447b1ab8be0da`, `b552fd03a2039970`) | 27 ms |

## What each trace demonstrates

1. **In-corpus** — full happy path: retrieval ranks the কোষ chapter first,
   the grounding gate passes, the (mock) answer is grounded, trace outcome
   `answered` with three evidence ids.
2. **Banglish (romanised)** — the transliteration lane fires: `kosh ki`
   retrieves the same কোষ chapter evidence and the answer is grounded.
   This is the first-class path the project mandates (§5 of AGENTS.md);
   before the transliteration lane existed, every Banglish question abstained.
3. **Out-of-corpus** — the grounding gate **refuses** with
   `INSUFFICIENT_EVIDENCE_ANSWER` / `refused_reason=insufficient_evidence`,
   empty sources, no fabricated content. **A refusal is the correct
   outcome here** — candidates existed (`chunk_ids` in the trace) but
   coverage was below the gate; nothing was answered from them.

Caveats (honesty): the generator here is the mock provider, so answer text
quality is not being judged — this trace validates the retrieval → gate →
refusal plumbing and evidence-id recording end-to-end, which is what Phase 4
asks for. Live-model answer quality is the separate UNVERIFIED-LIVE class
(judge mode `local_overlap`; a real model + human review required, per the
eval CLI's own output).
