# Feature-Lock Register — Bangla GPT web

**Purpose:** the 100% feature-preservation contract for the frontend renovation
(master-prompt §0.3, §3.3). Nothing in this register may be removed, hidden, orphaned,
mocked, or made less capable. A renovation may change presentation only.

**Method.** Derived from full reads of all 22 page modules and 30 components under
`apps/web/src`, cross-referenced against route gates in `App.tsx` and the API surface in
`docs/route_baseline.md`. Derived 2026-11-11 at HEAD `03dfe21`.

**Evidence status of this register.** Every row is backed by a `file:line` code
reference — that is *source* evidence. Rows are **not** runtime-verified; the runtime
positive-path PASS/FAIL column is maintained in `FEATURE-PARITY-REPORT.md` as browser
tests execute. A row existing here is not a claim that the feature works today.

**ID scheme.** `SHL` shell · `WEL` welcome · `AUTH` login/register/recovery · `LGL` legal ·
`STA` status · `MNT` maintenance · `STU-HOME`/`LEARN`/`READ`/`PRAC`/`ASK`/`CHAT`/`QUIZ`/`ME`
student · `TCH-*` teacher · `PAR` parent · `ADM` admin · `SCH` school.

Preservation-test IDs follow `PT-<FEATURE-ID>` and resolve to an entry in
`TEST-STRATEGY-AND-MATRIX.md`.

---

## 1. Shell (present on every authenticated route) — `AppShell.tsx`

| ID | Feature | Entry point | Action / API | States | Ref |
|---|---|---|---|---|---|
| SHL-NAV-001 | Brand → home | brand button | `navigate(me ? "/" : "/login")` | — | `AppShell.tsx:133-147` |
| SHL-SRCH-001 | Global search (students only) | topbar input | debounced 300 ms `GET /search?q=`; ArrowUp/Down/Home/End/Enter/Escape; "ask in Tutor" → `/student/tutor` `{ask}` | loading, empty, error+retry, unroutable-href, listbox | `SearchBox.tsx:20-253` |
| SHL-PWA-001 | PWA install | download icon, only when `canInstall()` | `promptInstall()` | hidden when not installable | `AppShell.tsx:114-115,155-163` |
| SHL-NOTIF-001 | Notifications | bell | `GET /notifications` on mount + 60 s interval while visible; item click → `markNotificationRead` + navigate | unread badge, error badge, empty, menu keyboard contract | `NotificationBell.tsx:37-258` |
| SHL-NAV-002 | Teacher profile icon | user icon | `navigate("/teacher/profile")` | — | `AppShell.tsx:165-173` |
| SHL-I18N-001 | Language toggle | languages icon | `setLang(bn⇄en)` **in-place re-render** (never remount) | — | `AppShell.tsx:174-187`; `App.tsx:417-427` |
| SHL-THM-001 | Dark mode | sun/moon icon | `toggleTheme()`, `aria-pressed` | — | `AppShell.tsx:188-202` |
| SHL-AUTH-002 | Sign out | logout icon | `signOut()` → `POST /auth/logout` + local scrub | — | `AppShell.tsx:203-211` |
| SHL-NAV-003 | Student bottom nav (5) | Home/Learn/Tutor/Practice/Me | `NavLink`s | active | `AppShell.tsx:36-42,262-278` |
| SHL-NAV-004 | Teacher sidebar (5) | Home/Create/Classes/Assessments/Analytics | `NavLink`s | active | `AppShell.tsx:46-62,218-231` |
| SHL-NAV-005 | Staff sidebar | Dashboard (roleHome), Status | `NavLink`s | — | `AppShell.tsx:234-254` |
| SHL-OFF-001 | Offline banner | automatic | `online`/`offline` events | `role=status` | `AppShell.tsx:64-82` |
| SHL-IMP-001 | Impersonation banner + exit | "exit impersonation" | `exitImpersonation()` → reload `/` | disabled while ending | `AppShell.tsx:84-104` |
| SHL-UPD-001 | New-version banner | "update now" | `applyUpdate()` (SW); never auto-reloads | only when update waiting | `UpdateBanner.tsx:22-44` |
| SHL-SKIP-001 | Skip to content | link | focus `#main-content`; also on public routes | — | `SkipLink.tsx:12-18`; `App.tsx:192` |
| SHL-ERR-001 | Route error boundary | "retry" | `window.location.reload()`; clears on navigation | error card | `AppErrorBoundary.tsx:39-78` |
| SHL-OUT-001 | API-unreachable screen | "retry" | `retrySession()` — keeps token | `role=alert`, focus to heading | `App.tsx:106,126-150` |
| SHL-TITLE-001 | Per-route document title | automatic | `ROUTE_TITLES` longest-prefix match | re-runs on language switch | `App.tsx:454-489` |
| SHL-FOOT-001 | Footer links | Privacy · Terms · Status | `<Link>` | — | `App.tsx:491-504` |
| SHL-SCROLL-001 | Scroll-to-top on route change | automatic | `window.scrollTo(0,0)`, instant (no motion) | — | `App.tsx:446-452` |
| SHL-AUTH-001 | Session probe / bounce | automatic | `fetchMe()`; 401 → `logout()` then `/login?next=<path>` | loading skeleton; unreachable vs signed-out distinguished | `AuthContext.tsx:38-87` |
| SHL-AUTH-003 | `?next=` return path | post-login redirect | same-origin relative only | open-redirect guard | `App.tsx:171-180,217-220` |

## 2. Public and account routes

