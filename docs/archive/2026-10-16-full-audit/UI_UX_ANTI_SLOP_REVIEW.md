> **Historical, not current.** Kept for history only; this snapshot does
> not describe the current tree and must not be quoted as current status.
> Current sources of truth: [../README.md](../README.md).

# UI/UX & ANTI-AI-SLOP REVIEW — Bangla GPT APP (2026-10-16)

Method: **(1)** static review of every page and shared component in
`apps/web/src`, then **(2)** a live GUI pass against a real running stack —
API on `127.0.0.1:8010` (mock LLM provider, throwaway SQLite database) and the
SPA on `localhost:5273` — driving the app as a student and as a teacher at
1366×768 and 390×844, capturing **37 screenshots** in `screenshots/` (plus one after-fix re-capture). Findings
in the "live" section were observed on screen, not inferred from code.

Environment limits are stated at the end; nothing here is claimed as verified
that was not actually rendered and looked at.

---

## 1. What the product actually is (from the rendered app)

A bilingual (Bangla-first, English toggle) tutor for classes 6–10: a student
gets a textbook reader with an offline copy, an AI tutor that answers from
retrieved curriculum evidence with a citation affordance, quizzes with honest
grading, a revision queue, a progress report and an activity heatmap; a parent
gets a weekly/monthly digest of their linked child; a teacher gets class
analytics, question-paper and lesson-plan generation, short tests, assignments
and coverage views; admins and school staff get institutions, rosters, invites
and a feedback-triage/AI-quality console.

The identity that is actually present — teal/green palette, Shapla-book brand
mark, Hind Siliguri/Noto Sans Bengali typography, restrained cards — is
consistent across all 12 screens reviewed. It does not read as a generic
template swap: the tutor, reader, quiz and teacher hubs have visibly different
information hierarchies for different jobs.

## 2. Anti-slop verdict

**Code-level**

| Check | Result |
|---|---|
| Fake/inert controls in audited scope | **1 fixed** (triage retry), 4 open (see table) |
| Unsubstantiated metrics / placeholder production content | **1 fixed** (`{chapters}` on the report), 3 open (`F-17`, `F-31`, `F-33`) |
| Unexplained lint/type suppressions | 1 in `src/` (`ClassesPage.tsx:202`, a hooks-deps disable that is now unnecessary); no `any`, no `@ts-ignore` in app source |
| Dead code | `components/ui.tsx`'s focus-trapped `Modal` is unused by any page (only tests), while `AITutorPage` hand-rolls a second dialog; `.composer` CSS class is dead |
| Duplicated logic that has drifted | `errText`/`errOf` helpers repeated across 4 pages plus 7 inline `friendlyError` calls; `suggestionSentence` was duplicated — **now shared** |
| Stale/misleading comments | 2 found; 1 fixed (bookmark catch), 1 remains (`LearnPage.tsx:226` paints a fixed 45% "reading" bar with a comment that does not explain it) |
| Over-generalized abstractions | none found — the component set is small and each piece is used |

**Visual**

- No random gradients, glow effects, blobs, glassmorphism, stock illustrations, or fake charts were found in any reviewed screen.
- Spacing, radii, badges and buttons are consistent; the same primitives (`ui.tsx`) are used throughout rather than per-page re-styling.
- Every reviewed page had a clear primary task in the first screenful; the teacher hub and reader differ structurally, which is appropriate.
- Bangla text renders correctly at both viewport widths (no broken conjuncts, correct line height, no mid-character clipping), and no page overflowed horizontally at 390px.

## 3. Live pass — page-by-page

