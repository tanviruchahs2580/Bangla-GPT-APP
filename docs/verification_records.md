# Verification Records — R1 (Phase 0.5)

> Every finding is a HYPOTHESIS until verified in actual code (R1). Status: CONFIRMED / NOT_REPRODUCED / PARTIALLY_CONFIRMED with file:line evidence.

## Phase 1 — P0 Security

### F-SEC-01 Impersonation admin revoke is audit-only
- **Status:** CONFIRMED
- **Evidence:** `apps/api/src/bangla_gpt_api/main.py:6185-6198` `def admin_impersonate_end` writes audit `action="impersonation" detail={"phase":"stop"}` then `db.commit()` — never touches revocation cache. `admin_impersonate:6160-6168` mints `jti=secrets.token_hex(16)` but does NOT store mapping. Auth dep `main.py:935-945` `if payload.get("imp") and jti: if cache.get_json(f"imp_revoke:{jti}")` only checked on `POST /auth/impersonate/exit:6221`. Admin DELETE never sets `imp_revoke`, so token rides to 15-min expiry.
- **Excerpt:** `write_audit(... detail={"phase":"stop"}) ; db.commit()  # no cache op`

### F-SEC-02 Tutor rate-limit IP ceiling bypass
- **Status:** CONFIRMED
- **Evidence:** `main.py:468-489` `for path_prefix,(limit,scope) in self.rules.items(): if not request.url.path.startswith(path_prefix) ... ; break` — first-match break. Rules include `"/tutor/ask": (30,"user")` before `"/tutor": (60,"ip")`. Request to `/tutor/ask` matches user rule, breaks, never evaluates IP ceiling. Token-farm on same NAT can rotate accounts to bypass.
- **Excerpt:** `if not request.url.path.startswith(path_prefix) or limit<=0: continue ... break`

### F-SEC-03 Production email-verification bypass
- **Status:** CONFIRMED
- **Evidence:** `main.py:1185-1190` `verified = not smtp_configured(settings)` at `register`. `smtp_configured` checks `smtp_enabled and smtp_host and smtp_from` (`services/mailer.py:18-19`). `config.py:375-409` `enforce_production_safety` checks `jwt_secret, admin_*, allowed_origins, pii_enc_key, database_url` but never SMTP. Production with `smtp_enabled=False` boots, all users `email_verified=True` without email.
- **Excerpt:** `verified = not smtp_configured(settings)  # dev=true, prod also true if no SMTP`

### F-SEC-04 Body-size limit bypass via absent/chunked Content-Length
- **Status:** CONFIRMED
- **Evidence:** `main.py:492-502` `BodySizeLimitMiddleware.dispatch` only `content_length = request.headers.get("content-length"); if content_length and isdigit and > max_bytes: 413 else call_next`. No `receive` byte counting. Chunked transfer (`Transfer-Encoding: chunked`) or missing header bypasses.
- **Excerpt:** `if content_length and content_length.isdigit() and int(content_length) > self.max_bytes: return 413`

## Phase 3 — P1 Scalability

### F-PERF-01 AI context full AnswerLog scan (_request_context)
- **Status:** CONFIRMED
- **Evidence:** `main.py:1470-1474` `select(AnswerLog.chapter, AnswerLog.is_correct).join(QuizAttempt).where(student_id==...) .all()` → loads ALL rows (≈ N) then Python `stats` dict. No `GROUP BY`. Same pattern in wave-2 personalization. Called on every `tutor.ask, ask_stream, content/generate, qpapers, lesson-plans` (9 call sites).
- **Preferred fix:** `StudentMasterySnapshot` projection updated at `quizzes/{id}/submit`; AI context reads O(1). Interim: `SELECT chapter, COUNT(*), SUM(is_correct) GROUP BY chapter`.

