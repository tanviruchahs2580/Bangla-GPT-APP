# Launch Readiness — Legal, UAT & Pilot Checklist (D23)

> Owner-facing companion to `docs/runbook.md`. Everything engineering could
> execute in-repo is done; the items below require real-world action by the
> project owner. No code changes are needed for them.

## 1. Legal & child-safety (BLOCKING for launch)

- [ ] **Consent-flow legal review**: have a Bangladesh-based lawyer review the
      registration consent checkbox, `/privacy` and `/terms` copy against
      BTRC/ICT guidance and the Children Act 2013. Record the reviewer and
      date here: ____________________
- [ ] **Consent evidence**: verify a pilot registration stores
      `consent_ip / consent_at / consent_version` (check via data export).
- [ ] **Data retention schedule**: confirm `CHAT_RETENTION_DAYS` matches the
      published privacy policy; run the purge job once and log it.
- [ ] **Moderation red-team sign-off**: run through
      `tests/test_product_v3.py::test_unsafe_questions_get_supportive_refusal`
      categories manually in staging; document any gaps found with Gemini live.
- [ ] **Helpline accuracy**: verify the mental-health helpline number shown in
      self-harm refusals (`services/safety.py`) is current.

## 2. UAT with real users (1 school, 20–50 students)

- [ ] Recruit 2 teachers + 1 class of students + their parents.
- [ ] Create accounts via the real flow (parent consent checkbox ON).
- [ ] Each student: ask 5 curriculum questions, take 2 quizzes, check progress.
- [ ] Teacher: assign quiz from dashboard; read class analytics.
- [ ] Parent: redeem invite code; view child progress.
- [ ] Collect structured feedback (👍👎 counts in DB `feedback` table +
      one 15-minute interview per teacher).
- [ ] Exit criteria: ≥80% "understood the answer" on grounded responses;
      zero P0/P1 defects open.

## 3. Production deployment gate

- [ ] Domain purchased → DNS A/AAAA → Caddy TLS profile up (auto-HTTPS).
- [ ] `JWT_SECRET`, `ADMIN_PASSWORD` set to generated secrets; admin first
      login rotation completed.
- [ ] Gemini key deployed (rotated if ever exposed); paid tier enabled.
- [ ] SMTP configured; verification + reset emails deliver to Gmail.
- [ ] Load test at target concurrency passed SLO thresholds (runbook §10).
- [ ] Restore rehearsal executed on production backup (not just local).
- [ ] Real NCTB corpus ingestion rights confirmed and pipeline run
      (`docs/NCTB_DATA_PIPELINE.md`) — **this is the single biggest blocker
      between current state and a useful product.**

## 4. Post-launch

- [ ] Weekly: review Prometheus alerts, feedback ratings, error logs.
- [ ] Monthly: restore drill + dependency audit (`pip-audit`, `npm audit`).
- [ ] Quarterly: purge-job report, key rotations, corpus refresh vs NCTB edits.
