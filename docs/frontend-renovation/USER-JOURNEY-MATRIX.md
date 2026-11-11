# User Journey Matrix — Bangla GPT frontend renovation

Per-role journeys with their entry point, task, states, permission boundary and negative
access test. Built from `App.tsx`'s route gates, `AuthContext.tsx`'s session handling and the
per-page capability inventory in `FEATURE-LOCK-REGISTER.md`.

**Coverage status column is honest and current.** `PASS` means a named test actually ran in
this delivery and passed; `NOT RUN` means it did not. Nothing is marked PASS on the strength
of the code existing.

---

## 1. Role homes and the guard

`ROLE_HOME` (`AuthContext.tsx:117-123`) maps `student → /student`, `teacher → /teacher`,
`parent → /parent`, `admin → /admin`, `school_admin → /school`. A wrong-role request is
redirected to the requester's own home, never shown the requested page (`App.tsx:110-111`).

`RequireAuth` (`App.tsx:84-119`) decides in this order, and the order is itself the contract:

| Step | Condition | Outcome |
|---:|---|---|
| 1 | no token | → `/login` |
| 2 | session loading | polite loading region + skeletons; **shell not rendered** |
| 3 | `apiUnreachable` | the "API unreachable" screen — **token kept**, retry offered |
| 4 | `me === null` | → `/login` (session genuinely refused) |
| 5 | role mismatch | → own role home |
| 6 | otherwise | `AppShell` + `RouteErrorBoundary` + page |

Step 3 before step 4 is deliberate: a dead backend must not look to a child like their
account was closed. **No renovation change touches this ordering.**

## 2. Journeys

### J-01 Anonymous visitor → registration → student home

| Step | Detail |
|---|---|
| Entry | `/welcome` (`WEL-CTA-001`) → `/register` |
| Task | Create an account: role select, class level (students), required guardian-consent checkbox |
| States | busy, `friendlyError`, consent required, verification-code screen, resend |
| Success | Email verification → auto sign-in → `/student` |
| Recovery | `resendVerification`; back-to-login link |
| Permission boundary | Public route; an authenticated visitor is redirected to their role home |
| Negative test | With consent unchecked, submit must be blocked |
| Evidence | `e2e/smoke.spec.ts:86` "a guardian-consented student registers and lands on the student home" — **PASS** |

### J-02 Session sign-in and sign-out (all five roles)

| Step | Detail |
|---|---|
| Entry | `/login` (`AUTH-LOGIN-001`) |
| Task | Password sign-in; MFA step-up if the server answers `mfa_required`; forced password change |
| States | busy, error, `bad_mfa_token` returns to the password step, unverified-email offers resend |
| Success | Token stored (`bgpt_token`) → role home |
| Recovery | `?next=` returns the user to the interrupted route; API-unreachable keeps the token and offers retry |
| Permission boundary | Anonymous-only route; signed-in visitors are redirected |
| Negative test | Wrong credentials must not navigate; the error must be announced |
| Evidence | `e2e/smoke.spec.ts:66` (student, **PASS**), `e2e/smoke.spec.ts:208` (teacher, **PASS**), `e2e/session.spec.ts`, `e2e/w2-session.spec.ts` — **PARTIALLY VERIFIED** (the `w2-session` case needing `E2E_WEB=preview` was not run) |
| Renovation note | **R-12** changed the resend control from an anchor to a button. Handler, argument and outcome unchanged; newly covered by `login.test.tsx` |

### J-03 Student asks the tutor and reads a streamed, grounded answer

| Step | Detail |
|---|---|
| Entry | `/student` prompt bar (`STU-HOME-001`) or `/student/tutor` (`STU-CHAT-003`) |
| Task | Ask a Bangla question; optionally attach a photo, pick a strategy, use voice input |
| States | sending → streaming (token batches) → complete; typing dots; one polite completion announcement; Stop toggles into the same control; provider-failover drops the orphaned partial |
| Success | Grounded answer with confidence and grounding badges; source chip opens the evidence modal |
| Recovery | **Stop/cancel** aborts conversation POST *and* stream; retry; consent-403 surfaces the re-confirmation notice |
| Permission boundary | `role="student"` |
| Negative test | An out-of-corpus question must be **refused** with the grounding message, never answered |
| Evidence | `e2e/smoke.spec.ts:113` (streamed answer, **PASS**), `e2e/smoke.spec.ts:151` (refusal, **PASS**) |
| Renovation note | The grounding badge is a locked contract — a refusal must never render as a normal answer |