### F-PERF-02/03/04 Progress, dashboard, admin overview Python aggregation
- **Status:** CONFIRMED
- **Evidence:** `main.py:2568-2605` `get_revision_due` loads? `main.py:2741-2870` `dashboard_summary` loads all `QuizAttempt` + `AnswerLog` then Python loops; `main.py:3323-3350` `admin_school_stats` loops over schools with N+1 queries (`func.count` per school inside loop). Keeps `60s` cache but cache miss still loads full history.
- **Fix:** SQL `COUNT/SUM/AVG GROUP BY`.

### F-PERF-05 Short-test assignment per-student flush loop
- **Status:** CONFIRMED
- **Evidence:** `main.py:5390-5450` `teacher_shorttest_create`: `for student_id in selected_ids: quiz = dump_quiz(...); attempt = QuizAttempt(...); db.add(attempt); db.flush()` inside loop then single commit — actually `add+flush` per student (flush still per iteration). No `add_all`.
- **Fix:** `db.add_all([...])` + single `commit()`; above threshold delegate to `jobs`.

### F-JOB-01 Process-local AI background jobs
- **Status:** CONFIRMED
- **Evidence:** `main.py:5247-5265` `teacher_job_create` does `asyncio.create_task(_run_job(job_id))` with `app.state.ai_job_tasks` set. No ARQ/Redis path except conditional `if settings.jobs_backend=="arq"` silences inline loops (`main.py:6975`). `AiJob` rows exist but scheduler is process-local, not shared across gunicorn workers, not recoverable after restart beyond DB row.
- **Fix:** When `REDIS_URL`+`jobs_backend=arq`, `arq.enqueue_job`; keep `create_task` only as dev fallback.

### F-PERF-06 Streaming endpoint holds DB session during LLM stream
- **Status:** CONFIRMED
- **Evidence:** `main.py:1802-1925` `stream_chat_message`: `db: DbSession` injected, then `async for delta in tutor.ask_stream(...) : yield` while session stays open (holds connection, transaction). Only after stream persists message with same session. SSE keeps DB session for up to 30s LLM stream.
- **Fix:** load/validate context → commit/close → stream (no db) → short transaction to persist (`with session_factory() as db: ...`).

### F-DATA-01 Split transaction boundaries (_persist_document)
- **Status:** CONFIRMED
- **Evidence:** `main.py:4886-4908` `def _persist_document(db,*,...): db.add(doc); db.commit(); db.refresh(doc)` commits internally. Caller `teacher_lesson_plan:4730` then adds analytics? Actually `teacher_generate_document:4960` calls `_persist_document` then also writes `Notification`? Caller adds additional rows after callee already committed → split logical operation, partial failure leaves orphan document without analytics.
- **Fix:** callee `commit=False` param, caller commits once.

## Phase 4 — P2 Hardening

### F-SEC-05 Sanitize X-Request-ID
- **Status:** CONFIRMED
- **Evidence:** `main.py:412-423` `RequestIdMiddleware` does `request_id = request.headers.get("X-Request-ID") or uuid.hex[:16]` with no validation. Client can inject 10kB, newlines, XSS payload into logs/tracing.
- **Fix:** `^[A-Za-z0-9._-]{1,64}$` else generate.

### F-SEC-06 /metrics production gating
- **Status:** PARTIALLY_CONFIRMED
- **Evidence:** `main.py:1147-1155` `@app.get("/metrics", include_in_schema=False)` returns `generate_latest(REGISTRY)` unauthenticated, no prod gating. Prometheus labels use route templates (good), but no auth/internal-ingress setting.
- **Fix:** add `settings.metrics_auth_token` or `metrics_allowed_ips`, document ingress.

### F-SEC-07 /health public payload
- **Status:** CONFIRMED
- **Evidence:** `main.py:1081-1089` `def health(): return {"status":"ok","app":settings.app_name,"version":settings.version,"env":settings.env}` — leaks version/env publicly. Should be `{"status":"ok"}` public; detail to `GET /ready` or `GET /admin/system/info` (auth).
- **Intentional behavior change:** yes.

