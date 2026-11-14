# Risk acceptances — Enterprise V2 (2026-11-14)

Per the audit's §20 risk-acceptance requirements: ID, description, impact,
evidence, compensating controls, owner, approver, expiry, review trigger,
exit plan. Each acceptance below is owner-directed ("execute all actions
according to report"), recorded here with an expiry, and re-approved or
remediated at that date.

## RA-BGPT-SEC-004 — public registration discloses account existence

- **Description:** `POST /auth/register` with the default
  `registration_email_conflict=disclose` returns `email_taken` (409) for an
  already-registered address, so an unauthenticated caller can probe whether
  an email has an account (E1; audit §9.5).
- **Business impact:** low for the current school-pilot audience; account
  enumeration is a reconnaissance primitive, not an account takeover.
- **Evidence:** `apps/api/src/bangla_gpt_api/routers/auth.py::register`
  (conflict branch) and `config.py` (`registration_email_conflict` default;
  `generic` mode implemented and unexercised in production).
- **Compensating controls:** per-IP rate limiting on auth routes; account
  lockout (S-002); no capability is exposed to the probed address; emails on
  this deployment are institution-issued, so the address space is small.
- **Owner:** product owner (operator of record: repository owner).
- **Approver:** same (single-operator deployment; documented for the future
  institutional owner to re-approve).
- **Expiry:** 2027-05-14, or immediately before the first multi-school
  institutional rollout, whichever comes first.
- **Review trigger:** new deployment topology, new auth surface, any
  credential-stuffing incident.
- **Exit plan:** flip `registration_email_conflict` to `generic` at rollout
  (the mode exists and is tested); no code change is required for the flip.

## RA-BGPT-RAG-001-sub — real-corpus gate runs on the sample corpus until provisioning

- **Description:** the blocking eval gate measures the bundled 78-chunk
  sample corpus; the real served corpus is not yet available to CI.
- **Business impact:** retrieval regressions on the real corpus could reach
  a release without a blocking signal (the product's core promise).
- **Evidence:** eval-gate workflow status step (this wave);
  `retrieval-eval.yml` fail-closed wiring (`require_corpus`); nightly logs.
- **Compensating controls:** nightly real-corpus eval runs on the operator
  workstation against the exact served corpus (digest `1396faf2…` bound in
  the V4 baseline); release summary carries an explicit NOT RUN notice;
  corpus identity is enforced at serving time
  (`_verify_embedder_identity`, manifest fingerprint).
- **Owner:** repository owner (operator of record).
- **Expiry:** 2026-12-14 (provisioning is a Phase-0 item; the artifact
  location decision is the only blocker).
- **Review trigger:** any retrieval code change; any corpus change.
- **Exit plan:** provision the restricted artifact (repository variable
  `CORPUS_ARTIFACT_URL` / dispatch inputs in retrieval-eval.yml), then the
  gate runs fail-closed on the deployment digest and this acceptance
  expires.

## RA-BGPT-OPS-002 — restore/DR drill not yet executed (recorded, not silently open)

- **Description:** no completed restore drill on the live SQLite topology
  (E5 in the audit; AGENTS §15 known gap).
- **Compensating controls:** nightly `backup_loop` snapshots to the
  `bgpt-live-backups` volume with restore_test PASS evidence recorded
  2026-11-14 (users/students row counts verified); rollback = the retained
  stopped container `api-live-pre-0110`.
- **Owner:** repository owner (operator of record).
- **Expiry:** 2026-12-31 (drill needs a maintenance window).
- **Exit plan:** full restore into an isolated container + RPO/RTO
  measurement, per runbook §4 recipe (already scripted).