| ID | Feature | Entry point | Action / API | States | Ref |
|---|---|---|---|---|---|
| WEL-CTA-001 | Register CTA | "শুরু করুন" | `/register` + `track("welcome_cta",{cta:"register"})` | — | `WelcomePage.tsx:44-50` |
| WEL-CTA-002 | Login CTA | login link | `/login` + track | — | `WelcomePage.tsx:51-57` |
| WEL-CONT-001 | Trust row (NCTB / AI / offline) | static | none | — | `WelcomePage.tsx:59-72` |
| WEL-CONT-002 | 4 feature cards | static | none | — | `WelcomePage.tsx:75-107` |
| WEL-CONT-003 | Stat strip (3) + tagline | static | none | — | `WelcomePage.tsx:109-124` |
| AUTH-LOGIN-001 | Password login | submit | `login()` → `POST /auth/login` | busy, error, sync double-submit guard | `LoginPage.tsx:34-82,289-345` |
| AUTH-MFA-001 | MFA step-up OTP | submit after `mfa_required` | `mfaChallenge()` → `POST /auth/mfa/challenge`; `bad_mfa_token` → back to login | busy, error | `LoginPage.tsx:84-116,146-186` |
| AUTH-PWCHG-001 | Forced password change | submit | `changePassword()` → `POST /auth/change-password` | busy, mismatch error | `LoginPage.tsx:118-144,188-252` |
| AUTH-RESEND-001 | Resend verification inline action | link in error block | `resendVerification(email?)` | — | `LoginPage.tsx:317-341` |
| AUTH-NAV-001 | Forgot / Register links | link row | `/forgot`, `/register` | — | `LoginPage.tsx:346-349` |
| REG-001 | Create account | submit | `register()` then `login()` | busy, friendlyError | `RegisterPage.tsx:28-62,172-277` |
| REG-002 | Role select | `<select>` | student/teacher/parent; drives class + consent visibility | — | `RegisterPage.tsx:174-185,224` |
| REG-003 | Class level 1–12 | number input (student only) | `class_level` | — | `RegisterPage.tsx:226-237` |
| REG-004 | Guardian consent | required checkbox | blocks submit; Privacy/Terms `target="_blank"` | required, error | `RegisterPage.tsx:28-33,238-260` |
| REG-005 | Email verification code | submit | `verifyEmail()` → re-`login()` | code ≥16, busy, `invalid_token` | `RegisterPage.tsx:64-82,139-160` |
| REG-006 | Resend verification | ghost button | `resendVerification(email)` | busy, `verifySent` | `RegisterPage.tsx:84-92,161-165` |
| REG-007 | Back to login | link | `/login` | — | `RegisterPage.tsx:166-168` |
| FRG-001 | Tab: reset / verify | two chips | local tab state | — | `ForgotResetPage.tsx:15-28` |
| FRG-002 | Request reset code | submit | `forgotPassword()` | busy, error | `ForgotResetPage.tsx:44-56,72-93` |
| FRG-003 | Complete reset | submit code + new password (≥8) | `resetPassword()`; success → `/student` | busy, error | `ForgotResetPage.tsx:58-70,100-127` |
| FRG-004 | Verify email | submit code (≥16) | `verifyEmail()`; success → `/login` after 800 ms | busy, ok, error | `ForgotResetPage.tsx:138-155,157-182` |
| LGL-001 | Privacy sections (6) | static | none | — | `LegalPage.tsx:3-57,68-80` |
| LGL-002 | Terms sections (3) | static | none | — | `LegalPage.tsx:82-119` |
| LGL-003 | Login/Register links | card footer | `href` | — | `LegalPage.tsx:121-124` |
| STA-001 | Load component health | automatic | `getStatus()` → `GET /status` | loading, error `role=alert`, degraded hero | `StatusPage.tsx:62-86,99-128` |
| STA-002 | Refresh | refresh icon | re-fetch (manual only, no polling) | — | `StatusPage.tsx:133-139` |
| STA-003 | Login link | link | `/login` | — | `StatusPage.tsx:143-145` |
| MNT-001 | Retry / reload | "আবার চেষ্টা" | `window.location.reload()` | — | `MaintenancePage.tsx:22-29` |
| MNT-002 | Status link | "স্ট্যাটাস" | `/status` | — | `MaintenancePage.tsx:30-32` |

## 3. Student — home

| ID | Feature | Entry point | Action / API | States | Ref |
|---|---|---|---|---|---|
| STU-HOME-001 | Ask prompt bar | input + submit, **Enter** (IME-guarded) | `navigate("/student/tutor",{state:{ask}})` | — | `HomePage.tsx:79-82,135-152` |
| STU-HOME-002 | Continue learning card | "পড়া চালিয়ে যান" | `navigate(/student/learn/:subject/:chapter?class=)`; server `continue_learning` else `localStorage.lastChapter` | hidden when none | `HomePage.tsx:84-123,156-186` |
| STU-HOME-003 | Quick tiles ×4 | image-ask, practice, learn, AI tutor | `Link` targets | — | `HomePage.tsx:189-236` |
| STU-HOME-004 | Recommendation card | "মিনি কুইজ" | `navigate("/student/quiz?count=3")` | error+retry (`F-021`) | `HomePage.tsx:239-262` |
| STU-HOME-005 | Progress snapshot | "সম্পূর্ণ অগ্রগতি" | ring avg, streak, top-3 weak chips → `/student/me` | skeleton, error+retry, empty + take-quiz link | `HomePage.tsx:264-332` |
| STU-HOME-006 | Mount queries | automatic | `GET /students/:id/progress`, `/dashboard/summary`, `/students/:id/activity` | per-query loading/error | `HomePage.tsx:22-50` |

## 4. Student — learn and reader

