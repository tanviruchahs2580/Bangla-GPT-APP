# FINAL EXECUTION REPORT — v0.3.0 "Product-Complete MVP"

> Companion to the earlier `FINAL_ENTERPRISE_VALIDATION_REPORT.md` (v0.2.1,
> engineering verdict B). That report proved the *infrastructure*; this one
> closes the *product* gaps identified in the independent review that
> followed it. Every step from the review was executed in-repo or converted
> into an owner-action artifact; nothing was dropped.

## 1. Verdict

**v0.2.1 = deployable skeleton → v0.3.0 = usable product MVP.**
The core loop a real student needs — chat with a tutor, get cited answers,
take quizzes, see progress — now works end-to-end across classes 6–10, in a
redesigned mobile-first UI, behind child-safety guardrails.

## 2. Step-by-step execution matrix (review step → what was done → proof)

### Phase A — Product core

| Step | Executed | Proof |
|---|---|---|
| **A1 Corpus expansion** | Synthetic original Bangla corpus grew 2 files → 12 files: classes **6–10**, subjects science/mathematics/bangla; loader manifest updated | `test_sample_corpus_covers_classes_6_to_10` ✓; live C9 quiz now returns **5/5 questions** (was `"No quiz could be generated"`) |
| **A2 Hybrid retrieval** | New `retrieval/hybrid.py`: light Bangla stemmer, curated query expansion, char-trigram fallback blended into BM25; grounding gate upgraded to best-of-hits + stem matching | `test_paraphrased_question_still_grounds` ("গাছ কীভাবে নিজের খাদ্য তৈরি করে?" → grounded=True) |
| **A3 Chat + history + SSE** | `conversations`/`chat_messages` tables (+alembic), conversation CRUD, history-aware prompt (last N turns), `POST .../messages` JSON turn and `.../messages/stream` SSE (`token`…`done` events); ownership enforced (IDOR-tested) | Live SSE captured **27 token events + done** over HTTP; `test_chat_create_send_history_and_ownership`, `test_chat_stream_sse_events` ✓ |
| **A4 Quiz honesty fix** | Second-pass cloze harvesting fills requested count; response carries `requested` + machine note `partial_quiz:{got}` when short; error codes on empty/mismatch | `test_quiz_reports_requested_count`; live C9 quiz 5/5 with no note |
| **A5 Safety + citation verify** | `services/safety.py`: category regex screen (self-harm w/ helpline, weapons, drugs, sexual, violence, personal-data) → supportive refusals with `refused_reason`; user-question wrapped as data in prompt (injection hardening); post-generation citation coverage signal | Live UTF-8 test: self-harm question → `refused_reason=self_harm` + helpline copy; `test_unsafe_questions_get_supportive_refusal` ×3, `test_curriculum_question_is_not_falsely_blocked` ✓ |

### Phase B — Frontend international standard

| Step | Executed | Proof |
|---|---|---|
| **B6 Design system** | Full `styles.css` rewrite: token system, dark mode (auto+manual), buttons/inputs/badges/tables/stats/skeletons/modals; self-hosted **Noto Sans Bengali + Hind Siliguri** via @fontsource (bundled woff2); favicon/OG/description/theme-color meta | Build emits font assets + 15 KB CSS; index.html complete |
| **B7 Chat-first student UI** | StudentDashboard rebuilt: conversation sidebar, streaming bubbles with typing dots, inline citations, 👍👎 per answer, quiz card with partial-note, progress bars, modal account deletion + export link | Manual E2E against live API |
| **B8 Auth/session UX** | Machine-code → localized copy map (`errors.ts`); pending spinners everywhere; show/hide password; autocomplete attrs; global 401 handler; resend-verification link | `login.test.tsx` asserts friendly copy renders from `email_unverified` |
| **B9 i18n scaffold** | Typed bn/en dictionaries + `t()` with interpolation + runtime language toggle in header | `core.test.ts` interpolation test |
| **B10 PWA** | `manifest.webmanifest` (bn locale), SVG icons (any+maskable), service worker (shell cache-first, navigation network-first w/ offline fallback, API never cached, prod-only registration), offline banner | `public/sw.js`, manifest linked in index.html |
| **B11 Frontend tests** | Vitest + RTL + jsdom wired into `vite.config.ts`; 6 tests (error map, i18n, login UX contract incl. failure path) | `npx vitest run` → **6 passed**; added to CI web job |
| **B12 Feedback & analytics** | `/feedback` (rating persists onto message) and privacy-safe `/events` structured-log endpoint; UI thumbs on every assistant message | `test_feedback_and_events_endpoints` ✓ |
| **B13 Accessibility** | aria-live message region, role=alert/status, fieldset/legend radio groups, labelled controls, focus-visible rings, reduced-motion media query, 44px targets, semantic headings | Code inspection + component tests |

### Phase C — Backend completeness

