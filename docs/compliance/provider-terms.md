# LLM provider terms — checked record (A7-04 / I10)

Finding AUD-A2-… / catalog item **A7-04** requires the provider's *current*
data-use and retention terms for the tier in use to be looked up, recorded here
with a date, and flagged to the owner. This is that record. It gives no legal
conclusions: it quotes the vendor's own pages and states the operational
consequence, so the owner (or counsel) can decide.

## What was read

| Source | Last updated (as shown) | Read on |
|---|---|---|
| `https://ai.google.dev/gemini-api/terms` (Gemini API Additional Terms) | 2026-04-28 UTC | 2026-10-20 |
| `https://ai.google.dev/gemini-api/docs/usage-policies` | 2026-06-09 UTC | 2026-10-20 |
| `https://ai.google.dev/gemini-api/docs/pricing` (price rows used by `services/costs.py`) | 2026-10-16 UTC | 2026-10-19 |

## What the terms say, split by tier

The terms distinguish **Unpaid Services** from **Paid Services**, and the
difference matters directly for this product.

| | Unpaid (free) tier | Paid tier |
|---|---|---|
| Prompts and responses used to improve Google products? | **Yes** — "Google uses the content you submit to the Services and any generated responses to provide, improve, and develop Google products and services and machine learning technologies." | **No** — "Google doesn't use your prompts … or responses to improve our products." |
| Logging | As above | Logs prompts/responses "for a limited period of time, solely for detecting and preventing violations of the Prohibited Use Policy" |
| Retention (usage policies) | "Prompts", "Contextual Information" and "Output" are kept for **55 days** to detect and prevent prohibited-use violations and for legal/regulatory disclosures | Same 55-day abuse-monitoring retention; Grounding-with-Google-Search/Maps data is stored for 30 days |
| Human access | "Data can be accessed for human review only by authorized Google employees via an internal governance assessment and review management platform" | Same |
| Training on logged abuse data | "is not used to train or fine-tune any AI/ML models besides those used specifically for policy enforcement" | Same |
| Processing terms | — | Prompts "processed … in accordance with the Data Processing Addendum" |

## What this means for this deployment (owner decision — flagged, not decided)

1. **A free-tier key is not appropriate for a minors-facing tutor.** The key
   currently configured is a free-tier key (the live run recorded the vendor's
   `generate_content_free_tier_requests` quota), so questions asked by
   children would fall under "used to improve and develop Google products and
   machine learning technologies". The paid tier's terms are the ones that
   match this product's guardian-consent story and the privacy page's
   "processed on our behalf" wording.
2. **Until the tier changes, the privacy copy must not claim paid-tier terms.**
   The privacy page (`/privacy`, bn + en) and `docs/compliance/bangladesh-law-mapping.md`
   describe the provider as a processor; that description holds under the paid
   tier's DPA sentence, and needs the owner's explicit decision (plus the
   guardian-notice wording) before any child uses a free-tier key in
   production.
3. **Nothing here is a legal conclusion.** The 55-day retention, the human-review
   clause and the improvement clause are quoted for counsel; the operational
   recommendation is: paid tier before launch, or a documented guardian-consent
   basis that covers free-tier improvement use.

## How this is enforced in code (not just promised)

- Redaction runs before every provider call (phone/email/NID spans,
  `services/tutor.py`, metered as `bgpt_pii_redacted_total`), so the provider
  receives the question and the textbook passages, not the child's identity.
- Chat images are re-encoded metadata-free before the call
  (`providers/image_safety.py`), so EXIF/GPS never reaches the provider.
- The model, prompt version and index fingerprint ride every trace, so a tier
  or model change is visible in the run record (see
  `docs/operations/CHANGE_MANAGEMENT.md`).
- `LLM_PROVIDER=mock` in production is refused at startup, so a deployment
  cannot silently run without a provider and claim the opposite.

## Follow-up owner actions

| Action | Why |
|---|---|
| Move to the paid tier before launch (or record the free-tier decision with counsel) | the improvement-use clause |
| Re-read this record at each provider-term update (the pages carry their own dates) | the quoted terms can change without notice |
| Keep the provider's DPA/terms PDF with the compliance set | evidence for the school/counsel conversation |
