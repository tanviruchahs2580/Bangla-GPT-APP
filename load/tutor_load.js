// D21 — Load profile for Bangla GPT Tutor (k6).
//
// Usage (on a machine with k6 installed, API reachable):
//   k6 run -e BASE=http://staging.example.edu.bd -e VUS=50 -e DURATION=3m load/tutor_load.js
//
// Scenario mix mirrors real usage: ~70% tutor asks (LLM-bound), 20% quiz
// journeys, 10% progress reads. SLO gates at the bottom fail the run when
// p95 latency or error budget is exceeded.

import http from 'k6/http';
import { check, group, sleep } from 'k6';

const BASE = __ENV.BASE || 'http://127.0.0.1:8000';
const VUS = Number(__ENV.VUS || 20);
const DURATION = __ENV.DURATION || '2m';

export const options = {
  scenarios: {
    steady: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '30s', target: VUS },
        { duration: DURATION, target: VUS },
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    // SLO gates (capacity plan in docs/runbook.md §Capacity)
    'http_req_duration{kind:tutor}': ['p(95)<8000'], // LLM-bound path
    'http_req_duration{kind:quiz}': ['p(95)<500'],
    'http_req_duration{kind:progress}': ['p(95)<300'],
    http_req_failed: ['rate<0.02'],
  },
};

function registerAndLogin(email) {
  const res = http.post(
    `${BASE}/auth/register`,
    JSON.stringify({
      email,
      password: 'LoadTest123',
      name: `load-${__VU}`,
      role: 'student',
      class_level: 6,
      guardian_consent: true,
    }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  const loginRes = http.post(
    `${BASE}/auth/login`,
    JSON.stringify({ email, password: 'LoadTest123' }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  return loginRes.json('access_token');
}

export default function () {
  const email = `loadtest+${__VU}-${Date.now()}@example.com`;
  group('setup', () => {
    var token = registerAndLogin(email);
    if (!token) {
      sleep(1);
      return;
    }
    globalThis.__TOKEN = token;
  });
  const token = globalThis.__TOKEN;
  if (!token) return;
  const auth = { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };

  const roll = Math.random();
  if (roll < 0.7) {
    group('tutor', () => {
      const res = http.post(
        `${BASE}/tutor/ask`,
        JSON.stringify({
          question: 'সালোকসংশ্লেষণ কী?',
          class_level: 6,
          subject: 'science',
        }),
        Object.assign({ tags: { kind: 'tutor' } }, auth),
      );
      check(res, { 'tutor ok': (r) => r.status === 200 });
    });
  } else if (roll < 0.9) {
    group('quiz', () => {
      const started = http.post(
        `${BASE}/quizzes`,
        JSON.stringify({ student_id: Number(__VU), num_questions: 5 }),
        Object.assign({ tags: { kind: 'quiz' } }, auth),
      );
      if (started.status !== 201 && started.status !== 200) return;
      const body = started.json();
      const answers = Array(body.questions.length).fill(Math.floor(Math.random() * 4));
      http.post(
        `${BASE}/quizzes/${body.attempt_id}/submit`,
        JSON.stringify({ answers }),
        Object.assign({ tags: { kind: 'quiz' } }, auth),
      );
    });
  } else {
    group('progress', () => {
      const res = http.get(`${BASE}/students/${Number(__VU)}/progress`, {
        tags: { kind: 'progress' },
        headers: auth.headers,
      });
      check(res, { 'progress ok': (r) => r.status === 200 });
    });
  }
  sleep(1);
}