| Step | Executed | Proof |
|---|---|---|
| **C14 Email verification** | SMTP-configured deployments gate login (`email_unverified`) until single-use hashed code verified (`/auth/verify-email`, `/auth/resend-verification`); auto-verify without SMTP | `test_email_verification_gate` full cycle ✓ |
| **C15 Per-user limits** | RateLimitMiddleware scopes: login/forgot/reset=IP, tutor ask/chat=**user key** (NAT classroom-safe), remaining tutor routes=IP ceiling; settings instance injected (fixed lru_cache bug) | `test_tutor_limit_is_per_user_not_per_ip`: same IP, second user unaffected after first is throttled ✓ |
| **C16 Teacher assign quiz** | Roster rows carry an assign action → teacher posts `/quizzes` for any student in class (authorization already supported it) | TeacherDashboard UI + existing RBAC tests |
| **C17 Parent invite codes** | `parent_invites` table; student issues `BGPT-XXXXXXXX` code (SHA-256 stored, TTL, ≤3 live); parent redeems at `/parents/link/invite`; single-use enforced; legacy ID link kept | `test_parent_invite_flow_end_to_end` incl. reuse rejection ✓ |
| **C18 Admin depth** | `/admin/users` paginated + searchable (`q`, `role`, `limit`, `offset`) returning `{total, items}`; admin UI gets search, filters, pager, purge button | `test_admin_users_pagination_and_search` ✓ |

### Phase D — Ops / compliance

| Step | Executed | Proof |
|---|---|---|
| **D19 Config inconsistency** | `GEMINI_MODEL` default unified to `gemini-3.1-flash-lite` across config.py, docker-compose.yml, both env examples | grep shows single value everywhere |
| **D20 Consent evidence + retention** | Students store `consent_ip/at/version` (v2026-08-v1) at registration, surfaced in GDPR export; `/admin/maintenance/purge` sweeps old chats/tokens/used invites | Migration applied+reverted cleanly; purge endpoint tested; runbook §10 cron recipe |
| **D21 Load testing** | `load/tutor_load.js`: ramping VUs, realistic 70/20/10 scenario mix, SLO thresholds (tutor p95<8 s, quiz p95<500 ms, errors<2%) fail the run | Script committed; execution needs k6 + staging host (owner) |
| **D22 Runbook** | §10 added: secrets rotation procedures, capacity plan, retention schedule + automation command, email-verification ops | docs/runbook.md |
| **D23 Legal/UAT/pilot gates** | `docs/LAUNCH_READINESS_CHECKLIST.md`: legal review sign-off lines, UAT script with exit criteria, production deployment gate, post-launch cadence | Committed |

## 3. Bugs found & fixed during execution (beyond the plan)

1. **Subject mismatch**: frontend sent `math`, corpus used `mathematics` → math quizzes/asks always missed. Fixed via canonical_subject aliasing.
2. **Rate-limiter settings bug**: middleware read the process-global cached settings instead of the app's own — would break multi-tenant tests and any embedded deployment. Now `app.state.settings`.
3. **Grounding gate fragility**: top-hit-only coverage flipped grounded questions to refusal when ranking shuffles near-ties; gate now scans best-of-hits with stem normalization.
4. **Quiz under-generation**: silent shortfall replaced by second-pass fill + explicit `partial_quiz` note.

## 4. Verification summary (all executed this round)

| Gate | Result |
|---|---|
| Backend pytest | **154 passed, 3 skipped** (was 136; +18 new feature/red-team tests) |
| ruff check + format | Clean |
| mypy strict | `Success: no issues found in 43 source files` |
| Alembic | upgrade head → downgrade base → upgrade head clean (incl. new revision) |
| Web vitest | 6 passed |
| Web build (tsc+vite) | Success — fonts bundled, JS 228 KB (73 KB gzip), CSS 15 KB |
| Live E2E smoke | register→login→chat SSE(27 tokens+done)→invite code→self-harm refusal→class-9 quiz 5/5 |

## 5. Still requires the OWNER (cannot be done in-repo)

1. 🔐 Rotate the Gemini key exposed in chat history (unchanged from before).
2. 📚 **Real NCTB corpus rights + ingestion** — the synthetic corpus proves the pipeline; the product's usefulness scales with real content.
3. 🌐 Domain + DNS → TLS profile; paid Gemini tier; SMTP credentials.
4. ⚖️ Legal sign-off on consent flow (checklist §1) + formal UAT (§2).
5. 🚀 Staging host → run `load/tutor_load.js` at target VUs → deploy with `DEPLOY_ENABLED=true`.

## 6. Honest limitations

- Streaming is SSE-over-POST (fetch streams); older browsers without `ReadableStream` fall back to non-streaming chat turn.
- Safety layer is deterministic regex — auditable and fast, but not a substitute for periodic human red-teaming of live Gemini output.
- Playwright browser-E2E specs are not included; vitest covers unit/UX contracts, and CI runs them. Browser-matrix validation remains an owner-side task (no browser automation in this environment).
- The corpus remains synthetic-original text pending rights clearance.
