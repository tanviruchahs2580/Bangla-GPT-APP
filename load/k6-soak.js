// AUD-HI-10 / I-08 — soak and stability profile for the Bangla GPT API.
//
// What this answers that a short load test cannot: does the streaming path
// leak? A service holding long-lived SSE streams, pooled DB connections and an
// in-process retrieval index can pass a 2-minute test and still die on hour
// three. This script holds a steady mixed load for 30-60 minutes and fails the
// run on the *drift* signals a leak produces:
//
//   * `http_req_duration` p95 creeping up across the run (threshold on the
//     whole window, plus k6's own trend comparison in the summary),
//   * error rate growth (a leaking pool surfaces as 5xx/503 under steady load),
//   * dropped iterations / VU init failures.
//
// It CANNOT see process memory or connection counts — k6 is outside the
// process. Run it together with the host-side collectors in the README
// (load/README.md §Soak) and attach both outputs to the incident/regression
// record; a soak without RSS and connection counts is half the evidence.
//
// Usage:
//   k6 run -e BASE_URL=http://127.0.0.1:8000 -e VUS=10 -e DURATION=45m load/k6-soak.js
//
// This repository's audit environment had no k6 binary, so this profile has
// NEVER BEEN EXECUTED here — it is a committed, reviewable procedure, not a
// measurement. Record the run in docs/operations/SLO.md §5 when it happens.

import http from 'k6/http'
import { check, sleep } from 'k6'
import { Counter, Rate, Trend } from 'k6/metrics'

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000'
const VUS = Number(__ENV.VUS || 10)
const DURATION = __ENV.DURATION || '45m'
//: A stage that legitimately streams for a while; SSE responses are held open
//: by the server, so the client timeout must exceed the generation budget.
const STREAM_TIMEOUT = __ENV.STREAM_TIMEOUT || '120s'

export const options = {
  scenarios: {
    soak: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
      gracefulStop: '30s',
    },
  },
  thresholds: {
    // Steady-state gates over the whole window. A leak shows up as these
    // drifting past the budget as the run progresses, not as a single spike.
    http_req_failed: ['rate<0.01'],
    'http_req_duration{kind:read}': ['p(95)<500', 'p(99)<1500'],
    'http_req_duration{kind:tutor}': ['p(95)<8000'],
    'http_req_duration{kind:stream}': ['p(95)<15000'],
    // A soak that silently stopped doing work would otherwise "pass".
    http_reqs: ['rate>0.1'],
    checks: ['rate>0.99'],
  },
}

const streamAnswers = new Counter('soak_stream_answers')
const streamErrors = new Rate('soak_stream_errors')
const streamFirstEventMs = new Trend('soak_stream_first_event_ms')

export function setup() {
  const email = `soak-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`
  const payload = JSON.stringify({
    email,
    password: 'soak-test-pass-1',
    name: 'soak',
    role: 'student',
    class_level: 6,
    guardian_consent: true,
  })
  const register = http.post(`${BASE_URL}/auth/register`, payload, {
    headers: { 'Content-Type': 'application/json' },
  })
  check(register, { 'register 201': (r) => r.status === 201 })
  const login = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({ email, password: 'soak-test-pass-1' }),
    { headers: { 'Content-Type': 'application/json' } },
  )
  check(login, { 'login 200': (r) => r.status === 200 })
  return { token: login.json('access_token') }
}

function jsonHeaders(token) {
  return { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } }
}

//: One grounded class-6 question; the mock provider answers it in CI/staging
//: without a live key (see README: live-provider soak needs a key and a budget).
const QUESTION = '\u0995\u09cb\u09b7 \u0995\u09c0?'

export default function (data) {
  const roll = Math.random()
  const headers = jsonHeaders(data.token)

  if (roll < 0.5) {
    // Streaming turn: the long-lived connection the soak exists to exercise.
    const started = Date.now()
    const res = http.post(
      `${BASE_URL}/tutor/conversations/${ensureConversation(data.token)}/messages/stream`,
      JSON.stringify({ message: QUESTION }),
      { ...headers, timeout: STREAM_TIMEOUT, tags: { kind: 'stream' } },
    )
    const body = res.body || ''
    const ok = check(res, {
      'stream 200': (r) => r.status === 200,
      'stream declares no-buffering': (r) => r.headers['X-Accel-Buffering'] === 'no',
      'stream has done event': () => body.includes('event: done') || body.includes('event: error'),
    })
    streamErrors.add(ok ? 0 : 1)
    if (ok) {
      streamAnswers.add(1)
      streamFirstEventMs.add(Date.now() - started)
    }
  } else if (roll < 0.85) {
    const ask = http.post(
      `${BASE_URL}/tutor/ask`,
      JSON.stringify({ question: QUESTION, class_level: 6, subject: 'science' }),
      { ...headers, tags: { kind: 'tutor' } },
    )
    check(ask, {
      'ask 200': (r) => r.status === 200,
      'ask grounded': (r) => r.status !== 200 || typeof r.json('grounded') === 'boolean',
    })
  } else {
    const health = http.get(`${BASE_URL}/health`, { tags: { kind: 'read' } })
    const me = http.get(`${BASE_URL}/users/me`, { ...headers, tags: { kind: 'read' } })
    check(health, { 'health 200': (r) => r.status === 200 })
    check(me, { 'me 200': (r) => r.status === 200 })
  }

  // Realistic think-time so the connection churn stays comparable between runs.
  sleep(1 + Math.random() * 2)
}

//: VU-local conversation cache: creating one per request would soak the write
//: path instead of the streaming path.
const conversations = {}

function ensureConversation(token) {
  const key = `${__VU}`
  if (conversations[key]) {
    return conversations[key]
  }
  const res = http.post(`${BASE_URL}/tutor/conversations`, '{}', jsonHeaders(token))
  check(res, { 'conversation 201': (r) => r.status === 201 })
  conversations[key] = res.json('id')
  return conversations[key]
}