### J-04 Student learns from a chapter and practises it

| Step | Detail |
|---|---|
| Entry | `/student/learn` → class chip → subject card → `/student/learn/:subject/:chapter` |
| Task | Read a chapter; bookmark; read aloud; download for offline; set font size; then Practice or Ask |
| States | catalogue loading/failure; classes without corpus content are `disabled` with the reason in the accessible name; reader loading/error+retry; offline-copy badge; auto progress reporting (40 % on open, furthest scrolled, complete >90 %) |
| Success | Progress recorded; grounded practice quiz started from the chapter |
| Recovery | Bookmark is optimistic with rollback + toast; failed progress totals offer retry |
| Permission boundary | `role="student"`; deep link carries `?class=` |
| Evidence | `e2e/qa-flows.spec.ts`, `e2e/w2-flows*.spec.ts` exist; `e2e/visual.spec.ts` covers the visual state — **PARTIALLY VERIFIED** |
| Renovation note | **R-06** added failure feedback to the offline-copy delete. `offlineLibraryCopy.test.tsx` — **PASS** |

### J-05 Student completes a quiz attempt

| Step | Detail |
|---|---|
| Entry | `/student/quiz` (`STU-QUIZ-001`), or a chapter, or a weak-chapter recommendation, or a teacher assignment |
| Task | Answer with the shared radio group, pager, finish |
| States | draft persisted to `sessionStorage` and restored on reload; unanswered-submit confirmation ("Submit anyway" / "Keep answering"); submit busy with a double-submit guard; consent-403 notice |
| Success | Result screen: score ring, per-question review, grounded re-teach cards (textbook content, never AI text) |
| Recovery | Explain-a-wrong-answer hands off to the tutor with `{explain, backToResult}`; `?result=1` restores the last result |
| Permission boundary | `role="student"` |
| Negative test | Finalising a paper is disabled until every question is reviewed (teacher side, `TCH-QPR-007`) |
| Evidence | `e2e/smoke.spec.ts:177` "completes a quiz attempt end to end" — **PASS** |

### J-06 Student manages account, privacy and data

| Step | Detail |
|---|---|
| Entry | `/student/me` |
| Task | Saved notes, guardian invite, learning preferences, AI memory, report, settings, **JSON data export**, **account deletion** |
| States | prefs load-failure hides the form behind a retry; memory switch; export spinner; 2-step delete requiring the current password before the confirm enables |
| Permission boundary | `role="student"`; deletion requires re-authentication |
| Evidence | `mePrefsAndMutations.test.tsx`, `meReport.test.tsx`, `dataExport.test.tsx`, `savedNotes.test.tsx` — unit-level **PASS**; not driven end to end in a browser in this delivery |

### J-07 Teacher creates content

| Step | Detail |
|---|---|
| Entry | `/teacher` quick tiles → `/teacher/create?kind=…` |
| Task | QP, short test, lesson plan, worksheet, answer key, homework, rubric |
| States | generate-now vs generate-in-background (job polled every 2.5 s only while in flight); document library with kind filter; PDF export; 2-step document delete |
| Permission boundary | `role="teacher"` |
| Evidence | `createhub.test.tsx`, `lessonplan.test.tsx`, `shorttest.test.tsx`, `qpapers.test.tsx`, `qpaperDownload.test.tsx` — unit-level **PASS** |
| Renovation note | **R-11** corrected the per-question accept label; `qpapers.test.tsx` re-run **PASS** |

### J-08 Teacher runs a class

| Step | Detail |
|---|---|
| Entry | `/teacher/classes` |
| Task | Create a classroom; search and filter the roster; open a student; create a support plan; **CSV roster import** (120 s timeout) |
| States | rooms/roster error banner with refresh; empty roster; invite-pending badge; per-row import result `role="status"` |
| Permission boundary | `role="teacher"`; tenancy enforced server-side |
| Evidence | `teacherClassrooms.test.tsx`, `bulkassign.test.tsx`, `weakmatrix.test.tsx` — unit-level **PASS** |

### J-09 Teacher assesses a class

| Step | Detail |
|---|---|
| Entry | `/teacher/assessments?tab=` |
| Task | QP library + review panel; short-test list; per-student quiz assignment; bulk assignment with a due date; assignment progress detail |
| States | tabs from the URL; bulk selection with select-all; disabled until selection+chapter+due; per-assignment progress cached per id |
| Permission boundary | `role="teacher"` |
| Evidence | `assessmentTabs.test.tsx`, `analyticsWorkload.test.tsx` — unit-level **PASS** |

