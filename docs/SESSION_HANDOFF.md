# SESSION HANDOFF - Bangla GPT APP (2026-09-08)

Start-of-session file for a fresh agent session. Read this + PROGRESS.md
before touching anything. This reflects the state at the end of session
sess_901eaae2 (context overflow -> user requested continuation elsewhere).

## 0. STANDING USER DIRECTIVES (still in force)

- "kono push, commit execute kora jabena ekhon" - NO git commit, NO push,
  NO CI/CD trigger, ever, until the user lifts this. Every PROGRESS.md
  entry uses marker: EMDASH + " (no-commit directive)".
  Byte-verify: grep -c "$(printf '\xe2\x80\x94') (no-commit directive)" PROGRESS.md
  Current verified count: **53**.
- R8: steps needing human input must STOP and ask; never fake them.
  R11/R7: child PII/counts only in logs; never print secrets (env NAMES
  only; admin creds live in apps/api/.env - read in-script, never echo).
  R6: never regress test counts. R12: never delete/weaken tests.
  R5 protected: design tokens (--brand #4353b8), Hind Siliguri font,
  middleware order, guardian_consent, 4 SYSTEM_PROMPTs byte-identical,
  alembic append-only (head a1b2c3d4e5f6).
- Mode: autonomous; finish steps, verify with real runs, then report.

## 1. WHERE WE ARE (master roadmap S0 -> S7 + Phase H)

- Stages 0-5: DONE. GATE G5 PASS incl. full live user-mode browser test
  on the preview (:4174) - registration, tutor Q&A grounded, feedback ->
  admin triage, impersonation support session, account deletion.
- Stage 6 local batch: DONE this session.
  - S6.2 Content QA: apps/api/src/bangla_gpt_api/nctb/content_qa.py +
    apps/api/scripts/content_qa.py CLI (report exit-3 gate / sample /
    review). Checks: NFC, zero-width, math-mojibake, U+FFFD, PUA, legacy
    Bijoy. 13 tests. PASS-WHEN proven with seeded bad chunk c0042.
  - S6.5 Govt reporting: services/govt_report.py + admin-only
    GET /admin/reports/aggregate?format=json|csv|pdf&district=&since_days=
    &min_cell=. k-anonymity (default min_cell=5, cells below suppressed +
    counted), fail-closed PII scanner (email/phone-shaped => 500, count
    logged only), CSV formula-escape + BOM, PDF via fpdf2+Noto. District
    = export label only, NO migration. 9 tests (canary PII in NO format).
    Live-verified on :8000 (200x3, suppressed_cells=2, zero '@').
  - S6.6: docs/capacity_plan.md (10k/100k/1M MAU, measured baselines:
    entry JS 281KB->84KB gz, Bengali fonts ~175KB real cold payload,
    LLM ~$0.024/student/month ASSUMPTION - needs procurement confirm);
    scripts/font_subset_report.py measured: full Noto TTF->UI subset
    -71.8%, shipped font dir -23.0% (keep @fontsource for pilot).
  - S6.7: docs/hosting_decision.md DRAFTED. Sign-off block EMPTY on
    purpose (human: vendor/region/budget + data residency for minors'
    data). Recommendation on paper: single VPS Singapore, current
    compose stack. NOTHING provisioned/spent.
  - S6.8: docs/game_day_2026-09-08.md - 240-way concurrency 0% errors
    (1 worker ~65 RPS plateau, p95 3.5s@240); rate limiter verified as
    backpressure (clean 429s); LLM-down drill: /tutor/ask -> 502
    llm_unavailable (safe), quizzes/auth/status stay 200. KNOWN GAP
    (accepted, option flagged): /status "assistant" check is
    presence-only, so status page stays ok during a real upstream
    outage.
- GATE G6: local legs PASS (load + degraded + cost-estimate). Open legs
  need staging/human: real 100-school load (needs hosting sign-off),
  contracted pricing, CDN/revocation chaos on staging.
- GATE G5 remaining note: dedicated Bengali i18n pass for some S5.10
  keys still English in both dicts (admTriaged etc.) - follow-up task.

## 2. OPEN BLOCKERS (human-owned - do NOT fake, do NOT work around)

1. B-2026-09-08: S6.1 needs REAL NCTB textbook PDFs + explicit permission
   to ingest them (HARD gate; pipeline exists since S1/S2: extract_pdf ->
   qc -> normalize -> chunk -> scripts/build_nctb_corpus.py; content QA
   gate from S6.2 is ready to run on the output).
2. S6.7 hosting sign-off (fill the 4 lines in docs/hosting_decision.md).
3. LLM pricing confirmation for the capacity budget table.
4. Stage 7 (7.1 pilot recruitment, 7.3 release approvals) = human.
5. Phase H (F1-F7, incl. any push) only after all gates + the user says
   the word "finalize" - and push still needs explicit approval; moot
   while the no-commit directive holds.

## 3. VERIFIED BASELINES (re-verify, never trust stale claims)

- Backend: **492 passed + 3 skipped, exit 0** (~12.5 min, run from
  apps/api with REDIS_URL=redis://127.0.0.1:6399/0 for rate-limit tests;
  suite is hermetic - conftest kills .env).
- Frontend: vitest **89/89**, tsc exit 0, vite build green.
- Lint/type: ruff clean (src, tests, root scripts incl.
  font_subset_report.py; line-length 100), mypy **76 files** clean.
- alembic head a1b2c3d4e5f6, no drift; dev DB apps/api/dev.db.

## 4. LIVE PREVIEW STACK (keep running for the user)

- API :8000 (uvicorn, module-level app, reads apps/api/.env; LLM_PROVIDER
  =gemini real key). Restart from apps/api:
  PY="$(ls "$PWD"/../../.ven*/Scripts/python.exe | head -1)" && \
  RATE_LIMIT_BACKEND=redis REDIS_URL=redis://127.0.0.1:6399/0 \
  "$PY" -X utf8 -m uvicorn bangla_gpt_api.main:app --host 127.0.0.1 --port 8000
- Web preview :4174 = `vite preview` of the built dist (rebuilt after the
  S5.10 fixes: aria-label on status refresh, admTriaged label).
- Redis: docker container bgpt-redis-s53 on :6399.
- Health: GET :8000/health 200, /status ok, :4174 200.
- If code under apps/api changes, :8000 must be RESTARTED (no --reload).

## 5. ENVIRONMENT GOTCHAS (this host: Windows + Git Bash)

- Python venv at repo ROOT: "$PWD"/.ven*/Scripts/python.exe (from repo
  root) or "$PWD"/../../.ven*/Scripts/python.exe (from apps/api). Shell
  state never persists across tool calls - recompute PY each call.
  Bengali needs -X utf8; new code/tests ASCII-only (use chr()/escapes).
- META-LESSON: rendered output AND typed output can corrupt glyphs BOTH
  ways. Trust only code-point dumps, py_compile, grep counts, real runs.
  Anchor PROGRESS.md edits on ASCII substrings; build em-dash via
  chr(0x2014) in python; byte-verify marker count after every PROGRESS
  write (see pattern in /tmp/prog6*.py approach).
- Path quirk: `Path.write_text`/`read_text` are correct APIs - verify
  disk with grep, don't trust echoes.
- Browser testing (control-browser skill, main-agent ONLY): bootstrap
  scripts/browser-client.mjs setupBrowserRuntime each call, get("iab"),
  tabs.list() each call; locator lacks inputValue/isChecked -> use
  .evaluate(); window.prompt auto-dismisses in IAB -> stub via page
  evaluate; React inputs need native-setter + input event to clear;
  build Bengali test strings with String.fromCodePoint; screenshots via
  nodeRepl.emitImage(tab.screenshot()).
- Web auth localStorage keys: bgpt_token, bgpt_admin_token_backup,
  bgpt_impersonating; support-session exit button text is
  "End support session"; admin search inputs #q / #nschool.
- Load drills: use THROWAWAY sqlite copies + separate ports (:8010 mock
  LLM / :8020 fake key), never burn real Gemini quota, never point drills
  at dev.db. scripts/concurrency_probe.py [base] --levels a,b --reqs N.
  Default tutor limit 30/min/user -> lift via RATE_LIMIT_TUTOR_PER_MINUTE
  for pure-capacity runs (429s otherwise count as probe "errors").

## 6. WHAT TO DO NEXT (when human unblocks)

- On PDFs+permission: run S6.1 ingest CLI on real files -> content QA
  report -> sample sheet for the 10% human review -> re-run retrieval
  evals; PROGRESS entry + marker 54.
- On hosting sign-off: fill nothing yourself - the user fills the block;
  then (their word) provisioning steps from the doc.
- Stage 7 prep that needs no human: 7.2 teacher kit content can be
  drafted when the user enters Stage 7.
- Quick regression check at session start: targeted pytest of
  test_content_qa.py + test_govt_report.py, then decide if the full
  suite is needed (only after backend edits).

## 7. UNCOMMITTED WORK INVENTORY (branch upgrade/master-roadmap)

Everything from this multi-session run is UNCOMMITTED by directive:
modified backend/web/config/CI files (see git status), plus new files:
content_qa (module+CLI+tests), govt_report (module+tests), chat/parent/
feedback migration d4e5f6a7b8c9, new sample_nctb md files, docs:
capacity_plan.md, hosting_decision.md, game_day_2026-09-08.md,
SESSION_HANDOFF.md (this file), scripts/font_subset_report.py.
A future commit (ONLY when user lifts the directive) should group these
logically; nothing here is pushable now.
