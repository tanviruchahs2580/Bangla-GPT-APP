# S6.7 — Hosting decision record

Status: **DRAFT — awaiting human sign-off (🖐).** This document is the
decision package; the decision itself is a human responsibility (budget
owner + data-residency owner). Nothing here has been purchased or
provisioned.

## Scope

Where the production stack (api/worker/web/caddy/postgres/redis +
prometheus/grafana/backup, see docker-compose.yml) runs for pilot
(≤ 10k MAU) and scale (100k+), with a child-safety lens: the system
stores minors' chat history, so *data residency and processor
obligations outrank raw price*.

## Options evaluated

| # | Option | Pilot $/mo (approx) | Latency to Dhaka | Data residency | Ops burden | Notes |
|---|---|---|---|---|---|---|
| A | Single VPS, Docker Compose + Caddy (current stack, unchanged) — e.g. Hetzner Singapore / DigitalOcean Singapore / AWS Lightsail ap-southeast-1 | ~$20–60 | ~70–120 ms RTT | Provider-jurisdiction; pick region explicitly | Low–medium (we already operate it; CD exists: GHCR + SSH deploy w/ health-gated rollback) | Exactly matches what CI/CD already validates (v0.2.1 evidence) |
| B | Managed PaaS (Render / Railway / Fly.io) | $50–200 (HA-ish is pricier) | similar | US/EU regions mostly | Lowest | Postgres add-on nice, but 6-service compose doesn't map cleanly; egress + worker + SSE long-connections cost surprises |
| C | BD-local hosting (local DC VPS / ITPark) | varies, often $30–80 | ~5–20 ms | **Bangladesh** — strongest answer to any future govt data-localization ask | Medium (no GHCR/SSH parity guaranteed, backup tooling self-built) | Variable TLS/email deliverability; hardware SLAs weaker |
| D | Multi-node k8s (EKS/DOKS/GKE) | $300+ before data | 70–120 ms | configurable | High | Overkill below 100k MAU; this is the capacity_plan.md step-3 target, not the pilot answer |

## Decision criteria (weights agreed during S6 planning discussion)

1. Child-data handling & residency (30 %) — documented region, DPA
   available (dpa_template.md exists for our own downstream DPA),
   backup encryption (backup_dr.md).
2. Reliability at pilot load (25 %) — G6 evidence says one 2-vCPU node
   covers 100 schools; A/B both fine, D unnecessary.
3. Cost at pilot (20 %) — A cheapest with margin.
4. Ops fit with what CI/CD already proves (15 %) — A is literally the
   validated pipeline; B needs pipeline rewrite.
5. Growth headroom (10 %) — B, D better; A→D migration path documented
   in capacity_plan.md §6.

## Recommendation (pending sign-off)

**Phase 1 (pilot, G6–G7): Option A** — one VPS in a chosen region,
current compose stack, Caddy TLS, GHCR tag-deploys with health-gated
rollback (already built), nightly backup loop → offsite object storage.
Chosen region is itself a sign-off input (see below): default proposal
**AWS Lightsail / DigitalOcean ap-southeast-1 (Singapore)** unless the
authority requires BD residency, in which case Option C with a written
SLA review.

**Phase 2 (≥ ~50k MAU or 99.5 % SLA ask): split DB to managed Postgres
first**, then second app node (capacity_plan.md §6 step 2). k8s only at
step 3 triggers.

## Sign-off required (🖐 — human, not agent)

- [ ] Budget owner approves phase-1 vendor + region (cost ceiling written here: ______)
- [ ] Data-residency owner confirms jurisdiction acceptable for minors' data (region written here: ______)
- [ ] Backup offsite location + retention confirmed against backup_dr.md
- [ ] Approval date / initials: ______

Until these lines are filled by a human, this document is a proposal
only and **no hosting spend or provisioning is authorized**.