| Page / state | Verdict | Notes |
|---|---|---|
| `/welcome` (desktop, mobile) | Good, one issue | Clear value proposition, Bangla-first copy, restrained stat tiles. **`F-17`**: "১০০% / বাংলা-প্রথম অভিজ্ঞতা" is an unverifiable statistic. |
| `/login` (desktop, mobile) | Good | Labels, focus handling and error copy are correct; MFA step-up and forced-password-change paths exist. |
| `/student` home | Good | Five purposeful blocks, real skeletons while loading; dark mode and language toggle both persist. |
| `/student/learn` catalogue | **P2 defect** | **`F-26`**: the grade chip row offers 1–12 but only class 6 has content; choosing 1 renders an empty page with no message. Real catalogue/chapters render well for class 6. |
| Chapter reader | Good, three polish defects | Real Bangla content, working bookmark (with `aria-pressed` + toast), working offline download (IndexedDB), working font slider. **`F-32`**: badge shows the English slug `science` next to a Bangla heading; the saved-download state keeps the old `aria-label`; the font slider moves body text only. |
| `/student/tutor` | Good, two defects | Streaming answer over SSE works; citation chip opens an evidence modal with breadcrumbs; stop/send/mic/attach all present and labelled; no stuck spinner. **`F-27`**: the citation row renders the same chip twice. **`F-29`/`F-30`** at 390px: composer placeholder clipped, and keyboard focus can land under the fixed bottom bar. |
| `/student/quiz` | Good | Start → 5 questions → results → revision/assigned tabs all work; correct rows show ✓ and incorrect rows offer re-teaching; revision tab shows a real empty state. |
| `/student/me` | **P2 defect, now fixed** | **`F-25`**: the report sentence printed a raw `{chapters}` placeholder. Fixed and re-verified live — it now reads "পরামর্শ: দুর্বল অধ্যায়গুলোতে বেশি অনুশীলন করুন: পানিচক্র।" with no `{...}` anywhere. **`F-14`**: the AI-memory switch applies immediately while the adjacent preference card requires an explicit Save, so the save model is inconsistent. |
| `/teacher` home | Good, one issue | Workload and quick starts are clear. **`F-28`**: React duplicate-key console error. **`F-33`**: "প্রায় ০ মিনিট সাশ্রয় (আনুমানিক)" — a zero-data estimate presented as a metric. |
| `/teacher/create` | Acceptable | Question-paper form is complete and its submit correctly stays disabled until a name is entered. **`F-28`**: duplicate-key console error. An empty bordered panel appears before a type is chosen. |
| `/status` | Acceptable | Real dependency states with a timestamp. **`F-31`**: English-only copy and a US-format timestamp (already tracked in the i18n checker's pending list). |
| `/parent` | Not exercised live | Static review only: linking is consent-gated and the digest renders the API's suggestion code through the now-shared helper. |

**Interaction integrity:** every control clicked during the pass did real work
(search, notifications, language, theme, bookmark, download, font size, quiz
flow, citation modal, teacher tiles). No dead button, fake navigation or
decorative control was found in the reviewed pages — the one inert control from
the static review (`CreatePage` assign with no classroom, `F-14`) was not
reached in this pass and remains PROBABLE.

## 4. Accessibility outcomes

**Verified good:** icon-only buttons carry `aria-label`s; the shared `Modal`
traps focus, restores it, locks scroll and closes on Escape; class-health status
in `ClassesPage` includes visually-hidden text so it is not colour-only; the
spinner exposes a status role.

**Open (`F-13`, `F-30`):** no skip link and no `<h1>` in the app shell;
`aria-live="polite"` on the entire chat thread container (every streamed token
mutates the live region); pagination buttons in the admin console have no
accessible name; the chapter-question input and the CSV paste box are
placeholder-only; `role="menu"`/`menuitem` and several `role="tab"`/`role="radio"`
groups lack arrow-key handling; and on 390px keyboard focus can settle beneath
the fixed bottom bar.

Automated axe coverage exists in the suite (`axeSweep`, `axeWelcome`), which is
why several of these are structural (ARIA-contract) rather than label-level
issues that a scanner would flag. Screen-reader verification was **not** possible
here, so the impact of the live-region issue is stated as a WCAG concern rather
than a measured usability result.

## 5. Before/after evidence

| Route | Before | After |
|---|---|---|
| `/student/me` report sentence | `screenshots/student-me__desktop__placeholder-chapters.png` — literal `{chapters}` | `screenshots/student-me__desktop__report-after-fix.png` — real chapter name, page-wide scan for `{...}` returns 0 matches |

## 6. What was not verified in the visual pass

- Speech output: the automation host has only `en-US` voices, so the app's
  correct `speak({lang:"bn-BD"})` call produces no audio here. `NOT VERIFIED`.
- File attach and microphone capture (no OS devices exposed to the browser).
- Teacher AI **generation** submit (a name must be typed first; not triggered).
- Destructive actions (delete account, data download) — deliberately not run.
- Tablet viewport widths and real Android devices.
- Screen-reader behaviour (no assistive technology on this host).
- Long-running states (streaming cancellation, provider outage mid-answer).