### J-10 Teacher reads analytics

| Step | Detail |
|---|---|
| Entry | `/teacher/analytics` |
| Task | Class-level filter; weak-concept heatmap (concepts × students); curriculum-coverage matrix; at-risk actions; capacity/time-saved with methodology tooltip |
| States | error+retry per block; empty states; health meaning carried by colour **plus** `title` and visually-hidden text, never colour alone |
| Evidence | `analytics.test.tsx`, `analyticsWorkload.test.tsx` — unit-level **PASS** |

### J-11 Parent follows a child

| Step | Detail |
|---|---|
| Entry | `/parent` (`PAR-001`) |
| Task | Link a child by invite code; view per-chapter progress; activity heatmap; weekly/monthly report |
| States | link busy/ok/error; **per-child loading and error, with no stale cross-child data on switch**; report keeps the previous period while loading |
| Permission boundary | `role="parent"`. Must never expose another role's data or actions |
| Negative test | Child selection must not leak the previous child's figures during the new fetch |
| Evidence | `parentDashboard.test.tsx`, `parentInviteCard.test.tsx` — unit-level **PASS** |

### J-12 Platform admin operates the platform

| Step | Detail |
|---|---|
| Entry | `/admin` |
| Task | AI quality, refusal audit, feedback triage, purge expired data (2-step), create school, school invites, content versions, user search + role filter, change role, **impersonate with a reason**, pagination |
| States | per-card loading/error+retry; "unreadable payload" + retry; pagination edges disabled |
| Permission boundary | `role="admin"`. Impersonation is hidden for admin/school_admin rows and requires a ≥3-character reason |
| Negative test | Invite-list fetch failure must be reported, not shown as empty |
| Evidence | `admincenter.test.tsx` **6/6 PASS** including the new failed-invite case (R-03), and `aiQualityStates`, `refusalaudit`, `supportops`, `workspace` |
| Renovation note | **R-03** and a carried finding that `/school` is not reachable by `admin` (**R-14**) |

### J-13 School admin reviews a school

| Step | Detail |
|---|---|
| Entry | `/school` |
| Task | Overview (counts, health buckets, at-risk table with a null-average "N/A" badge) + five independent sections: students, teachers, classes, coverage, analytics |
| States | full-page skeleton; `role="alert"` error card; **per-section** loading/error+retry so one failing section does not blank the page |
| Permission boundary | `role="school_admin"`; cross-school access returns 403 server-side |
| Evidence | `schooldashboard.test.tsx`, `schoolSections.test.tsx` — unit-level **PASS** |

### J-14 Public and support surfaces

| Route | Journey | Evidence |
|---|---|---|
| `/welcome` | marketing entry, two tracked CTAs | `welcome.test.tsx`, `landingStats.test.ts` **PASS**; `visual.spec.ts` 12 snapshots **PASS** |
| `/login` | see J-02 | 12 `visual.spec.ts` snapshots **PASS** |
| `/forgot` | reset *and* verify-email tabs, both with code flows | `forgotReset.test.tsx` **PASS** |
| `/privacy`, `/terms` | bilingual legal sections | `legalPrivacy.test.tsx` (11 tests) **PASS** |
| `/status` | component health, manual refresh only (no polling) | `statusPageLocalization.test.tsx` **PASS** |
| `/maintenance` | deployment rewrite target: reload + status link | — **NOT RUN** in a browser |
| `*` | not-found page | `routeBoundaries.test.tsx` **PASS** |

## 3. Coverage summary — what is proven and what is not

| Measure | Result |
|---|---|
| Roles with a verified sign-in journey | 2 of 5 driven end to end in a browser (student, teacher); the other three covered by automated a11y role sweeps and unit tests but **not** driven through a full journey in this delivery |
| Critical journeys (J-02, J-03, J-05) | **PASS** in a real browser |
| Journeys verified only at unit/component level | J-04 (partial), J-06, J-07, J-08, J-09, J-10, J-11, J-12, J-13 |
| Journeys not verified at all in a browser | `/maintenance` |
| Permission negative paths | server-side tenancy and role rejection are asserted by the API's own tests; **the frontend negative access tests (direct URL as the wrong role) were not re-executed** for every role×route pair |
| Android / native | **BLOCKED** — no toolchain on this machine |

This is why the verdict in `FINAL-DELIVERY-REPORT.md` is not `COMPLETED — VERIFIED`.
