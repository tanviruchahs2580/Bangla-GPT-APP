# AI incident response

Procedure for AI-related incidents at BASE_SHA `7e8525e2` (2026-10-29): a
flagged or harmful answer, a self-harm disclosure, an abuse disclosure, or a
teacher escalation. The document separates what the code does today from the
human procedure, which is proposed and needs owner confirmation. No gap is
claimed as implemented unless a `file:line` exists; open gaps carry their
finding id.

## 1. What the system does today (implemented)

- Every student free-text question passes a keyword screen before retrieval (`services/safety.py:83-106`). Six categories exist: self_harm, weapon_synthesis, drug_synthesis, sexual_content, violence, personal_data (`services/safety.py:25-57`). Romanized/English variants exist only for self_harm.
- A refusal returns supportive copy, never an error page and never the matched pattern (`services/safety.py:109-117`). Self-harm refusals include the helpline sentence from `services/safety.py:14-18`; that number is pending owner verification (section 6) and must not be edited on assumption.
- The refusal is persisted as a reason code on the chat message (`ChatMessage.refused_reason`). The admin board aggregates it by reason and class over a window — counts only, deliberately no content and no identity (`routers/admin.py:330-365`). A self-harm disclosure therefore produces a count and a supportive answer to the child, and is visible to no human beyond those counts.
- Answer feedback (thumbs up/down, optional comment) goes to an admin triage queue: oldest untriaged first, reporter identity withheld beyond user id, internal note field (`routers/tutor.py:944-1016`; `db/models.py:320-345`). Triage is manual.
- There is no escalation concept in the codebase: a search for "escalat" over `apps/`, `docs/` and `scripts/` finds no path that notifies a teacher, counsellor, parent or anyone else about a disclosure or a flagged answer (audit F-LLM-12 / F-029). `SECURITY.md` covers data incidents only.
- There is no runtime kill switch (audit F-LLM-14; `git grep KILL_SWITCH|DISABLE_AI|AI_ENABLED|GENERATION_ENABLED` has no matches).
- Generation can only be disabled by changing `LLM_PROVIDER` at deploy time, and that also removes the retrieval index: with an unusable provider the app answers `/ready` 503, `/tutor/ask` 503 `tutor_unavailable` and `/search` 503 `index_unavailable` (probe `.qa-work/evidence/E-AIG-06/`; `initialize/dependencies.py:240-311` builds the index inside the provider-valid branch). Retrieval-only degradation does not exist.

## 2. Severity levels (proposed; owner must approve before these are commitments)

| Level | Trigger | Examples | Response target (proposed) |
|---|---|---|---|
| SEV-1 | A minor is at risk of harm, or a harmful answer reached a minor | Self-harm or abuse disclosure with no human follow-up; hate/bullying content in a delivered answer; helpline copy found wrong | Acknowledge within 1 h; child-safety owner engaged same day; school safeguarding lead informed per section 4 |
| SEV-2 | Safety control regressed, or wrong answers at scale | Refusal screen bypass found; coverage gate serving out-of-corpus answers in production; systematic uncited answers | Acknowledge within 1 school day; decide mitigation/rollback within 3 days |
| SEV-3 | Single flagged answer, quality complaint, provider degradation | One thumbs-down with a comment; one bad worksheet; provider latency/outage | Triaged via the feedback queue within 5 school days |

Response times are proposals; the repository records no incident timelines.

## 3. Tools available during any incident

- Refusal counts by reason and class, 1-365 days (`routers/admin.py:330-365`).
- Feedback queue with notes (`routers/tutor.py:944-1016`).
- Append-only audit trail of privileged actions, ids and counts only (`audit_log`; SEC-15 evidence E-SEC-15-1).
- Provider config change plus redeploy, and release/DB rollback (`docs/runbook.md:297-320`).

## 4. Event procedures

1. **Flagged answer** (thumbs-down, comment, or a report).
   1. An admin works the queue (`/admin/feedback`), reads the complaint, writes the internal note (`routers/tutor.py:984-1016`).
   2. Classify: content defect (product bug, open a finding), model/config regression (section 5), or user error (no action).
   3. A safety-classified answer continues as SEV-2 or SEV-1 below.
