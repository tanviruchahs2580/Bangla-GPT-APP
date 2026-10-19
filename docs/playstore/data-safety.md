# Play Console — Data safety form answers

Fill the Data safety form from this table, not from memory. Every row names the
repo-side fact it is derived from; the inventory of record is
`docs/compliance/data-inventory-and-flow-map.md` (41 tables, 11 flows), and the
Bangla-law mapping with dated sources is `docs/compliance/bangladesh-law-mapping.md`.

Two questions to answer the same way everywhere:

- **Is the data encrypted in transit?** Yes — the API and the web app are
  TLS-only, and the Android WebView forbids mixed content
  (`apps/web/capacitor.config.ts`).
- **Do you provide a way to request deletion?** Yes — in-app account deletion
  (`DELETE /users/me`, `apps/web/src/pages/student/MePage.tsx`), plus the same
  URL as the privacy policy. Chat history is also swept automatically after
  `CHAT_RETENTION_DAYS` (180).

## Collected

| Play category | What exactly | Required or optional | Purpose | Evidence |
|---|---|---|---|---|
| Personal info → Name | Student, teacher and parent names entered at registration | **Required** (account) | App functionality — addressing a student, roster display | `db/models.py:Student/Teacher/Parent` |
| Personal info → Email | Account email | **Required** | App functionality, account security (verification, password reset) | `db/models.py:User.email` |
| Personal info → Phone number | Guardian phone, supplied by a parent account | Optional (only for the parent↔student link) | App functionality | `models.py:Parent.phone_enc`; encrypted at rest with Fernet when `PII_ENC_KEY` is set (`security.py:encrypt_pii`) |
| Messages → In-app messages | Tutor conversations and quiz answers | Optional (you only send what you type) | App functionality | `db/models.py:Conversation/ChatMessage`; retention sweep `services/retention.py` |
| Photos → Photos | A photo of a question, when the student chooses to use the camera path | Optional | App functionality (vision question) | `routers/tutor.py` image path; validated (mime allowlist, size cap, magic-byte sniff) before it is sent |
| App activity → In-app search history / other actions | Product events (event name + sanitized primitive properties) | Optional | Analytics — which features get used, where students get stuck | `routers/common.py:_sanitize_event_props` (PII-flavoured keys dropped, strings capped at 40 chars); swept on the same retention policy |
| App info and performance → Crash logs, Diagnostics | Error events and four web-vitals aggregates, **only after the user turns telemetry on** | Optional | Analytics / stability | `apps/web/src/lib/telemetry.ts` — consent-gated, default OFF, `beforeSend` strips user, cookies, headers, request bodies and URL query strings |

## Not collected (declare as "No" in the form)

| Category | Why it is genuinely absent |
|---|---|
| Location | No location permission is requested (`AndroidManifest.xml` asks for `INTERNET` and `RECORD_AUDIO` only) and no geolocation code exists. A photograph can carry GPS EXIF, but the server re-encodes every chat image to a metadata-free copy before it reaches the model provider (`providers/image_safety.py:sanitize_inline_image`, second pass in `services/tutor.py:sanitize_image_payload`), so no location data leaves the device. |
| Financial info | No payments, no purchase path in the app. |
| Health and fitness | None. |
| Contacts, Calendar | None; no permission is requested. |
| Device or other IDs | No advertising ID, no device-ID collection, no third-party ad or analytics SDK. |
| Web browsing history | None. |

## Sharing with third parties

The form asks separately about *sharing*. Play treats a vendor processing data
**on your behalf under a contract** as a service provider, which is answered in
"Collected" rather than "Shared" — but that reading depends on the contract
existing, so treat this as an owner/counsel decision, not an engineering one:

| Recipient | Data | Status to declare |
|---|---|---|
| Google Gemini API (LLM) | The redacted question, retrieved textbook passages, conversation history; an image when the student sends one (re-encoded, metadata-free) | Sent as a **service provider** for the tutoring answer. Redaction of phone/email/NID spans happens before the call (`services/tutor.py`, `bgpt_pii_redacted_total`), and the provider's current data-use/retention terms must be recorded with a date before launch — see `docs/dpa_template.md` and catalog item A7-04. |
| SMTP provider | Recipient address + transactional email body | Service provider. |
| Sentry (error/RUM) | Only after consent: error events and vitals, scrubbed as above | Service provider; **only if `VITE_SENTRY_DSN` is set in the build**. |

## Open items that must be closed before you submit

1. **Provider terms date** (catalog item A7-04). The privacy page and this form
   claim the LLM is a processor; that claim needs the provider's current
   data-use/retention terms looked up and recorded with a date (owner action,
   `I10`) — `docs/dpa_template.md` still carries the "to be confirmed by
   counsel" row.
2. **Account deletion from the packaged app.** Verify once in the release build:
   `/me` → delete account → server-side erasure confirmed (the API is covered by
   tests; the device check covers the WebView path).
3. **Telemetry consent state in the shipped build.** The Data safety answers
   above assume `apps/web/src/lib/telemetry.ts` is in the build (default OFF,
   `beforeSend` scrubbing). Confirm the file exists on the commit you ship; if
   `VITE_SENTRY_DSN` is unset, nothing is collected at all and the
   Crash-logs/Diagnostics row can be answered "No".

## What the form should NOT say

- Do not claim "no data collected" or "data is not shared" — the tutor flow
  genuinely sends the question and passages to the model provider.
- Do not claim "designed for families" in the target-audience answer just
  because the users are minors; that declaration triggers the Families policy
  requirements, which this app does not meet (see `content-rating.md`).