| ID | Feature | Entry point | Action / API | States | Ref |
|---|---|---|---|---|---|
| STU-LEARN-001 | Class chips 1–12 | chip row | `getSubjects(class)`; classes with no corpus are `disabled` with reason in the accessible name | disabled, catalogue load/failure | `LearnPage.tsx:141-171` |
| STU-LEARN-002 | Subject cards | card toggle `aria-pressed` | `getSubjectChapters(subject,class)` + per-subject totals; ring done/total | skeleton, error+retry, `noSubjects` hint, totals-failed retry | `LearnPage.tsx:60-133,173-264` |
| STU-LEARN-003 | Chapter list | "পড়া শুরু" per chapter | `track("chapter_open")` + navigate | loading, error+retry, empty, read-progress bar, done/reading/bookmark badges | `LearnPage.tsx:277-376` |
| STU-LEARN-004 | Offline library | `OfflineLibrary` card, only if copies exist | open record → reader; trash → `deleteChapter` | hidden when empty | `LearnPage.tsx:266-275`; `OfflineLibrary.tsx:22-98` |
| STU-LEARN-005 | Progress query | automatic | `getLearnProgress(class)` | error surfaced | `LearnPage.tsx:70-73` |
| STU-READ-001 | Back | "ফিরে যান" | `navigate(-1)` | — | `LearnChapterPage.tsx:266-271` |
| STU-READ-002 | Bookmark toggle | bookmark button `aria-pressed` | optimistic `upsertLearnProgress({bookmarked})` with rollback + toast | optimistic / rolling back | `LearnChapterPage.tsx:180-200,307-320` |
| STU-READ-003 | Read-aloud (TTS) | "শুনুন"/"থামুন" | `speechSynthesis` bn-BD; `cancel()` stops; `disabled` when no bn voice, tooltip explains | speaking, disabled+tooltip | `LearnChapterPage.tsx:204-245,321-337` |
| STU-READ-004 | Download chapter offline | "ডাউনলোড" | `saveChapter(userId,…)` (IndexedDB, user-scoped, 20-chapter cap) | saving, saved `aria-pressed`, error toast | `LearnChapterPage.tsx:83-84,247-262,339-348` |
| STU-READ-005 | Font size | range 0.8–1.4 step .1 | scales reader text; persists `localStorage.fontScale` | — | `LearnChapterPage.tsx:69-76,349-366` |
| STU-READ-006 | Workspace tabs | Read / Practice / Ask tablist | Arrow ←→↑↓, Home, End, roving tabindex | selected | `LearnChapterPage.tsx:372-414` |
| STU-READ-007 | Auto progress reporting | automatic | 1.5 s → `read_pct:40`; scroll >70 % throttled to furthest; `completed` >90 %; invalidates study caches | silent best-effort | `LearnChapterPage.tsx:127-178` |
| STU-READ-008 | AI next-step suggestion | suggestion button | switches to practice (or ask if completed) | `role=status` | `LearnChapterPage.tsx:444-474` |
| STU-READ-009 | Offline-copy indicator | badge | `fetchChapterWithOfflineFallback` (network-first) | offline badge | `LearnChapterPage.tsx:202-203,338` |
| STU-READ-010 | Load failure | retry | `query.refetch()` | alert | `LearnChapterPage.tsx:278-289` |
| STU-PRAC-001 | Chapter practice | "কুইজ শুরু" | `POST /quizzes` (5 Q, prerequisite-aware) | busy, error | `ChapterPractice.tsx:29-53,165-183` |
| STU-PRAC-002 | Answer options | radio group | shared `QuizOptionGroup` (arrows/Home/End, roving) | — | `ChapterPractice.tsx:125-130`; `QuizOptionGroup.tsx:37-81` |
| STU-PRAC-003 | Pager + finish | prev/next, "শেষ" | `POST /quizzes/:id/submit` | prev disabled at 0, busy on finish | `ChapterPractice.tsx:131-155` |
| STU-PRAC-004 | Result review + restart | score, review rows, "আবার" | `start()` again | — | `ChapterPractice.tsx:74-108` |
| STU-ASK-001 | Chapter-scoped ask | input (Enter, IME-guarded) + "পাঠান" | `POST /tutor/ask` `{question,class_level,subject,chapter,low_data}` | disabled <3 chars, busy, error | `ChapterAsk.tsx:27-47,59-79` |
| STU-ASK-002 | Answer card | automatic | grounded/unsupported badge, `SafeMarkdown`, chapter source; `role=status` | — | `ChapterAsk.tsx:90-111` |

## 5. Student — AI tutor (largest feature surface)