2. **Self-harm disclosure.**
   1. The child already received the supportive refusal and the helpline sentence; no human is notified by the system today (section 1).
   2. Proposed: the child-safety owner (or the on-call duty holder) reviews the refusal counts for the window and, with the school safeguarding lead, decides whether the guardian must be contacted. This is manual and must respect the privacy decision already made in code: the audit deliberately withholds message content and identity (`routers/admin.py:330-365`). Reading a child's chat beyond the disclosed policy needs a documented legal basis — legal review required.
   3. Proposed minimum implementation (owner decision): a safety event visible to one designated school role, k-anonymity-aware, with a documented retention; today no such record exists (F-LLM-12).
3. **Abuse disclosure** (coercion, exploitation, sexual content about a third party). Same flow as a self-harm disclosure, with the school safeguarding lead as the primary human contact. Whether staff have a mandatory reporting duty under Bangladesh law is a legal question the repository does not answer; obtain legal review before promising any reporting behaviour in the UI.
4. **Teacher escalation** (a teacher disputes an answer, worksheet or question paper): today the teacher submits feedback with a comment and an admin triages it (section 1) — there is no teacher-to-admin escalation channel and no notification when the note is written. Proposed: generated question papers route to the existing review flows, and the AI owner is tagged when the same defect appears twice.
5. **Provider outage or cost spike.** Verify the coded failures first: `/tutor/ask` 502 `llm_unavailable` is the bounded provider-down path (`.qa-work/audit/ARCH/report.md` failure-mode table); cost is visible on the admin AI-quality board (`.qa-work/audit/RAG/report.md`, RAG-25). Treat sustained 5xx or a budget breach as SEV-3/SEV-2 and use section 5.

## 5. Disabling generation and rollback (documented, manual)

- **Disable generation today (deploy-time only).** Set an unusable `LLM_PROVIDER` (or unset the API key) and redeploy. Known consequence: the retrieval index is not built, so `/search` also returns 503 `index_unavailable` alongside `/tutor/ask` 503 `tutor_unavailable` (E-AIG-06). This is not a partial degradation and not a runtime switch; it takes the tutor and search down together. Restore by reverting the config and redeploying.
- **Release rollback:** redeploy the previous tag per `docs/runbook.md:297-320`.
- **Database rollback:** `alembic downgrade <revision>` after a backup (`docs/runbook.md:318-320`); never without the backup step.
- **Provider fault isolation:** the optional fallback provider and circuit breaker exist (`providers/__init__.py:77-125`); switching primary provider is a config change and must be followed by re-running the eval gate (`docs/ai/system-card.md` section 9).
- **Not available:** a tutor-off, retrieval-on mode (F-LLM-14). If the owner requires this for child-safety incidents, it is a code change, not a configuration change.

## 6. Notification list and the helpline

- Proposed recipients, by role: platform on-call (availability), child-safety owner (SEV-1/2 safety), school safeguarding lead (school-side follow-up), data-protection owner (privacy), engineering lead (model/config regressions). Names, numbers and duty rota live with the owner, not in this repository.
- The number shipped in `services/safety.py`, pending owner verification, is the only helpline the product shows. Do not edit it, "correct" it from memory, or validate it against unofficial sources; verification is an open owner action on the launch checklist (`docs/LAUNCH_READINESS_CHECKLIST.md:29-30`; audit F-LLM-11). A wrong number is itself a SEV-1 trigger.

## 7. After an incident

1. Record: date, level, trigger, actions taken, which release/config the rollback used.
2. Add or update the regression guard (a test where the defect is testable offline; a documented manual check where it is not).
3. Update `docs/ai/risk-register.md` residual status and the system card when a limitation changes.
4. Keep findings traceable: reference the finding id (`.qa-work/findings.csv` while the QA run is open, the issue tracker after it closes).

Open gaps this procedure cannot paper over: no human escalation path (F-LLM-12 / F-029), no runtime kill switch or retrieval-only mode (F-LLM-14), and the unverified helpline (F-LLM-11).
