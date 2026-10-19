# School tenancy enforcement (B-08)

Two layers protect one school's rows from another school's staff, plus a
third layer that is prepared but deliberately not applied (Postgres RLS).

## 1. Per-route helpers (the primary gate)

`apps/api/src/bangla_gpt_api/routers/deps.py`:

| Helper | What it does |
|---|---|
| `_tenant_school_id(db, user)` | The caller's tenant: `school_id` for teacher/school_admin; the shared default school for standalone staff (F-04); `None` for admin (platform-wide) and for student/parent sessions (ownership checks instead). |
| `_assert_student_in_school(db, user, student)` | 403 `other_school` when the student is outside the tenant's student set. |
| `_assert_room_in_school(db, user, room)` | 403 `other_school` when the classroom belongs to another school. |
| `load_student_for_tenant(db, id, user)` | Load-then-check in one call; 404 only for ids that match no student at all. |
| `authorize_student_access(db, id, user)` | Role-dispatched gate used by student-scoped read routes. |

Cross-tenant negative coverage: `tests/test_school_tenancy_isolation.py`,
`tests/test_cross_school_content.py`, `tests/test_school_admin_edges.py`,
`tests/test_school_aggregation.py`, `tests/test_school_dashboard.py`,
`tests/test_school_onboarding.py`, plus the audit remediation suites.

## 2. Central ORM read filter (defense in depth)

`apps/api/src/bangla_gpt_api/db/tenancy.py`, installed on every session
factory by `db/session.make_session_factory`. `get_current_user` installs the
caller's tenant on the request's session (`set_tenant_context`); a
`do_orm_execute` listener then rewrites every ORM **select** against the
tenancy anchors with a `with_loader_criteria` predicate:

| Model | Predicate |
|---|---|
| `ClassRoom` | `school_id == tenant` |
| `ClassStudent` | enrollment into a classroom of the tenant's school |
| `Student` | id in the tenant's student set (the `_school_student_id_set` predicate) |

A new query that forgets the helper can therefore only return the caller's
school. What is deliberately out of scope, stated so nobody assumes more
than the mechanism gives:

* admin sessions are unscoped; student and parent sessions are unscoped and
  rely on ownership/link checks;
* writes are not rewritten — a missing write guard fails its own test
  loudly instead of silently no-opping;
* a `Session.get()` served from the identity map (the row was already
  loaded in this session) is not re-filtered. In a request the tenant is
  installed before any route code runs, so only `get_current_user`'s own
  `User`/`School` lookups precede it;
* the sanctioned bypass `tenant_filter_bypassed()` exists for exactly one
  caller — `load_student_for_tenant` — because the documented contract for
  a cross-school student is 403 `other_school`, and a filtered (invisible)
  row would answer a bare 404. The bypass is immediately followed by the
  same predicate the filter applies, and
  `tests/test_r3_ws4_tenancy.py` pins that the bypass is scoped.

Mechanism + contract tests: `tests/test_r3_ws4_tenancy.py` (7 cases:
scoped selects and by-key gets, unscoped sessions, the bypass, 403/404/admin
contracts, same-school success).

## 3. Postgres row-level security (prepared, not applied)

Considered and **not applied** in this round, with the reason recorded: the
application connects as the table owner, and Postgres does not apply RLS to
the owner unless `ALTER TABLE ... FORCE ROW LEVEL SECURITY` is set; with
FORCE, every non-superuser connection needs the tenant GUC set
(`SET LOCAL app.school_id`) *or* an explicit bypass role for jobs, CLIs and
migrations. That is a connection-layer change across every engine user plus a
migration, and a wrong bypass is a silent platform-wide exposure. The ORM
filter above covers the same read paths without touching the database
contract. If RLS is wanted as a third layer:

1. `ALTER TABLE students/classrooms/class_students ENABLE ROW LEVEL SECURITY`
   plus `FORCE ROW LEVEL SECURITY`, policies keyed on
   `current_setting('app.school_id', true)::int`;
2. set `app.school_id` per transaction in `get_db` from the same
   `_tenant_school_id` value, and clear it on connection return
   (`pool_reset_on_return` / a `reset` event);
3. give jobs/CLIs/migrations a dedicated non-FORCE role or an explicit
   `app.bypass_rls` policy, and add a two-session negative test.

Owner action; not verifiable on the SQLite test database.
