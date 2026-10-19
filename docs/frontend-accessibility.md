# Frontend accessibility: what is verified automatically, and the manual pass sheet

Owner-facing record for the Domain-G accessibility items (G-10..G-14, G-23).
Written 2026-10-19 for the R3 audit pass. **The screen-reader pass is not
claimed here**: no screen reader was driven and observed during this pass, and
the manual sheet at the bottom is the work that remains for a human. Everything
above the sheet is executable and reproducible from this repository.

## 1. What runs automatically, and where

| Check | Where | Command |
|---|---|---|
| axe, WCAG 2.0/2.1/2.2 A/AA, every route of `src/main.tsx` x light/dark x bn/en, serious+critical = 0 | `apps/web/e2e/axe.spec.ts` | `npx playwright test axe.spec.ts` |
| axe in jsdom (component level, no layout) | `apps/web/src/test/axeSweep.test.tsx`, `axeWelcome.test.tsx` | `npx vitest run` |
| Keyboard-only flows: skip link moves focus into `main`, Enter-only login, visible focus at every Tab stop, dialog trap/Escape/restore, no keyboard traps | `apps/web/e2e/keyboard.spec.ts` | `npx playwright test keyboard.spec.ts` |
| Landmarks, `html lang` per language, the tutor's single polite live region and its one announcement per completed answer, reviewed ARIA-snapshot baselines | `apps/web/e2e/screen-reader.spec.ts` + `e2e/__screenshots__/screen-reader.spec.ts/*.aria.yml` | `npx playwright test screen-reader.spec.ts` |
| Reflow at 320/360/390/768/1024/1280/1440 px, 200% text resize, no horizontal scrolling, nothing painting outside the viewport | `apps/web/e2e/reflow.spec.ts` | `npx playwright test reflow.spec.ts` |
| Reduced motion honoured (durations collapse to 0, content still renders) | `apps/web/e2e/reflow.spec.ts` | same |
| Every visible control has an accessible name on every route | `apps/web/e2e/crawl.spec.ts` | `npx playwright test crawl.spec.ts` |
| Bangla conjuncts unclipped, no letter-spacing on Bangla, no weight without a loaded face, `Intl bn-BD` behaviour — in Chromium, Firefox and WebKit | `apps/web/e2e/engines.spec.ts` | `npx playwright test -c playwright.engines.config.ts` |

jsx-a11y rules also run as errors in ESLint (`npm run lint`, `--max-warnings 0`).

### Colour contrast (G-13)

- Lighthouse's `color-contrast` audit passes on all six public routes in Bangla,
  light theme, mobile emulation (raw JSON under `.audit/evidence/`).
- The dark-theme failure found earlier (white-on-accent at 1.4:1-1.7:1) was
  fixed by the `--on-brand` / `--on-teal` / `--on-ai` / `--on-danger` tokens;
  the axe sweep now runs green in dark mode on every route.
- Measured ratios for the semantic trio are recorded inline in
  `src/styles.css` (`--danger` 5.14:1, `--warn` 5.56:1, `--ok` 6.32:1 on their
  soft backgrounds, light theme).
- **Colour is never the only signal** where status is shown: badges carry text
  ("ডাউনলোড হয়েছে" / "Downloaded"), warnings are `role="alert"` text, the
  offline banner is a labelled region, and the activity heat-map cells carry a
  `title` describing the day's counts.

### Target size (G-13, WCAG 2.2)

- The register consent checkbox — the one serious target-size failure axe
  reported — is now 24x24 CSS px minimum (`.consent-check` in `styles.css`).
- Interactive controls that are used on touch (primary buttons, nav items,
  list rows) carry `min-height: 44px` in the shell styles.
- 24x24 is the WCAG 2.2 minimum; the 44 px "preferred on touch" bar is met on
  the primary controls but not audited exhaustively per control.

## 2. Media (G-14)