| ID | Feature | Entry point | Action / API | States | Ref |
|---|---|---|---|---|---|
| STU-CHAT-001 | New chat | "নতুন চ্যাট" | `POST /tutor/conversations`, refetch list, load thread | error; consent-403 → notice | `AITutorPage.tsx:198-209,546-548` |
| STU-CHAT-002 | Subject selector | Segmented (Science/Math/Bangla) | per-turn `subject` | — | `AITutorPage.tsx:579-585` |
| STU-CHAT-003 | **Streaming answer** | send (button or **Enter**, IME-guarded) | `POST /tutor/conversations/{id}/messages/stream` (SSE), token batching 80 ms, `onReset` drops orphaned partial on provider failover, final merge by `message_id` | sending, streaming, typing dots, live status region, one polite completion announcement, error | `AITutorPage.tsx:211-381`; `TutorComposer.tsx:144-196`; `TutorThread.tsx:137-151,278-294` |
| STU-CHAT-004 | **Stop / cancel turn** | same control toggles to Stop | aborts conversation POST **and** stream; also aborts on unmount | focus stays on the same element | `AITutorPage.tsx:149-158,673`; `TutorComposer.tsx:180-196` |
| STU-CHAT-005 | Strategy chips ×5 | simple/example/book_language/steps/analogy | per-turn `strategy`, toggles off, tracked | pressed | `TutorComposer.tsx:8-24,79-94` |
| STU-CHAT-006 | Attach photo | paperclip → hidden file input (png/jpeg/webp ≤1.5 MB) | FileReader → base64; preview + remove; cleared only after a successful turn | type/size errors, preview | `AITutorPage.tsx:33-34,465-487`; `TutorComposer.tsx:95-141,162-178` |
| STU-CHAT-007 | Image-intent chips ×4 | solve/explain/check/steps | sends intent text with the image | only when image attached | `TutorComposer.tsx:26-31,122-139` |
| STU-CHAT-008 | Voice input | mic, hidden if unsupported | Web Speech bn-BD appends transcript | listening `aria-pressed` | `VoiceButton.tsx:11-73` |
| STU-CHAT-009 | Empty-state suggestions | 3 chips + image chip | set input / open picker | — | `TutorThread.tsx:69-98` |
| STU-CHAT-010 | Follow-up action bar | simpler / example / quiz me / practice | re-asks previous question with strategy; quiz → `/student/quiz?subject=` | grounded, non-streaming, id≠0 only | `TutorThread.tsx:153-182`; `AITutorPage.tsx:396-399,655-656` |
| STU-CHAT-011 | Rate answer | thumbs up/down | `POST /feedback` `{rating,message_id}` | thanks, error toast, consent-403 | `TutorThread.tsx:229-246`; `AITutorPage.tsx:426-442` |
| STU-CHAT-012 | Re-teach ("আমি বুঝিনি") | chip | re-send with `reteach:true` (server rotates strategy) | grounded only | `TutorThread.tsx:247-251`; `AITutorPage.tsx:401-406` |
| STU-CHAT-013 | Save answer as note | bookmark icon | `createNote({body,source:"tutor",source_ref})` | saved check, error toast | `TutorThread.tsx:252-262`; `AITutorPage.tsx:445-461` |
| STU-CHAT-014 | Regenerate | chip (last message) | `send(q)` again | — | `TutorThread.tsx:263-270`; `AITutorPage.tsx:408-411` |
| STU-CHAT-015 | Evidence modal | source chip | book › chapter › section, page, excerpt; Modal owns Esc/focus-trap/scroll-lock | — | `TutorThread.tsx:213-226`; `EvidenceModal.tsx:22-31` |
| STU-CHAT-016 | Confidence badge | automatic | ≥0.6 teal / <0.6 warn + low-confidence hint | low-confidence | `TutorThread.tsx:183-197` |
| STU-CHAT-017 | Grounding badge | automatic | supported vs "unsupported" when `grounded===false` or `refused_reason`, even with zero sources | — | `TutorThread.tsx:198-212` |
| STU-CHAT-018 | History search | input (Enter, IME-guarded) | `GET /tutor/messages/search?q=`, 6 hits, opens conversation | empty, failure toast | `TutorHistory.tsx:51-91`; `AITutorPage.tsx:490-508` |
| STU-CHAT-019 | Conversation list | chips | open → `GET /tutor/conversations/:id/messages`; **Enter/Escape/blur** commit rename; delete | active chip, list error+retry, rename pencil only on active | `TutorHistory.tsx:95-127`; `AITutorPage.tsx:184-196` |
| STU-CHAT-020 | Rename chat | pencil | `PATCH /tutor/conversations/:id {title}` | error toast, consent-403 | `AITutorPage.tsx:510-524` |
| STU-CHAT-021 | Delete chat | trash | `window.confirm(deleteChatConfirm)` then `DELETE /tutor/conversations/:id` | confirm dialog, error toast | `ConversationChip.tsx:42-49`; `AITutorPage.tsx:526-540` |
| STU-CHAT-022 | Consent re-confirmation | inline warn + "confirm" | `GET /students/:id/consent`; `POST …/consent/reconfirm {accepted:true}` | blocked vs needs_reconfirm, pending, error | `ConsentReconfirmNotice.tsx:30-130`; `AITutorPage.tsx:554-559` |
| STU-CHAT-023 | Handoff in | `state.ask` / quiz explain payload | asks once, then strips state (`replace`) | — | `useTutorHandoff.ts:22-67` |
| STU-CHAT-024 | Back to quiz result | ghost button | `/student/quiz?result=1` | after explain handoff only | `AITutorPage.tsx:561-571` |
| STU-CHAT-025 | Auto-follow stream | scroll | follows only while pinned within 48 px; instant under reduced motion | pinned / detached | `AITutorPage.tsx:36-39,168-182` |
| STU-CHAT-026 | Question length guard | typing | `maxLength=MAX_QUESTION_CHARS` + pre-POST length error; input preserved | inline error | `lib/tutorQuestion.ts`; `TutorComposer.tsx:150` |
| STU-CHAT-027 | Structured answer layout | automatic | simple / example / points / check-question sections when parseable | — | `AssistantContent.tsx:6-40` |

## 6. Student — quiz hub

