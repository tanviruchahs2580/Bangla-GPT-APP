# Main Section Map — Phase 0.2 (R9)

Source: `apps/api/src/bangla_gpt_api/main.py` — 7018 lines — `def create_app()` at line 756

| Section | Lines | Description |
|---|---|---|
| 1. Imports & constants | 1–74 | 74 lines |
| 2. Helper: build_personalization_block & workload constants | 710–755 | 46 lines |
| 3. Factory: create_app() setup | 756–880 | 125 lines |
| 4. Middleware: enforce_production_safety | 375–410 | 36 lines |
| 5. Middleware: RequestId | 412–425 | 14 lines |
| 6. Middleware: _client_ip + RateLimit | 426–491 | 66 lines |
| 7. Middleware: BodySize + SecurityHeaders + Prometheus | 492–560 | 69 lines |
| 8. Lifespan helpers: configure_logging, caching, engine, session | 880–970 | 91 lines |
| 9. System routes: /health, /live, /ready, /status, /metrics | 1081–1160 | 80 lines |
| 10. Auth routes: register, verify-email, login, forgot, reset, change-password | 1151–1400 | 250 lines |
| 11. Auth helpers: _send_verification_email, _hash_reset_token, etc. | 1400–1445 | 46 lines |
| 12. School tenancy helpers: _tenant_school_id, _school_student_id_set, authorize_student_access | 970–1080 | 111 lines |
| 13. Education context: _request_context + build_personalization_block | 1443–1510 | 68 lines |
| 14. Tutor routes: /tutor/ask, conversations CRUD, search, chat, stream | 1382–1930 | 549 lines |
| 15. Feedback / Events / users/me / export | 1929–2170 | 242 lines |
| 16. Students / Quizzes / Progress / Activity / Revision / KG / Search / Dashboard | 2240–2880 | 641 lines |
| 17. Learn progress: /learn/progress GET/POST | 2875–3010 | 136 lines |
| 18. Teacher roster / analytics / classrooms / import | 3009–3310 | 302 lines |
| 19. School admin: /admin/schools, invites, content versions, reports | 3304–3530 | 227 lines |
| 20. School staff: /schools/{id}/invites, /auth/join-school, /schools/mine, /school/overview | 3519–3700 | 182 lines |
| 21. School dashboard: /school/students, teachers, classes, coverage, analytics | 3860–4100 | 241 lines |
| 22. Teacher content: /teacher/content/generate, history, GET, PUT | 4190–4360 | 171 lines |
| 23. Teacher qpapers: CRUD, review, replace, finalize, pdf | 4359–4710 | 352 lines |
| 24. Teacher lesson-plans: /teacher/lesson-plans | 4708–4930 | 223 lines |
| 25. Teacher generate/document: /teacher/generate/{kind}, documents CRUD, pdf | 4928–5090 | 163 lines |
| 26. Notes & Notifications | 5080–5170 | 91 lines |
| 27. Jobs / Workload / ShortTests / Weak-matrix / Coverage / Support-plans / Assignments | 5247–6015 | 769 lines |
| 28. Assignments mine / Admin users / Role update / Impersonate | 6014–6200 | 187 lines |
| 29. Admin impersonate / exit / audit / analytics / refusals / quality / purge | 6200–6400 | 201 lines |
| 30. Parents link / invite-code / prefs / memory / children progress/activity/report | 6400–6975 | 576 lines |
| 31. Lifespan: @app.on_event startup/shutdown (parent_digest, weakness_refresh) | 6975–7018 | 44 lines |

## Notes (R9)
- Read in chunks ≤500 lines. Delete from `main.py` ONLY after identical logic exists in new module.
- Final `main.py` ≤300 lines: only `create_app()`, lifespan wiring, middleware registration, dependency registration, router registration.
- Route parity must match `docs/route_baseline.md` (129 routes).

## Nesting warnings
- `create_app()` at 756 contains ~6262 lines of nested helpers and route handlers. Shared closures (`settings`, `engine`, `session_factory`, `cache`, `tutor`, `index`, `provider`) must become module-level factories with explicit params.
- `authorize_student_access` at 1036 captures `_tenant_school_id` and `_school_student_id_set` — extract together.
- `_request_context` at 1443 captures `build_personalization_block`, `EXPLANATION_STYLES`, `snapshot_mastery`, `atrisk` — extract with imports.
- `_persist_document` at 4886 does `db.commit()` internally — F-DATA-01 warns split boundary.