| Rule | State |
|---|---|
| Every `<img>` has an `alt` attribute | Yes. Two renderers: the chat attachment preview (`alt=""`, decorative — the user chose the image and the intent chips beside it carry the meaning) and model-authored markdown images (`alt={alt ?? ""}` in `lib/safeMarkdown.tsx`, `loading="lazy"`). The crawl spec asserts nothing renders an `<img>` without the attribute. |
| Decorative images hidden from assistive technology | Yes: the logo (`BrandMark`) is `aria-hidden` unless given a `title`, the empty-state mark is `aria-hidden`, all icon-only controls use `aria-label` with `aria-hidden` on the glyph. |
| Captions or transcripts for audio/video | **N/A — there is no audio or video element in the app** (`rg "<audio|<video|<track" src` returns nothing). Chapter audio is the browser's speech synthesis (TTS), not a media element; its "transcript" is the chapter text on screen, which is the source of the speech. If a recorded audio or video lesson is ever added, this line becomes a blocker rather than an N/A. |
| Background imagery is purposeful | Three photographs are used as backgrounds (login splash desktop/mobile, student-home); they are re-encoded and referenced from `styles.css`. They are decorative CSS backgrounds, not content images, so they correctly carry no alt text. No stock or placeholder imagery is used. |
| TTS controls | `aria-label` + `aria-pressed` on the Listen/Stop button, `aria-describedby` pointing at the notice region (`role="status"`) when a Bangla voice is missing; rate and pitch sliders are labelled. |

## 3. Manual screen-reader pass sheet (G-12) — for the owner

The item asks for "notes naming the tool and version". This sheet is what that
note should record. Windows Narrator is present on the audit host but its
speech cannot be observed or captured there, and a screen reader cannot be
driven headlessly against a specific window; NVDA, VoiceOver or TalkBack on a
device the reviewer can hear is equally acceptable.

Run order and what to listen for. Fill in the "Result" column with what you
actually heard — "pass" alone is not a result for this item.

| # | Screen | Steps | What must be announced | Result |
|---|---|---|---|---|
| 1 | `/login` | Load, press `Tab` once, `Enter` | "Skip to main content, link" first; Enter moves focus into the main region (the next Tab reaches the page, not the shell) | |
| 2 | `/login` | Tab through the form | Each field announced with its visible label; the password field must not be read as an unlabelled edit box | |
| 3 | `/login` | Submit an empty form | The error is announced as an alert and the focused field is described by it (`aria-invalid` + `aria-describedby`) | |
| 4 | `/register` (student) | Tab to the consent checkbox | Announced with its label ("I agree to the privacy policy..."), state "not checked", and the size must be reachable (24x24) | |
| 5 | `/student` | Load the dashboard | One "main" landmark, one "navigation" landmark; heading levels descend without skipping (h1 then h2/h3) | |
| 6 | `/student/tutor` | Ask a question and let the answer stream | While streaming: **no** announcement per token. When the answer completes: one announcement of the completed answer | |
| 7 | `/student/tutor` | Activate a source chip | Dialog announced as a dialog with its name; Tab stays inside; `Escape` closes it and focus returns to the chip | |
| 8 | `/student/tutor` | Press the thumbs-down button | The reason dialog is announced; skipping it still records the rating | |
| 9 | `/student/learn/<subject>/<chapter>` | Open a chapter, press Listen | The reader reports the missing-Bangla-voice message *only* when the device really has none; the rate/pitch sliders announce their label and value | |
| 10 | Any page | Switch the language toggle | `html lang` changes to `en`; Bangla segments inside the English page are still announced as Bangla (`lang="bn"` on the segment) | |
| 11 | Any page | Go offline (disable the network) | The offline banner is announced once ("Offline — retry when the connection returns"), not repeatedly | |
| 12 | `/teacher/classes` (or any list) | Tab through rows | Rows are reachable and announced with their content; a row is activated by `Enter`/`Space` where it is clickable | |

Record: screen reader name and version, browser and version, OS, the date, and
for each row the actual announcement. Any row that reads "unlabelled", repeats
itself per token, or cannot be reached by Tab is a defect to file against this
repository, not a pass.

## 4. Known gaps in the automated evidence

1. **No screen-reader run.** See the sheet above; this is the only G-12
   requirement not met here.
2. **No real touch device.** The 44 px touch-target guidance is met by CSS
   on primary controls and by the target-size fix on the checkbox, but no
   physical Android/iOS device was measured. Playwright's Desktop Safari
   (WebKit) is not iOS.
3. **Contrast is measured by Lighthouse on six public routes**; the role
   dashboards are covered by axe's `color-contrast` rule (which does compute
   contrast in a real browser) rather than by a separate Lighthouse run.
4. **Focus appearance** is asserted as "an outline or box-shadow exists"
   (`keyboard.spec.ts`), which is WCAG 2.4.7-level evidence. WCAG 2.2's
   focus-appearance criteria (2.4.11/2.4.13: area, contrast, unobscured) are
   not measured.