| ID | Feature | Entry point | Action / API | States | Ref |
|---|---|---|---|---|---|
| STU-QUIZ-001 | Start quiz | "কুইজ শুরু" | `POST /quizzes` `{student_id,class_level,subject,chapter?,num_questions 1–20}` | busy, error, disabled with no profile | `QuizPage.tsx:251-288`; `StartQuizCard.tsx:87-97` |
| STU-QUIZ-002 | Count + subject pickers | selects (3/5/10/15) | feeds start; pre-set by `?count=`/`?subject=` | — | `StartQuizCard.tsx:33-62`; `QuizPage.tsx:47-54` |
| STU-QUIZ-003 | Weak-chapter practice | "দুর্বল বিষয়ে অনুশীলন" | `start({subject,chapter,count:3})` | progress error+retry, no-weak-chapters | `QuizPage.tsx:429-489` |
| STU-QUIZ-004 | Hub tabs | Chapter practice / Revision (due badge) / Assigned (count badge) | **Arrow ←→** roving tabs | — | `QuizPage.tsx:141-171,491-540` |
| STU-QUIZ-005 | Answer / pager | options radio group, prev/next, finish | `QuizOptionGroup`; ProgressRing answered/total | prev disabled at 0, finish busy | `QuizRunner.tsx:51-111` |
| STU-QUIZ-006 | **Unanswered-submit confirmation** | "শেষ" with blanks | warn strip: "Submit anyway" / "Keep answering" | `role=alert` | `QuizRunner.tsx:117-134`; `QuizPage.tsx:104-111` |
| STU-QUIZ-007 | Submit attempt | finish | `POST /quizzes/:id/submit`; sync double-submit guard; invalidates study caches; stores result | busy, consent-403 → notice, error | `QuizPage.tsx:290-342` |
| STU-QUIZ-008 | Result screen | automatic | score ring, correct/total, per-question review, confetti, restart | celebration motion | `QuizResultScreen.tsx:16-111` |
| STU-QUIZ-009 | Explain a wrong answer | "ব্যাখ্যা করুন" | `/student/tutor` `{explain, backToResult:true}` | — | `QuizResultScreen.tsx:82-92`; `QuizPage.tsx:362-365` |
| STU-QUIZ-010 | Grounded re-teach cards | automatic when server sends `reteach[]` | textbook prerequisite chain (never AI text) | — | `ReteachCards.tsx:10-28`; `QuizRunner.tsx:60-64` |
| STU-QUIZ-011 | Revision queue | revision tab, answer buttons | `POST /revision/:id/review {chosen}`, refetch due | pending, failed+retry, empty, busy | `QuizPage.tsx:220-238,542-555`; `RevisionPanel.tsx:23-77` |
| STU-QUIZ-012 | Teacher-assigned work | assigned tab rows | start short test or bulk assignment; disabled when expired/no attempt/already done | expired/done/overdue badges, loading, error+retry, empty | `QuizPage.tsx:195-217,556-570`; `AssignedPanel.tsx:38-119` |
| STU-QUIZ-013 | Draft persistence | automatic | sessionStorage write-through; restored on reload; cleared on submit/start | storage-unavailable tolerated | `QuizPage.tsx:84-95`; `lib/quizDraft.ts` |
| STU-QUIZ-014 | Result restore | `?result=1` | reads `LAST_RESULT_KEY` from sessionStorage | — | `QuizPage.tsx:241-249` |
| STU-QUIZ-015 | Consent notice placement | hub / runner / result | one instance per mounted `<main>` | blocked | `QuizPage.tsx:347-354` |

## 7. Student — account, privacy and settings

| ID | Feature | Entry point | Action / API | States | Ref |
|---|---|---|---|---|---|
| STU-ME-001 | Profile card | automatic | avatar, name, role, class badge | — | `MePage.tsx:278-316` |
| STU-ME-002 | Sign out | "লগআউট" | `signOut()` | — | `MePage.tsx:296-298` |
| STU-ME-003 | Sign out everywhere | "সব জায়গা থেকে" | `revokeAllSessions()` → `POST /users/me/sessions/revoke` then `signOut()` | disabled while busy | `MePage.tsx:299-313` |
| STU-ME-004 | Activity heatmap + streak | card | `GET /students/:id/activity`; shared `ActivityHeatmap` (labelled image) | error+retry; hidden if no data | `MePage.tsx:318-347`; `ActivityHeatmap.tsx:32-70` |
| STU-ME-005 | Saved notes | list, trash per row | `GET /notes`; `DELETE /notes/:id` (no confirmation) | empty, error+retry, delete-failure toast | `MePage.tsx:122-141,349-383` |
| STU-ME-006 | Guardian invite | `ParentInviteCard` | `POST /students/me/invite-codes`; `getLiveInviteCodes`; `revokeInviteCode` (no confirmation) | busy, code+expiry, revoked notice, error | `MePage.tsx:385`; `ParentInviteCard.tsx:23-147` |
| STU-ME-007 | Learning preferences | style select + subject focus (≤60) + Save | `PATCH /students/me/prefs`; refetch prefs+memory | loading, load-failed+retry (form hidden), saving, success/failure | `MePage.tsx:178-205,387-452` |
| STU-ME-008 | AI memory panel | `role="switch"` + "স্মৃতি মুছুন" | `DELETE /students/me/memory`; fact chips from `GET /students/me/memory` | switch, error+retry, no-facts | `MePage.tsx:207-220,454-540` |
| STU-ME-009 | Progress report | weekly/monthly Segmented | `GET /students/me/report` | keeps previous period while loading; error+retry | `MePage.tsx:142-157,542-614` |
| STU-ME-010 | Settings | language select, dark mode, low-data `role="switch"` | `setLang`, `toggleTheme`, `toggleLowData` | pressed/checked | `MePage.tsx:616-665` |
| STU-ME-011 | **Export my data (JSON)** | "ডেটা এক্সপোর্ট" | `GET /users/me/export` → `downloadBlob("bangla-gpt-data-export.json")` | exporting spinner, inline error | `MePage.tsx:235-252,667-683` |
| STU-ME-012 | **Delete account** | "অ্যাকাউন্ট মুছুন" → inline confirm | requires current password; `DELETE /users/me {password}` then `signOut()` | 2-step, confirm disabled until password typed, busy, error | `MePage.tsx:254-270,684-724` |

## 8. Teacher

