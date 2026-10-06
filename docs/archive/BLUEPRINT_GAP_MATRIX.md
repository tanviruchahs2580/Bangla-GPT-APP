# BLUEPRINT_GAP_MATRIX — Master Implementation Prompt v1.0 vs codebase (FINAL)

**Contract:** `Bangla_GPT_NCTB_AI_Tutor_Master_Implementation_Prompt_v1.0.md` · **Initial audit:** 2026-09-08 (pre-work) · **Final update:** 2026-09-08 after all implementation waves + live 5-role browser E2E · **Owner:** ZCode
Statuses: PASS (real, wired, tested) · PARTIAL (shipped with a documented, deliberate scope line) · FAIL (missing) · BLOCKED (external dependency). No PASS is visual-only (blueprint §80): each carries code + test + (where role-reachable) live browser verification.

**Verification evidence for this final pass:** API pytest 537 passed + 6 skipped (exit 0), ruff + mypy clean; web vitest 99 tests / 34 files passed, tsc 0 errors, production build green. Live E2E as all five roles (student, parent, teacher, school_admin, admin) against :4174 + :8000 (mock provider, no quota burn); every finding found while using the app was fixed and re-verified live (see ledger at bottom).

## Design decision logged
Blueprint §7 (green palette, Noto Sans Bengali) supersedes the previous indigo design tokens (owner directive 2026-09-08: "proti ta instruction reflect korte hobe"). Token NAMES stayed stable (`--brand` etc.), values migrated; blueprint's AI Indigo #4F46E5 is the AI accent; Noto Sans Bengali is primary. Engineering protections unchanged: guardian_consent, middleware order, the 4 original SYSTEM_PROMPTs byte-identical (only NEW ANSWER_KEY/HOMEWORK/RUBRIC/WORKSHEET prompts added), alembic append-only, test counts never regressed (API 494→537; web 92→99).

## 1–9. Architecture, roles, UX, design, responsive, navigation
| Requirement | UI | Backend | DB | AI | Test | Status |
|---|---|---|---|---|---|---|
| 5 roles incl. School (school_admin exists) | yes | yes | yes | — | yes | PASS |
| Role controls authorization server-side | — | yes | — | — | yes | PASS |
| Design system per §7 (green palette, Noto Sans Bengali, AI accent) | shipped | — | — | — | build + live | PASS (design wave landed) |
| Role-aware navigation (teacher Create hub + tabs, school sections, parent tabs, student tabs) | shipped | — | — | — | live E2E | PASS |
| Responsive (student mobile-first, school/admin desktop-first) | yes | — | — | — | manual desktop E2E + build | PASS (desktop verified live; 390px matrix = owner QA leg) |
| Accessibility (WCAG AA-ish; aria, focus, contrast) | mostly | — | — | — | manual | PARTIAL (aria/labels/roles live-checked; full WCAG audit = owner QA leg) |

## 11. Auth & onboarding (screens 01–05)
| Requirement | Status |
|---|---|
| 01 Splash / 02 Welcome pre-login screen | PASS (`/welcome` shipped, styles in welcome sheet) |
| 03 Role selection (register: student/teacher/parent + invite-join for school) | PASS (school joins via staff invite redeem; verified: BGPT-DEFAULT invite row) |
| 04 Student profile (name/class + guardian consent) | PASS |
| 05 Learning preference (multi-select, persisted, feeds AI) | PASS (prefs persisted, injected into tutor context; verified in MePage live) |

