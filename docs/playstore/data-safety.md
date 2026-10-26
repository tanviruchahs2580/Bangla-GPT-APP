# Play Console — Data safety form answers

Fill the Data safety form from this table, not from memory. Every row names the
repo-side fact it is derived from, or the owner-side record that has to exist
before the answer is given. This file is the answer sheet; the governance
records behind it — the data inventory and flow map, the Bangladesh-law
mapping with dated sources, and the provider-terms decision — are owner-side
documents kept with the launch checklist, not in the product tree.

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
| Photos → Photos | A photo the student attaches from their device — a question paper or a whiteboard. The app has **no in-app camera** (`accept=...` file input only, no `capture`, no camera permission, no camera plugin) | Optional | App functionality (vision question) | `apps/web/src/pages/student/AITutorPage.tsx` file input; `routers/common.py:_validate_chat_image` (mime allowlist, size cap, magic-byte sniff) before it is sent |
| App activity → In-app search history / other actions | Product events (event name + sanitized primitive properties) | Optional | Analytics — which features get used, where students get stuck | `routers/common.py:_sanitize_event_props` (PII-flavoured keys dropped, strings capped at 40 chars); swept on the same retention policy |
| App info and performance → Crash logs, Diagnostics | Error events (and a 10% performance-trace sample) sent to Sentry, **only when the build was compiled with `VITE_SENTRY_DSN`** | Optional | Stability | `apps/web/src/main.tsx` — `Sentry.init` is a no-op without a DSN. **There is no consent switch and no `beforeSend` scrubbing yet**, so this row follows the build you ship: a DSN-less build answers **No**; a build with a DSN must declare crash logs/diagnostics. Consent-gating is tracked work — do not claim "consent-gated" until it exists |

## Not collected (declare as "No" in the form)

| Category | Why it is genuinely absent |
|---|---|
| Location | No location permission is requested (`AndroidManifest.xml` asks for `INTERNET` and `RECORD_AUDIO` only) and no geolocation code exists. A photographed page can carry GPS EXIF, so the server decodes and re-encodes every attached image before it goes anywhere: `providers/image_safety.py:sanitize_image` drops EXIF (including the GPS sub-IFD), XMP, ICC, PNG text chunks and trailing bytes, and `routers/common.py:_validate_chat_image` is the only boundary that turns outside bytes into a provider payload. Pinned by `apps/api/tests/test_image_metadata_stripping.py`. No location data leaves the device. |
| Financial info | No payments, no purchase path in the app. |
| Health and fitness | None. |
| Contacts, Calendar | None; no permission is requested. |
| Device or other IDs | No advertising ID and no device-ID collection. No ad SDK and no product-analytics SDK; the only third-party SDK in the shipped bundle is `@sentry/react` for error monitoring, active only in DSN builds (see the Crash-logs row). |
| Web browsing history | None. |

## Sharing with third parties

The form asks separately about *sharing*. Play treats a vendor processing data
**on your behalf under a contract** as a service provider, which is answered in
"Collected" rather than "Shared" — but that reading depends on the contract
existing, so treat this as an owner/counsel decision, not an engineering one:

| Recipient | Data | Status to declare |
|---|---|---|
| Google Gemini API (LLM) | The redacted question, retrieved textbook passages, conversation history; the student's photo when they attach one, **re-encoded without metadata** | Sent as a **service provider** for the tutoring answer. Redaction of phone/email/NID spans happens before the call (`services/tutor.py`, `bgpt_pii_redacted_total`). The provider's data-use/retention terms must be recorded, with a date, before launch — the vendor's data-use and retention terms must be **confirmed in the billing console and recorded with a date** (the tier is not established anywhere in this repo) — the free tier uses submitted content to improve Google products, so **a paid-tier key is required before launch** unless a guardian-consent basis for free-tier use is documented. An attached photo reaches the provider as a metadata-free re-encode (see the Location row for the mechanism), so the file's GPS, capture time and device identifiers are not part of what is shared. |
| SMTP provider | Recipient address + transactional email body | Service provider. |
| Sentry (error monitoring) | Sent whenever the build set `VITE_SENTRY_DSN` — **no consent switch and no scrubbing hook exist yet** (see the Crash-logs row above); no web-vitals package is installed | Service provider; **only if `VITE_SENTRY_DSN` is set in the build**. |

## Open items that must be closed before you submit

1. **Provider terms date** (catalog item A7-04). The privacy page and this form
   claim the LLM is a processor; that claim needs the provider's current
   data-use/retention terms looked up and recorded with a date (owner action,
   `I10`) — `docs/dpa_template.md` still carries the "to be confirmed by
   counsel" row.
2. **Account deletion from the packaged app.** Verify once in the release build:
   `/me` → delete account → server-side erasure confirmed (the API is covered by
   tests; the device check covers the WebView path).
3. **Whether the shipped build reports crashes.** There is no consent switch:
   the build reports to Sentry exactly when `VITE_SENTRY_DSN` was set at build
   time (`apps/web/src/main.tsx`). Decide per build: no DSN → the
   Crash-logs/Diagnostics row is "No"; DSN → declare it. If a consent-gated
   telemetry module lands before submission, answer from what that module
   actually does, not from intent.

## What the form should NOT say

- Do not claim "no data collected" or "data is not shared" — the tutor flow
  genuinely sends the question and passages to the model provider.
- Do not claim "designed for families" in the target-audience answer just
  because the users are minors; that declaration triggers the Families policy
  requirements, which this app does not meet (see `content-rating.md`).