| ID | Feature | Entry point | Action / API | States | Ref |
|---|---|---|---|---|---|
| TCH-HOME-001 | Load-failure banner | "retry" | refetch classrooms/qpapers/workload | `role=status` | `TeacherHomePage.tsx:109-116` |
| TCH-HOME-002 | Stat row | students / classes / drafts | `/teacher/classrooms`, `/teacher/qpapers`, `/teacher/workload` | drafts "—" on error | `TeacherHomePage.tsx:122-126` |
| TCH-HOME-003 | Quick-create tiles ×5 | tiles | `/teacher/create?kind=question_paper\|short_test\|worksheet\|lesson_plan\|quiz` | — | `TeacherHomePage.tsx:19-25,128-148` |
| TCH-HOME-004 | AI insight line | automatic | `/teacher/weak-matrix?class_level&room_id`, best-effort `retry:false` | risk / weakest / all-ok / no-data | `TeacherHomePage.tsx:54-105,150-161` |
| TCH-HOME-005 | Workload stat | automatic | `getTeacherWorkload()` + methodology tooltip | hidden on failure | `TeacherHomePage.tsx:163-177` |
| TCH-CREATE-001 | Entry grid ×8 | tiles `aria-pressed` | sets `?kind=` | empty-state hint | `CreatePage.tsx:640-682` |
| TCH-CREATE-002 | QP: generate | "তৈরি করুন" | `POST /teacher/qpapers` (class, subject, chapters CSV, exam type, marks, duration, difficulty) | quick/advanced toggle, disabled until exam type + chapters, busy | `CreatePage.tsx:104-286` |
| TCH-CREATE-003 | Short test: assign | "অ্যাসাইন" | `POST /teacher/shorttests` | classroom error+retry, disabled until chapter+room, success count, last-5 list | `CreatePage.tsx:288-464` |
| TCH-CREATE-004 | Lesson plan: generate + edit + **print** | "প্রিন্ট" | `POST /teacher/lesson-plans`; `window.print()` | busy, error, editable sections, `.lp-no-print` | `CreatePage.tsx:466-627` |
| TCH-CREATE-005 | Worksheet / answer key / homework / rubric hub | `CreateHub` Segmented kind | class 1–12, subject, chapter, answer-key question lines | — | `CreateHub.tsx:77-296` |
| TCH-CREATE-006 | Generate now | "এখনই তৈরি" | `POST /teacher/generate/:kind`; PDF button for worksheet/answer_key/lesson_plan | busy, disabled until required fields, error | `CreateHub.tsx:174-195,301-346` |
| TCH-CREATE-007 | Generate in background (job) | "পরে তৈরি করুন" | `POST /teacher/jobs`; polls `/teacher/jobs` every 2.5 s while any job active | queued/generating/validating/ready/failed, jobs table (8) | `CreateHub.tsx:197-213,126-147,348-384` |
| TCH-CREATE-008 | Document library | kind chips, row expand | `GET /teacher/documents?kind&limit=100` | empty, error inline | `CreateHub.tsx:104-113,386-477` |
| TCH-CREATE-009 | **Document PDF download** | "PDF" | `GET /teacher/documents/:id/pdf` → blob | — | `CreateHub.tsx:335-344,429-436` |
| TCH-CREATE-010 | Delete document (2-step) | "মুছুন" → Confirm | `DELETE /teacher/documents/:id` | confirm, busy-disabled, error | `CreateHub.tsx:96-98,215-234,437-464` |
| TCH-CREATE-011 | Workload stat | automatic | `GET /teacher/workload` | hidden on failure | `CreateHub.tsx:149-153,479-488` |
| TCH-CREATE-012 | Quiz entry card | "খুলুন" | `/teacher/assessments?tab=assignments` | — | `CreatePage.tsx:684-697` |
| TCH-QPR-001 | QP stepper | automatic | draft → review → edit → approve → publish | current/done | `QPaperReviewPanel.tsx:16-53` |
| TCH-QPR-002 | Validation checklist | automatic from `qp.meta` | duplicate / difficulty mix / NCTB alignment; neutral when server sent no verdict | ok/warn/neutral | `QPaperReviewPanel.tsx:56-115` |
| TCH-QPR-003 | Per-question review/edit | per-row accept → "review all" | `POST /teacher/qpapers/:id/review {decisions:[accept\|edit+text]}` | busy, error | `QPaperReviewPanel.tsx:250-305,316-325` |
| TCH-QPR-004 | Replace one question | "replace" | `POST …/replace {ref}` | busy | `QPaperReviewPanel.tsx:172-177,293-300` |
| TCH-QPR-005 | Regenerate paper | "regenerate" | `POST …/regenerate` (clears edits) | busy | `QPaperReviewPanel.tsx:179-187,326-333` |
| TCH-QPR-006 | Shuffle options | "shuffle" | `POST …/shuffle` | busy | `QPaperReviewPanel.tsx:189-194,334-341` |
| TCH-QPR-007 | Finalize | "finalize" | `POST …/finalize` | **disabled until every question reviewed** | `QPaperReviewPanel.tsx:196-204,342-349` |
| TCH-QPR-008 | **Paper / answer-key PDF** | "PDF" / "PDF+" | `GET /teacher/qpapers/:id/pdf?kind=paper\|answer` → `downloadBlob("qp-<id>-<kind>.pdf")` | busy, error | `QPaperReviewPanel.tsx:206-219,352-369` |
| TCH-CLASS-001 | Refresh | "রিফ্রেশ" | refetch rooms + roster | error banner `role=alert` | `ClassesPage.tsx:266-268,136-140` |
| TCH-CLASS-002 | Classroom chips | chip per room `aria-pressed` | selects room; clears student detail | empty | `ClassesPage.tsx:277-291` |
| TCH-CLASS-003 | Create classroom | level select + section (≤8) | `POST /teacher/classrooms`; invalidate list | busy, mutation error | `ClassesPage.tsx:142-161,293-322` |
| TCH-CLASS-004 | Class overview | automatic | roster size, chapter count, weak-concept count, health badge | — | `ClassesPage.tsx:330-382` |
| TCH-CLASS-005 | AI insight line | automatic | weak-matrix derived | — | `ClassesPage.tsx:239-260,375-380` |
| TCH-CLASS-006 | Student search | text input | filters roster by name/email (local) | empty result | `ClassesPage.tsx:185-207,490-496` |
| TCH-CLASS-007 | Health filter | chips all/strong/support/risk | local filter | pressed | `ClassesPage.tsx:61-63,497-514` |
| TCH-CLASS-008 | Roster table | "open" per student | `/teacher/classrooms/:id/roster` | invite-pending badge, health dot | `ClassesPage.tsx:94-98,518-574` |
| TCH-CLASS-009 | Student detail | back | ring, mastery, graded count, trend, at-risk badge, weak concepts (6), recommendation | — | `ClassesPage.tsx:384-486` |
| TCH-CLASS-010 | Create support plan | "সাপোর্ট প্ল্যান" | `POST /teacher/support-plans {student_id}` | loading, msg/error | `ClassesPage.tsx:163-179,453-485` |
| TCH-CLASS-011 | **CSV roster import** | textarea + "ইমপোর্ট" | `POST /teacher/classrooms/:id/import {csv_text}`, **120 s timeout**, invalidates 4 caches | disabled until text, busy, per-row result `role=status`, error | `ClassesPage.tsx:579,590-685` |
| TCH-ASM-001 | Tab filter (URL) | Segmented papers/short tests/assignments | `setParams({tab})` | — | `AssessmentsPage.tsx:34,200-224` |
| TCH-ASM-002 | QP library | "open" per paper | `GET /teacher/qpapers`; opens `QPaperReviewPanel`; back button | loading/error+retry/empty, finalized vs needs-review | `AssessmentsPage.tsx:44,233-311` |
| TCH-ASM-003 | Short-test list (read-only) | automatic | `GET /teacher/shorttests`, top 8 | error+retry / empty | `AssessmentsPage.tsx:314-319,601-618` |
| TCH-ASM-004 | Classroom chips | chips | selects room, resets bulk selection | — | `AssessmentsPage.tsx:72-76,326-338` |
| TCH-ASM-005 | Bulk student selection | per-row + select-all checkboxes | local `Set` | indeterminate-ish `allSelected`, reset on room change | `AssessmentsPage.tsx:134-150,349-373` |
| TCH-ASM-006 | Per-student quiz assignment | "assign quiz" | `POST /quizzes {student_id,class_level,subject,num_questions}` | busy, success `#attempt_id` / error | `AssessmentsPage.tsx:114-132,391-401,460-501` |
| TCH-ASM-007 | **Bulk assignment** | chapter + subject + count + `datetime-local` due | `POST /teacher/assignments`; invalidates; clears selection | disabled until selection+chapter+due, busy, success count / error | `AssessmentsPage.tsx:152-181,410-458` |
| TCH-ASM-008 | Assignment results | list (8) + per-card "progress" | `GET /teacher/assignments`, `GET …/:id/progress` (cached per id) | loading, error+retry, empty | `AssessmentsPage.tsx:183-198,503-535` |
| TCH-ASM-009 | Progress detail | automatic | avg/high/low + per-student status table | — | `AssessmentsPage.tsx:543-598` |
| TCH-ANA-001 | Class-level filter | chips (only when >1 level) | drives weak matrix | pressed | `AnalyticsPage.tsx:156,164-181` |
| TCH-ANA-002 | Classroom intelligence | automatic | `/teacher/weak-matrix?class_level=` + `/teacher/curriculum-coverage` | error+retry, empty, top-3 | `AnalyticsPage.tsx:121-154,183-204` |
| TCH-ANA-003 | Weak-matrix heatmap | automatic | concepts × students, accuracy buckets, avg + trend row | error+retry, empty | `AnalyticsPage.tsx:89-99,206-276` |
| TCH-ANA-004 | Curriculum coverage matrix | automatic | class × subject badges | empty | `AnalyticsPage.tsx:68-71,278-325` |
| TCH-ANA-005 | Create support plan | per at-risk student | `POST /teacher/support-plans`, invalidate | busy, msg/error | `AnalyticsPage.tsx:101-117,326-343` |
| TCH-ANA-006 | Support plan list | automatic | weeks + stage labels | empty | `AnalyticsPage.tsx:344-364` |
| TCH-ANA-007 | Capacity / time-saved | automatic | `getTeacherWorkload()` + methodology tooltip | error+retry, loading, no-documents | `AnalyticsPage.tsx:367-392` |
| TCH-PROF-001 | Profile card | automatic | name/email/role | — | `TeacherProfilePage.tsx:29-42` |
| TCH-PROF-002 | Default class preference | select 1–10 + Save | `localStorage["bgpt_teacher_default_class"]` (prefills generators) | saved notice 2 s | `TeacherProfilePage.tsx:9,16-19,44-79` |
| TCH-PROF-003 | Language | select | `setLang` | — | `TeacherProfilePage.tsx:81-98` |
| TCH-PROF-004 | Dark mode | icon button | `toggleTheme()` | — | `TeacherProfilePage.tsx:99-115` |

