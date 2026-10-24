// B16 — mixed-workload load test for the Bangla GPT API.
//
// Usage:
//   k6 run -e BASE_URL=http://127.0.0.1:8080 load/k6-tutor.js
//   Scale via environment: -e VUS=50 -e DURATION=2m
//
// Gates (CI/release): error rate < 1%, p95 < 800 ms.
// The default profile is a modest laptop-scale smoke; set VUS/DURATION to
// approach the 500–1000 concurrent target on an appropriately sized runner.

import http from 'k6/http'
// The coverage gate REFUSES off-corpus questions with HTTP 400 +
// refused_reason=insufficient_evidence — a correct, fast answer, not an
// error (CI runs without the full NCTB corpus, so most load questions take
// the refusal branch). Count 200 and 400 as "expected" so http_req_failed
// measures real failures (5xx, network); the ask check below pins the
// semantic: grounded answer OR coded refusal.
http.setResponseCallback(http.expectedStatuses(200, 201, 400))
import { check, sleep } from 'k6'
import { Rate } from 'k6/metrics'

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8080'
const VUS = Number(__ENV.VUS || 20)
const DURATION = __ENV.DURATION || '1m'
// The app rate-limits by design: /auth/register and /auth/login at 10/min
// per IP, /tutor/ask at 30/min per USER. A load mix over ONE account is a
// 429 generator, and a setup burst over 10 accounts trips the register
// ceiling — the first time this script actually ran (against a live API) it
// failed at 57% because nobody had ever executed the "CI gate" it
// advertised. The defaults stay under every ceiling: 8 users (register/login
// headroom), iteration pacing that keeps each account under 30 asks/min.
// To push aggregate throughput beyond ~8x30 asks/min, raise the limits on
// the load target (RATE_LIMIT_* env) or run k6 from multiple IPs.
const USERS = Number(__ENV.USERS || 8)

export const options = {
  scenarios: {
    mixed: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '15s', target: VUS },
        { duration: DURATION, target: VUS },
        { duration: '15s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<800'],
    checks: ['rate>0.99'],
  },
}

const failures = new Rate('failed_auth')

export function setup() {
  const tokens = []
  for (let i = 0; i < USERS; i++) {
    const email = `load-${Date.now()}-${i}-${Math.random().toString(36).slice(2)}@example.com`
    const register = http.post(
      `${BASE_URL}/auth/register`,
      JSON.stringify({
        email,
        password: 'load-test-pass-1',
        name: 'লোড টেস্ট',
        role: 'student',
        class_level: 6,
        guardian_consent: true,
      }),
      { headers: { 'Content-Type': 'application/json' } },
    )
    check(register, { 'register 201': (r) => r.status === 201 })
    const login = http.post(
      `${BASE_URL}/auth/login`,
      JSON.stringify({ email, password: 'load-test-pass-1' }),
      { headers: { 'Content-Type': 'application/json' } },
    )
    check(login, { 'login 200': (r) => r.status === 200 })
    if (login.status !== 200) {
      failures.add(1)
      continue
    }
    tokens.push(login.json('access_token'))
  }
  if (tokens.length === 0) throw new Error('setup: no user could log in')
  return { tokens }
}

export default function (data) {
  const token = data.tokens[Math.floor(Math.random() * data.tokens.length)]
  const headers = {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
  }

  // 80% tutor ask / 20% health+profile reads
  if (Math.random() < 0.8) {
    const ask = http.post(
      `${BASE_URL}/tutor/ask`,
      JSON.stringify({ question: 'কোষ কী?', class_level: 6, subject: 'science' }),
      headers,
    )
    check(ask, {
      'ask answered or gated-refused': (r) =>
        r.status === 200 ||
        (r.status === 400 && r.json('refused_reason') === 'insufficient_evidence'),
    })
  } else {
    const health = http.get(`${BASE_URL}/health`)
    const me = http.get(`${BASE_URL}/users/me`, headers)
    check(health, { 'health 200': (r) => r.status === 200 })
    check(me, { 'me 200': (r) => r.status === 200 })
  }
  // pacing: with 8 pooled accounts this keeps every account under its
  // 30/min /tutor/ask ceiling while VUs still overlap on the server
  sleep(0.5 + Math.random())
}
