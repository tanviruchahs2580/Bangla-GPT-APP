# Vercel Deployment Record — 2026-09-13

**Live URL:** https://bangla-gpt-app.vercel.app · **Project:** `bangla-gpt-app` (Vercel account `tanviruchahs2580`)

## Architecture decision

The app is a two-part system: a Vite React SPA and a long-running FastAPI service
(PostgreSQL, in-process job queue, SSE streaming, gunicorn workers). Vercel serverless
cannot host the API faithfully (ephemeral filesystem, no long-running worker/queue, no
bundled PostgreSQL), so the deployment is:

- **Vercel:** `apps/web` static SPA (Vite build, `dist/`), `vercel.json` provides
  1. `/api/:path*` → **API origin** proxy rewrite (browser stays same-origin — no CORS)
  2. `/(.*)` → `/index.html` SPA fallback (filesystem still wins for hashed assets)
- **API origin:** the live `api-live` container exposed through a Cloudflare quick tunnel
  (`api-tunnel` docker container → `host.docker.internal:8000`), currently
  `https://tablets-forecasts-designed-fair.trycloudflare.com`

> **2026-09-15 update:** the quick tunnel rotated after a restart and the deployed
> `vercel.json` still pointed at the dead `endif-bottom-inputs-pens` URL, which made
> every live `/api/*` call return `502 DNS_HOSTNAME_NOT_FOUND`. The tunnel was
> restarted, `vercel.json` updated to the URL above, and the web bundle redeployed.
> `api-live` now runs the `bangla-gpt-api:v0.9.1` image in **ENV=production** with
> real `JWT_SECRET`/`PII_ENC_KEY`/`METRICS_TOKEN`, an allowlisted `ALLOWED_ORIGINS`,
> and email verification delivered over a local `api-mailpit` SMTP sink (STARTTLS).
> Full QA evidence: `docs/FULL_QA_ENTERPRISE_AUDIT_2026-09-15.md`.

## Deployed revision

`0c2311b` + v0.9.1 source (release 0.9.1) — same bundle as the local live stack.

## Functional verification (as a user, on the Vercel URL)

| Check | Result |
|---|---|
| Landing (new WAVE-4 design, bn) | ✅ |
| Register fresh student (`vercel_1789304870801@example.com`) → auto-login | ✅ write path |
| Login with existing student (`wave4_1789289768166@example.com`) | ✅ read path |
| AI tutor — grounded structured answer, **SSE streaming through Vercel rewrite → tunnel → API** | ✅ |
| Quiz: 3-question run → submit → result review + explain buttons | ✅ |
| Me page (profile, parent-link, learning prefs) | ✅ |
| SPA deep links (`/student`, `/student/quiz`, `/student/me`, `/login`) | ✅ |
| `/api/health` through the proxy | ✅ `{"status":"ok"}` |
| Console errors across the journey | **zero** |

Evidence: `docs/uiux_renovation_evidence/vercel/vercel-student-home.png`

## Operational caveats (important)

1. **The API still runs on the owner's machine.** If the host or Docker stack is down,
   the Vercel site loads but API calls fail. For a permanent deployment, host the API on
   a VM/PaaS and point the rewrite there (or use a named Cloudflare tunnel).
2. **Quick tunnels rotate.** If `api-tunnel` restarts, its URL changes — update the
   `destination` in `apps/web/vercel.json` and redeploy (`npx vercel --prod` from
   `apps/web`). A named Cloudflare tunnel gives a stable hostname.
3. GHCR images from the v0.9.0 release remain available for self-hosting.
4. LLM provider on the live API is `mock` — grounded canned answers, no external AI key
   needed. Wire `LLM_PROVIDER`/key in the API environment to enable real AI responses.

## Test accounts

**Fixed demo credentials (work on every domain — one shared API/database):**

| Role | Email | Password |
|---|---|---|
| Student (class 6) | `student@demo.com` | `Demo@1234` |
| Teacher | `teacher@demo.com` | `Demo@1234` |
| Parent | `parent@demo.com` | `Demo@1234` |

Verified via API on all three entry points (direct :8000, Vercel `/api` proxy, tunnel
proxy) and via UI login on the Vercel domain (teacher dashboard + student home render,
zero console errors).

Earlier QA accounts (also valid, same password `StrongPass123!`): `wave4_1789289768166@example.com`
(student with progress data), `renuqa_teacher@example.com`, `beforeqa_1789260126@example.com`,
`vercel_1789304870801@example.com`.