## 9. Parent, admin, school

| ID | Feature | Entry point | Action / API | States | Ref |
|---|---|---|---|---|---|
| PAR-001 | Link a child by invite code | code input + "রিডিম" | `POST /parents/link/invite {code}` uppercased; invalidates children | busy, ok, error | `ParentDashboard.tsx:99-119,127-164` |
| PAR-002 | Children table | "progress" per row | `GET /parents/me/children`; selects child | empty "—", error | `ParentDashboard.tsx:61-65,166-210` |
| PAR-003 | Child progress | automatic on select | `GET /parents/me/children/:id/progress`; per-chapter weak badges (<60) | per-child loading/error+retry, **no stale cross-child data** | `ParentDashboard.tsx:68-73,212-275` |
| PAR-004 | Child activity | automatic | `GET …/activity`; streak + heatmap | loading/error+retry | `ParentDashboard.tsx:74-79,276-295` |
| PAR-005 | Child report | weekly/monthly Segmented | `GET …/report?period=` | loading/error+retry, keeps previous on switch | `ParentDashboard.tsx:80-88,296-372` |
| ADM-AI-001 | AI quality panel | automatic | `GET /admin/ai/quality?days=30` | loading, error+retry, "unreadable payload"+retry, counts, reasons, by-model | `AiQualityCard.tsx:17-126` |
| ADM-MNT-001 | **Purge expired data (2-step)** | "purge" → confirm | `POST /admin/maintenance/purge?confirm=true` | confirm, busy, `role=status` result / error | `AdminDashboard.tsx:119-136,146-184` |
| ADM-OVR-001 | Overview stats | automatic | `GET /admin/analytics/overview` | load error | `AdminDashboard.tsx:68-71,186-217` |
| ADM-REF-001 | Refusal audit | automatic | `GET /admin/safety/refusals` | loading, error+retry, zero state | `RefusalAuditCard.tsx:55-119` |
| ADM-FB-001 | Feedback triage | open/all filter; note + mark triaged / reopen | `getFeedbackQueue(status)`; `PATCH /admin/feedback/:id` | loading, error+retry, empty, open-count | `FeedbackQueueCard.tsx:20-167` |
| ADM-SCH-001 | Create school | name + "create school" | `POST /admin/schools {name}` | min 2 chars, error to page alert | `SchoolsCard.tsx:63-76,107-120` |
| ADM-SCH-002 | School-level invite | role select + "invite" | `POST /schools/:id/invites`; shows one-time code `role=status` | error msg | `SchoolsCard.tsx:78-90,121-130,171-194` |
| ADM-SCH-003 | View school invites | school-name button (toggle) | `GET /admin/schools/:id/invites` | fetch failure → empty list | `SchoolsCard.tsx:36-61,153-234` |
| ADM-SCH-004 | Revoke invite | "revoke" per unused invite | `DELETE /admin/schools/:id/invites/:inviteId` (no confirmation) | msg/error | `SchoolsCard.tsx:92-102,219-227` |
| ADM-VER-001 | Content versions | automatic | `GET /admin/content/versions` | loading, error+retry, empty | `VersionsCard.tsx:9-61` |
| ADM-USER-001 | User search + role filter | debounced 300 ms + select + "send" | `GET /admin/users?limit=20&offset&q&role`; typing resets offset | load error | `AdminDashboard.tsx:42-67,229-270` |
| ADM-USER-002 | Change user role | per-row role select | `PATCH /admin/users/:id/role`; refresh | error alert | `AdminDashboard.tsx:108-117,289-299` |
| ADM-USER-003 | **Impersonate user** | "impersonate" (hidden for admin/school_admin rows) | `window.prompt` reason (≥3 chars) → `startImpersonation` → hard reload `/` | prompt, cancel, error | `AdminDashboard.tsx:95-106,300-308` |
| ADM-USER-004 | **Pagination** | ‹ / › | `offset ± 20`; prev disabled at 0, next at end; `total — a–b` | disabled edges | `AdminDashboard.tsx:315-333` |
| SCH-OVR-001 | School overview | automatic | `GET /school/overview`: name/code, counts, health buckets, at-risk table (null avg → "N/A") | full-page skeleton, error card `role=alert` | `SchoolDashboard.tsx:13-146` |
| SCH-SEC-001 | Students section | automatic | `getSchoolStudents(100,0)` `GET /school/students` | per-section loading/error+retry | `SchoolSections.tsx:55-116` |
| SCH-SEC-002 | Teachers section | automatic | `getSchoolTeachers` | ditto | `SchoolSections.tsx:118-144` |
| SCH-SEC-003 | Classes section | automatic | `getSchoolClasses` (graded/total, avg) | ditto | `SchoolSections.tsx:146-182` |
| SCH-SEC-004 | Coverage section | automatic | `getSchoolCoverage` (content/uncovered, read/available, completed) | ditto | `SchoolSections.tsx:184-230` |
| SCH-SEC-005 | Analytics section | automatic | `getSchoolAnalytics(30)` | ditto | `SchoolSections.tsx:232-265` |

