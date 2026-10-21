// AUD-HI-11 / I-07 — dashboard and retrieval hot-path load profile.
//
// The gap this closes: the repository had load profiles for the tutor path but
// nothing that hammered the *read* surfaces (teacher/school/admin dashboards,
// chapter content, search) which is where the N+1 and missing-index problems
// live. Those endpoints are cheap individually and expensive in aggregate, so a
// tutor-only profile can pass while a dashboard melts a worker.
//
// Thresholds are tagged per kind so a failure names the surface:
//   dashboards  p95 < 800 ms      (analytics aggregates over seeded rows)
//   content     p95 < 400 ms      (chapter/document reads)
//   search      p95 < 600 ms      (BM25 + rerank over the corpus)
//   tutor       p95 < 8000 ms     (LLM-bound control path)
//   errors      < 1%
//
// Usage:
//   k6 run -e BASE_URL=http://127.0.0.1:8000 -e VUS=25 -e DURATION=3m load/k6-dashboards.js
//   # 100k-row variant: seed with apps/api/scripts/bench_dashboards.py --rows 100000
//
// NOT EXECUTED in the audit environment (no k6 binary — see load/README.md).
// The matching 100k-row *benchmark* is apps/api/scripts/bench_dashboards.py,
// which runs without k6 and records query counts plus wall time.

import http from 'k6/http'
import { check, group, sleep } from 'k6'

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000'
const VUS = Number(__ENV.VUS || 25)
const DURATION = __ENV.DURATION || '3m'

export const options = {
  scenarios: {
    reads: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '20s', target: VUS },
        { duration: DURATION, target: VUS },
        { duration: '20s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{kind:dashboard}': ['p(95)<800'],
    'http_req_duration{kind:content}': ['p(95)<400'],
    'http_req_duration{kind:search}': ['p(95)<600'],
    'http_req_duration{kind:tutor}': ['p(95)<8000'],
    checks: ['rate>0.99'],
  },
}

export function setup() {
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  const make = (role, extra) => {
    const email = `${role}-${stamp}@example.com`
    const base = { email, password: 'dash-load-pass-1', name: `load-${role}`, role }
    http.post(`${BASE_URL}/auth/register`, JSON.stringify({ ...base, ...extra }), {
      headers: { 'Content-Type': 'application/json' },
    })
    const login = http.post(
      `${BASE_URL}/auth/login`,
      JSON.stringify({ email, password: 'dash-load-pass-1' }),
      { headers: { 'Content-Type': 'application/json' } },
    )
    check(login, { [`login ${role} 200`]: (r) => r.status === 200 })
    return login.json('access_token')
  }
  // Teacher traffic needs the default-school classroom seeded by the operator;
  // the runner documents that precondition in load/README.md.
  return {
    teacher: make('teacher', {}),
    student: make('student', { class_level: 6, guardian_consent: true }),
  }
}

function auth(token, kind) {
  return { headers: { Authorization: `Bearer ${token}` }, tags: { kind } }
}

export default function (data) {
  const roll = Math.random()
  if (roll < 0.35) {
    group('teacher dashboards', () => {
      const roster = http.get(`${BASE_URL}/teacher/students?class_level=6`, auth(data.teacher, 'dashboard'))
      const analytics = http.get(`${BASE_URL}/teacher/classes/6/analytics`, auth(data.teacher, 'dashboard'))
      check(roster, { 'roster 200': (r) => r.status === 200 })
      check(analytics, { 'analytics 200': (r) => r.status === 200 })
    })
  } else if (roll < 0.6) {
    group('student dashboard and progress', () => {
      const summary = http.get(`${BASE_URL}/dashboard/summary`, auth(data.student, 'dashboard'))
      const progress = http.get(`${BASE_URL}/learn/progress`, auth(data.student, 'content'))
      check(summary, { 'summary 200': (r) => r.status === 200 })
      check(progress, { 'progress 200': (r) => r.status === 200 })
    })
  } else if (roll < 0.8) {
    group('search and content', () => {
      const search = http.get(`${BASE_URL}/search?q=%E0%A6%95%E0%A7%8B%E0%A6%B7`, auth(data.student, 'search'))
      const subjects = http.get(`${BASE_URL}/learn/subjects?class_level=6`, auth(data.student, 'content'))
      check(search, { 'search 200': (r) => r.status === 200 })
      check(subjects, { 'subjects 200': (r) => r.status === 200 })
    })
  } else {
    group('tutor control path', () => {
      const ask = http.post(
        `${BASE_URL}/tutor/ask`,
        JSON.stringify({ question: '\u0995\u09cb\u09b7 \u0995\u09c0?', class_level: 6, subject: 'science' }),
        { ...auth(data.student, 'tutor'), headers: { Authorization: `Bearer ${data.student}`, 'Content-Type': 'application/json' } },
      )
      check(ask, { 'ask 200': (r) => r.status === 200 })
    })
  }
  sleep(Math.random())
}
