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
import { check, sleep } from 'k6'
import { Rate } from 'k6/metrics'

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8080'
const VUS = Number(__ENV.VUS || 20)
const DURATION = __ENV.DURATION || '1m'

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
  const email = `load-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`
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
  if (login.status !== 200) failures.add(1)
  return { token: login.json('access_token') }
}

export default function (data) {
  const headers = {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${data.token}`,
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
      'ask 200': (r) => r.status === 200,
      'ask grounded or refused': (r) => r.status !== 200 || typeof r.json('grounded') === 'boolean',
    })
  } else {
    const health = http.get(`${BASE_URL}/health`)
    const me = http.get(`${BASE_URL}/users/me`, headers)
    check(health, { 'health 200': (r) => r.status === 200 })
    check(me, { 'me 200': (r) => r.status === 200 })
  }
  sleep(Math.random() * 0.5)
}