---

## 10. Untouchable contracts (renovation must not alter)

These are cross-cutting behaviours that a visual redesign could plausibly break. Each gets
an explicit regression test in the plan.

1. **Language switch must re-render, never remount** (`App.tsx:417-427`). Remounting
   discards an in-progress quiz attempt, aborts a streaming answer, and resets half-filled
   forms.
2. **`RequireAuth` decision order** (`App.tsx:92-118`) — especially "API unreachable" before
   "session refused".
3. **Open-redirect guard on `?next=`** (`App.tsx:171-180`).
4. **`logout()` data scrub** (`api.ts:939-973`): server revoke, `USER_STORAGE_KEYS` wipe,
   impersonation tokens, in-flight quiz draft, last-result cache, react-query `clear()`
   (`App.tsx:82`), offline chapter clear. A shared device must never show the next user the
   previous user's dashboards.
5. **Offline copies are user-scoped** (`lib/offlineStore.ts:326`) and synced on login
   (`AuthContext.tsx:47-51`).
6. **Consent gate** — writes 403 until re-confirmed; the UI must surface
   `ConsentReconfirmNotice`, never silently swallow the 403.
7. **Grounding honesty** — a refusal must never be rendered as a normal answer; the
   "unsupported" badge and `refused_reason` path stay reachable (`TutorThread.tsx:198-212`).
8. **Re-teach cards are textbook content, never AI text** (`ReteachCards.tsx:10-28`).
9. **Client-side persistence keys** must survive: `localStorage.lastChapter`,
   `localStorage.fontScale`, `localStorage.bgpt_teacher_default_class`, quiz draft in
   `sessionStorage`, low-data mode, impersonation tokens.
10. **Keyboard contracts** listed in `TEST-STRATEGY-AND-MATRIX.md` §keyboard — six roving-nav
    widgets plus the IME-composing Enter guards.
11. **Print stylesheet** for the lesson plan (`.lp-no-print`, `@media print`, `styles.css:2919`).
12. **Security headers / CSP-sensitive paths**: `lib/safeHref.ts` (allowlisted hrefs),
    `lib/safeMarkdown.tsx` (sanitised rendering). No new `dangerouslySetInnerHTML`.
