# Frontend Security and Privacy Review — Bangla GPT renovation

Scope: the changed client-side surface. This is an NCTB-grounded AI tutor for Bangladeshi
schoolchildren; **student academic records and guardian contact data are in scope**, so
privacy findings are weighted accordingly.

Method: review of the actual diff, the auth/session code path, the rendering path, and the
storage/logout path. Findings the independent reviewer added are in
`REGRESSION-AND-INDEPENDENT-REVIEW.md`, not duplicated here.

---

## 1. Scope confirmation

**No backend, API contract, database, or model change exists in this diff.** Confirmed by
inspecting the change list rather than assuming:

| Area | Changed? |
|---|---|
| `apps/api/**` (routes, services, models, migrations, prompts, RAG, eval) | **No** |
| Dependencies / lockfiles / `constraints.txt` | **No** |
| Configuration / `.env*` / CI workflows / Capacitor or Android config | **No** |
| `apps/web/src/api.ts` (endpoints, methods, payloads, auth handling) | **No** |
| `apps/web/src/types.ts` (shared contract types) | **No** |
| `apps/web/src/AuthContext.tsx`, `App.tsx` route gates | **No** |

Files changed in product code: `styles.css`, `i18n.ts`,
`components/admin/SchoolsCard.tsx`, `components/OfflineLibrary.tsx`,
`components/teacher/QPaperReviewPanel.tsx`, `pages/LoginPage.tsx`, plus six files under
`src/test/`.

## 2. Checklist results

| # | Category | Result |
|---|---|---|
| 1 | Secrets, keys, tokens in source / tests / docs / logs | **None found.** No credential was added anywhere. No `.env*` file was read into source, printed, or committed. The fixture password for synthetic `@e2e.test` accounts was deliberately never placed on a command line or in a transcript; authenticated verification runs through the Playwright harness, which holds it in `e2e/a11y.ts`. |
| 2 | Unsafe HTML / markdown / code rendering | **No change.** No new `dangerouslySetInnerHTML`, `innerHTML`, `eval`, or `new Function`. The existing sanitised path (`lib/safeMarkdown.tsx`, `lib/safeMarkdownLazy.tsx`, `lib/safeHref.ts`) is untouched. |
| 3 | XSS / DOM injection in changed code | **No new surface.** The one new DOM write is `toast(t("offlineDeleteFailed"))` in `OfflineLibrary`, and `toast()` uses `el.textContent = message` — a text node, not markup. The string is a static i18n constant with no interpolation, so nothing user- or server-controlled reaches it. |
| 4 | Unsafe URL / redirect | **Improved.** The only changed URL-handling code is `LoginPage`'s resend control, which moves from `<a href="/forgot">` to a button that performs no navigation at all. The `?next=` open-redirect guard in `App.tsx:171-180` is untouched. |
| 5 | Authorization | **No change, and no new client-side check.** `RequireAuth`'s six-step decision order (`App.tsx:84-119`) is byte-identical. No route gate was added, widened, or reordered. Nothing in this diff can be mistaken for server authorization; the server remains the authority, and the one permission-adjacent finding (`/school` documented as `school_admin / admin` but gated to `school_admin`) was deliberately **left as-is** rather than widened from the client — see **R-14**. |
| 6 | Privacy / PII | **No new PII surface.** Nothing new is written to `localStorage`, `sessionStorage`, or IndexedDB. Nothing new is logged. Nothing is transmitted. The new i18n strings are static copy and name no person, school, or code. |
| 7 | Auth / session semantics | **No change.** Token handling, the `logout()` scrub, the "API unreachable vs session refused" ordering, and the `?next=` return path are untouched. The `LoginPage` change preserves the exact handler and argument (`resendVerification(email.trim() \|\| undefined)`) and only changes the element. Its new test asserts the control is `type="button"`, so it cannot submit the form it lives in. |
| 8 | Supply chain | **No dependency, lockfile, or config change.** No package was added, upgraded, or removed. |
| 9 | Client-side role checks as authorization | **None introduced.** |
| 10 | Untrusted content treated as instructions | **Not applicable to this diff.** No MCP/Figma/document content was imported into source. |
| 11 | Error messages leaking sensitive diagnostics | **No change.** `friendlyError()` and the error-code mapping are untouched. |
| 12 | Privacy exposure in evidence artefacts | Reviewed: the screenshots and logs committed into this bundle contain only synthetic `@e2e.test` data, or no data at all. No real student record, guardian contact, or credential appears. |

## 3. Two privacy-adjacent observations worth stating

**3.1 The changed SchoolInvite path now fails loudly instead of silently (R-03).** This is a
privacy-*positive* change in a subtle way: previously a failed fetch of
`/admin/schools/:id/invites` rendered an empty table. An admin acting on that false empty
state might re-issue invites unnecessarily, or conclude a leaked code had already expired.
The new `LoadError` states the truth. No data is exposed that was not already visible to the
same admin.

**3.2 The offline-copy delete now reports failure (R-06).** Also privacy-positive: previously
a student who tapped delete on a downloaded chapter and got no feedback would reasonably
conclude the copy was gone. It was not. Since offline copies are user-scoped device storage
of textbook content (not personal data), the exposure is low — but a UI that falsely implies
data was removed is the wrong default in a children's product.

## 4. Findings carried, not fixed (with the reason)

| ID | Sev | Finding | Why not fixed here |
|---|---|---|---|
| R-14 | P2 | `/school` is documented as serving "school_admin / admin" but gated to `school_admin`, so a platform admin is redirected to `/admin`. | Whether a platform admin *should* see `/school` is a permissions decision. Widening a frontend role gate is precisely the "frontend-only authorization" trap `AGENTS.md` §6 and the master prompt §0.3 warn about, and the server remains authoritative. Align route + comment + server policy together. |
| R-17 | P3 | `MePage.tsx:504` renders the server string `on_disable_note_code` through `t()` with a raw-value fallback, so an unmapped code can surface as machine text to a child. | The correct copy per code is a content decision and the code set is owned by the API. Inventing translations for codes whose meaning is not documented here would be worse than the fallback. |
| — | P3 | Four destructive actions have no confirmation (delete note, delete offline copy, revoke guardian invite, revoke school invite). | The feature lock names "confirmations" and "submission behavior" as locked, and `savedNotes.test.tsx` asserts the current single-step behaviour — so this is intended, not accidental. Owner decision; see **R-13**. |
| — | info | The audit log, consent versioning, PII encryption, retention windows, and the `gdpr.py` export/erasure path are all server-side and **outside this diff**. | Not assessed here beyond confirming they were not touched. |

## 5. Verdict for this section

**PASS for the changed surface, with two P3 items and one P2 permissions question carried to
the owner.** No new secret, injection, redirect, authorization, or PII exposure was
introduced. Two changes incidentally improve honesty in a privacy-adjacent way.

This is a review of a frontend diff, not a security audit of the product. It says nothing
about backend hardening, infrastructure, or the children's-data governance gap this
repository already documents as open (no DPIA — `AGENTS.md` §15).