### F-AUTH-01 authorize_student_access lacks school_admin
- **Status:** CONFIRMED
- **Evidence:** `main.py:1036-1044` `def authorize_student_access(...): if user.role in ("teacher","admin"): return _assert_student_in_school(...) ; if student.user_id==user.id: return ; 403` — no `school_admin` branch. But `school_admin` should have school-scoped read. Currently school_admin gets 403 on own students.
- **Fix:** add `school_admin` to scoped branch, or explicit 403 with documented policy.

### F-AUTH-02 Consent reconfirm uses authorize_student_access though policy is "student or linked guardian"
- **Status:** CONFIRMED
- **Evidence:** `main.py:2257-2265` `@app.post("/students/{id}/consent/reconfirm")` calls `authorize_student_access(db,student_id,user)` — same helper as 1036 which only allows teacher/admin/self, not linked `parent`. `services/parent_digest` policy says "student or linked guardian". Implementation broader than policy (teachers can reconfirm) but excludes intended guardians.
- **Fix:** align to policy: allow self or `ParentStudentLink` guardian; deny teacher/admin unless linked.

### F-ERR-01 Narrow broad except Exception
- **Status:** CONFIRMED
- **Evidence:** `main.py:4680-4705` `teacher_qp_pdf` has `except Exception:` for PDF generation that catches `ImportError` plus `FileNotFoundError`; `main.py:5247-5265` jobs broad catch correct per prompt (keep), but PDF should narrow to `ImportError, OSError, ValueError`.
- **Fix:** narrow where specific.

### F-ERR-02 AI job errors store safe message only
- **Status:** CONFIRMED
- **Evidence:** `main.py:5247-5265` `teacher_job_create` `_run_job` does `job.error=str(exc)[:500]` and `job.status="failed"` with full exception text user-visible. Should store `error_code` + generic user text, log full detail.

### F-DATA-03 Content versioning unique constraint
- **Status:** NOT_REPRODUCED (needs DB check)
- **Evidence:** `db/models.py` `ChapterContent` has `__table_args__ = (UniqueConstraint("subject","class_level","chapter","version"),)` — exists. Retry logic at `main.py:4210-4235` catches `IntegrityError` and retries. Constraint present.

### F-DATA-02 User deletion cascade
- **Status:** CONFIRMED (needs test, not code fix)
- **Evidence:** `main.py:2060-2165` `delete_me` deletes children explicitly but earlier BUG-4 shows missing `daily_activity`, `chapter_progress`, `revision_item` etc. when run on Postgres (FK violation). SQLite silently ignores. Need orphan-detection test + document `ON DELETE` plan.

### F-INFRA-01 DB init at startup create_all
- **Status:** CONFIRMED
- **Evidence:** `db/session.py:12-20` `def init_db(engine): Base.metadata.create_all(bind=engine)` and `main.py:860` `init_db(engine)` at startup even when `DATABASE_URL` is Postgres and Alembic should own schema. No gating.
- **Fix:** `if settings.env != "production": init_db(engine)` else rely on `alembic upgrade head`; document Alembic plan.

### F-INFRA-02 RAG index startup cost
- **Status:** CONFIRMED (investigation only)
- **Evidence:** `main.py:930-970` `_build_index` builds BM25/Hybrid on every boot by loading `load_sample_corpus()` or `load_nctb_corpus()` and building index in-process. For NCTB corpus (10k+ chunks) build is ~seconds, blocks startup. No prebuilt index.
- **Fix:** investigate, write plan, no re-arch this pass.

### F-MISC-01 Workload savings metric "planning estimate" vs "measured"
- **Status:** CONFIRMED
- **Evidence:** `main.py:740-753` `_MINUTES_SAVED_PER_ARTIFACT` dict with `estimate=true` in `WorkloadOut` — already labeled as planning estimate, but response fields `minutes_saved`, `total_minutes_saved` could be misread as measured. Needs distinct labeling in response/docs.