## 12. Student experience (screens 06–20)
| # | Requirement | Status |
|---|---|---|
| 06 | Home: greeting, AI input, continue, quick actions, recommendation, progress | PASS |
| 07/08 | Learn home + subject page w/ real progress, current/recommended chapter | PASS |
| 09/10 | Chapter workspace (read/practice/ask) + topic content (7-section study material) | PASS |
| 11 | Tutor: streaming, history, context, grounding, retry/stop, regenerate, save, feedback, voice, action chips | PASS (save-to-notes wired per §26 — `note_saved` event + Bookmark toggle; VoiceButton input) |
| 12 | AI answer structured (সহজ/উদাহরণ/মূল/চেক) + practice/other-way actions | PASS |
| 13 | Alternative explanation with user-chosen strategy | PASS (explicit strategy chips → `ChatSendRequest.strategy`; server rotation) |
| 14 | Image question: upload, preview, vision solve/explain/check/step | PASS code + mock refusal path (honest "can't see" on mock); real vision quality BLOCKED on owner `GEMINI_API_KEY` |
| 15 | Practice home: weakness-first categories | PASS |
| 16 | Adaptive practice (Elo difficulty, mistake→learner model) | PASS |
| 17 | Quiz result: score, strong/weak concepts, AI next action | PASS |
| 18 | Progress: streak, time, mastery, weak areas (real data) | PASS |
| 19 | Weekly/monthly AI learning report | PASS (report endpoint + parent/student surfaces; localized suggestion sentence live-checked) |
| 20 | Profile incl. AI memory view/edit/delete/disable | PASS (MePage: memory on/off, items view/remove, clear-all, all wired to prefs/memory API) |

