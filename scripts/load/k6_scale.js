// S5.5 load test (k6). Targets from the master prompt:
//   500 RPS read mix, 50 RPS write mix, p95 < 400 ms on NON-AI endpoints.
// AI endpoints (/tutor/ask, /quiz/generate, ...) are deliberately excluded:
// their latency is provider-bound, so the p95 budget is meaningless there.
//
// Run against staging (human-provided URL + credentials, see docs/scale_report.md):
//   k6 run -e BASE_URL=https://staging.example \
//          -e LOAD_EMAIL=load@banglagpt.app -e LOAD_PASSWORD='...' \
//          scripts/load/k6_scale.js
//
// setup() logs in ONCE and reuses the JWT: /auth/login is rate-limited to
// 10/min by design, so logging in per-iteration would only measure the
// limiter. Pre-provision the load-test student with a throwaway account
// (role=student, guardian_consent=true); while SMTP is unconfigured new
// accounts are auto-verified and can log in immediately.
//
// For an infrastructure-only pass, start the API with PROVIDER=mock so no
// real Gemini calls can ever be reached from the load path.
import http from "k6/http";
import { check } from "k6";
import { randomIntBetween } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

const BASE = __ENV.BASE_URL || "http://127.0.0.1:8000";

export const options = {
  scenarios: {
    reads: {
      executor: "constant-arrival-rate",
      rate: 500,
      timeUnit: "1s",
      duration: "2m",
      preAllocatedVUs: 200,
      maxVUs: 800,
      exec: "readMix",
      tags: { mix: "read" },
    },
    writes: {
      executor: "constant-arrival-rate",
      rate: 50,
      timeUnit: "1s",
      duration: "2m",
      preAllocatedVUs: 30,
      maxVUs: 150,
      exec: "writeMix",
      tags: { mix: "write" },
    },
  },
  thresholds: {
    // PASS-WHEN: p95 < 400 ms on both mixes, <1% non-2xx/3xx.
    "http_req_duration{mix:read}": ["p(95)<400"],
    "http_req_duration{mix:write}": ["p(95)<400"],
    http_req_failed: ["rate<0.01"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "max"],
};

export function setup() {
  const res = http.post(
    `${BASE}/auth/login`,
    JSON.stringify({ email: __ENV.LOAD_EMAIL, password: __ENV.LOAD_PASSWORD }),
    { headers: { "Content-Type": "application/json" }, tags: { name: "login" } }
  );
  if (res.status !== 200) {
    throw new Error(`load login failed: ${res.status} ${res.body}`);
  }
  return { token: res.json().access_token };
}

// Authenticated read mix (weights approximate a student session):
// dashboard 40%, search 25%, revision 20%, health 15%.
export function readMix(data) {
  const t = data.token;
  const auth = { headers: { Authorization: `Bearer ${t}` }, tags: { mix: "read" } };
  const r = randomIntBetween(1, 100);
  let res;
  if (r <= 40) {
    res = http.get(`${BASE}/dashboard/summary`, Object.assign({}, auth, { tags: { mix: "read", name: "dashboard" } }));
  } else if (r <= 65) {
    res = http.get(
      `${BASE}/search?q=${encodeURIComponent("%E0%A6%95%E0%A7%8B%E0%A6%B7")}&class_level=6&limit=10`,
      Object.assign({}, auth, { tags: { mix: "read", name: "search" } })
    );
  } else if (r <= 85) {
    res = http.get(`${BASE}/revision/due`, Object.assign({}, auth, { tags: { mix: "read", name: "revision" } }));
  } else {
    res = http.get(`${BASE}/health`, { tags: { mix: "read", name: "health" } });
  }
  check(res, { "read 2xx": (x) => x.status >= 200 && x.status < 300 });
}

// Authenticated write mix, non-AI only: chapter-progress upsert.
// NOTE: POST /events is deliberately NOT part of the mix -- it is rate-limited
// to 60/min/IP by design, so from one load-generator IP the run would measure
// the limiter, not the API (verified locally: excess calls answer 429).
export function writeMix(data) {
  const t = data.token;
  const auth = { headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" } };
  const res = http.post(
    `${BASE}/learn/progress`,
    JSON.stringify({ subject: "math", chapter: "load", class_level: 6, read_pct: randomIntBetween(0, 100) }),
    Object.assign({}, auth, { tags: { mix: "write", name: "learn_progress" } })
  );
  check(res, { "write 2xx": (x) => x.status >= 200 && x.status < 300 });
}