## 13. Teacher experience (screens 21–43)
| # | Requirement | Status |
|---|---|---|
| 21 | Teacher home: counts, classes, pending, quick create, AI insight | PASS (CreateHub unified) |
| 22 | AI copilot free-form (suggested actions) | PARTIAL (free-form lesson-plan copilot shipped + persisted, live-verified; beyond that the CreateHub kind-picker is the suggested-action surface — documented scope line) |
| 23 | Create hub: QP/ShortTest/StudyMaterial/LessonPlan/Quiz/Worksheet/AnswerKey/Rubric/Homework | PASS (live E2E: worksheet, answer_key, homework sync; rubric via async job #4→ready; QP, short test, lesson plan, study material, quiz flows) |
| 24–26 | QP generator NCTB-aware + config + edit/regenerate/replace-single/save, no hardcode | PASS (live: draft→per-question review→replace→finalize; DB status `final`) |
| 27 | AI quality check on paper (alignment/marks/difficulty/dup + flag uncertain) | PASS |
| 28 | A4 preview, PDF export (paper + answer key), print | PASS (PDF endpoint 200 for worksheet/answer_key/lesson_plan live; homework/rubric PDF deliberately unsupported → button hidden, by-design 400 guard) |
| 29 | Short test generator fast path | PASS (rule-based cloze; live: assigned, notification fan-out rows verified in DB) |
| 30 | Study material generator | PASS (versioned + persisted teacher_documents) |
| 31 | Lesson plan generator | PASS (persisted as teacher_documents kind=lesson_plan; live doc #5) |
| 32 | Quiz generator (MCQ/TF/short, difficulty) | PARTIAL (cloze adaptive + difficulty; explicit per-type picker not built — scope line) |
| 33 | Worksheet (basic/intermediate/advanced + answer sheet) | PASS (live E2E + PDF) |
| 34 | Answer key standalone (answers+solutions+marking guide) | PASS (live E2E; paper_id XOR questions pre-validated in UI) |
| 35–38 | Classes list → class overview → student list → individual view | PASS |
| 39 | Assignment center | PARTIAL (no draft state — documented scope line) |
| 40 | Assessment center | PASS (tabs over real status fields) |
| 41 | Assessment result analytics | PASS |
| 42 | Classroom intelligence | PASS |
| 43 | Workload reduction metric, estimated + documented methodology | PASS (live: "প্রায় 45→135 মিনিট" with per-kind minutes; methodology in docs) |

## 14–16. School (44–49), Parent (50–52), Admin (53–56)
| Requirement | Status |
|---|---|
| 44 Overview (students/teachers/classes/health/usage) | PASS (live: tiles 80/3/2, learning-health split, risk list, usage 30d) |
| 45/46 School students/teachers lists (risk, usage) | PASS (live: 80-row student table w/ quizzes+activity, teacher table, class table) |
| 47 Teacher capacity dashboard (augmentation language) | PASS |
| 48 Curriculum coverage (gap identification) school view | PASS (live: per-class coverage table incl. "no content subject" gap row) |
| 49 School analytics (strongest/weakest, at-risk, improving) | PASS (live: health %s, risk trend column, avg score) |
| 50 Parent dashboard | PASS |
| 51 Parent activity feed | PASS |
| 52 Parent reports | PASS (AI suggestion sentence localized; raw-code leak fixed live) |
| 53 Admin control center | PASS (live: counts 134/124/4/2 + 173 quizzes, security audit, schools & invites, content versions) |
| 54 NCTB knowledge mgmt w/ Verified/Needs Review/Invalid | PARTIAL (offline content-QA pipeline + admin content-versions audit shipped; per-chapter status UI = documented scope line) |
| 55 AI quality dashboard (grounding, refusal reasons, feedback, model) | PASS (live: 190 answers / 65 cited / 125 uncited, refusal breakdown, satisfaction, security audit) |
| 56 Knowledge verification chain (answer→sources→chapter→confidence→verification) | PASS (chips + evidence modal + numeric confidence badge) |

## 17–23. AI core
| Requirement | Status |
|---|---|
| 17 Universal composer w/ server-side intent detection | PARTIAL (server-side per-turn intent classification ships — Route SIMPLE/COMPLEX/TOOL, S1.7 — across the tutor + copilot composers; full natural-language intent→generator auto-orchestration from one composer stays a documented scope line) |
| 18 NCTB context selector validated vs KB | PASS |
| 19 Grounding pipeline, no false grounding claims | PASS (gate + refusal on insufficient evidence; live refusal counts on admin board) |
| 20 Source indicator (+advanced source view) | PASS |
| 21 Confidence & uncertainty (numeric + copy) | PASS (`confidence` on message schema, honest formula in `main._answer_confidence`, badge live) |
| 22 AI memory student (view/edit/delete/disable) + teacher context | PASS (MePage full memory controls live) |
| 23 Adaptive loop from real signals | PASS (Elo + mastery + KG gaps) |

## 24–29. Pipelines & offline/voice
| Requirement | Status |
|---|---|
| 24 Generation pipeline w/ validation + no auto-publish (HIL) | PASS (QP finalize gate + review rows live) |
| 25 Replace only Q7 + paper version history | PARTIAL (single-question replace live in review UI; paper revisions re-draft in place — append-only versioning exists for chapter content, not papers — documented scope line) |
| 26 Draft→review→edit→approve→publish persisted | PASS |
| 27 Version history compare/restore/duplicate | PARTIAL (chapter content versioned + history surfaced; paper-level compare/restore/duplicate = documented scope line) |
| 28 Offline: cached chapters, saved notes, sync status | PARTIAL (read cache + saved notes shipped; offline write-queue deliberately out — documented limitation) |
| 29 Voice: input yes, output TTS in reader | PARTIAL (voice input wired; reader TTS in LearnPage; tutor-answer TTS button not built — documented scope line) |

## 30–43. Quality, security, analytics, scale
| Requirement | Status |
|---|---|
| 31 Friendly errors + retry | PASS (raw API JSON leak fixed live via friendlyError(rawDetail); Bengali copy + retry action) |
| 32 Security basics (authn/z, rate limit, injection, audit, PII) | PASS |
| 32/68 School tenant isolation on ALL teacher/school queries | PASS (W2 scoping fix; tenancy tests in suite; live school_admin sees only school 2 data) |
| 33 Child safety categories + hotlines | PASS |
| 34 Event-driven analytics w/ real persisted events | PASS (AnalyticsEventRow persisted + queried by dashboards; `track()` everywhere) |
| 35/64 Perf (lazy, cache, pagination, streaming) | PASS (route-level code-split chunks visible in build) |
| 36 Configurable model routing small/medium/large | PASS |
| 37 Async generation Queued→Generating→Validating→Ready | PASS (ai_jobs; live: rubric job #4 queued→ready via bell + library) |
| 38 Persistent entities (analytics_event, notification, ai_job, saved_notes, teacher_documents) | PASS (migration appended at head b7e3f5a8c2d4; rows verified in live DB) |
| 39 API design | PASS |
| 40 AI provider abstraction + router + verification services | PASS (mock/gemini swap verified via `/ready` provider field — zero code change) |
| 41 RAG ingestion→retrieval w/ rich metadata | PASS |
| 42 NCTB governance (imported→verified pipeline) | PARTIAL (offline QA pipeline; UI surfacing = same scope line as §54) |
| 43 Server-side global search | PASS |

## 44–52. Notifications, saved content, gamification, components, tests
| Requirement | Status |
|---|---|
| 44 Contextual notifications | PASS in-app (bell verified per role live incl. localized empty state + raw-code fallback regression test; push=BLOCKED owner FCM) |
| 45 Saved content student+teacher persistent | PASS (saved_notes from tutor; teacher_documents library + type filters live) |
| 46 Minimal gamification (streak/achievement/mastery, no dark patterns) | PASS (intentionally minimal by design) |
| 47/48 Reusable component + AI component set | PASS (ui kit, ConfidenceBadge, NotificationBell, EvidenceModal, VoiceButton, CreateHub) |
| 50 Loading/empty/error/success everywhere | PASS |
| 51 No fake functionality in prod paths | PASS (mock is opt-in dev/CI provider, honest [mock] prefix, refusal on vision) |
| 52/53 Unit+integration+E2E suites + gates | PASS (API 537+6 skipped; web 99/99 incl. notification-bell crash regression; live 5-role browser E2E this pass) |

## 54–59. QA dimensions
Responsive QA — desktop fully verified live across all 5 roles; 390/768 matrix remains an owner QA-leg item. Accessibility QA — PARTIAL (labels/roles/aria-checked live in snapshots; formal audit = owner). Security QA — PASS (tenancy + existing suite). AI QA — PASS (golden eval + eval gate). Observability — PASS (structured logs, request IDs, Prometheus; `/ready` provider truth-check).

## 60–85. Remaining contract items
| Requirement | Status |
|---|---|
| 60 Feature flags for risky capabilities | PARTIAL (env settings incl. vision/voice gates; no central flag registry — documented) |
| 61 i18n structured strings | PASS (typed bn/en dicts; the Bengali-only spots found in live QA — errors.ts fallbacks, admin triage labels, notification codes — are now localized; unknown wire codes degrade to raw code, never crash) |
| 66 Teacher-shortage framing (augmentation language) | PASS |
| 70/71/72 Student/Teacher/School E2E journeys | PASS (executed live this pass, all roles) |
| 77 No fake data in prod flows | PASS |
| 79 Documentation set | PASS (this matrix + reports; README stays at last released version until owner ships) |
| 83 Release gate honesty | enforced in this matrix |

## E2E findings ledger (live user-testing this pass — all fixed + re-verified)
1. Parent report showed raw `sugg_*` code → localized suggestion sentences (i18n + helper).
2. Notification bell crashed the whole app on an unknown code → t() guard + snake→camel dict lookup + raw-code fallback + regression test (R12-clean: app fixed, test kept).
3. Workload card rendered literal `{n}` → vars passed to t().
4. CreateHub surfaced raw FastAPI validation JSON → `friendlyError(rawDetail)` Bengali copy + action.
5. Homework/rubric require chapter server-side but UI said optional → button gating + "Chapter (required)" label.
6. Untranslated admin triage labels (bn locale) → localized via typed i18n.
7. Live server silently ran provider=gemini (quota directive violation) → relaunched with `LLM_PROVIDER=mock` (process env; .env untouched), truth-checked via `/ready`.

## BLOCKED (external dependencies, exact owner action)
- Real vision quality: needs `GEMINI_API_KEY` with vision-capable model (contract + honest mock refusal shipped; owner key = live quality).
- Push notifications (FCM): owner GCP/FCM credentials (in-app notifications shipped instead).
- NCTB real textbook corpus: owner PDFs + permission (S6.1 human gate).
- Deploy/staging legs and commit/push/CI-CD: owner (explicitly excluded this phase by directive).
