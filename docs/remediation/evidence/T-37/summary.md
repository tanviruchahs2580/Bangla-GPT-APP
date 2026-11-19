T-37 capacity smoke — LOCAL / MOCK / SQLITE, Windows workstation, single uvicorn worker, measure-only (no threshold).
Profile: 2 steps (10, 25 VUs) x 2 runs x 8 s per endpoint. /tutor/ask saturates its per-user rate limit at this concurrency (the 429s ARE the abuse-protection layer working — recorded as-is).

GET /health: requests_ok=4546 errors(429/401/other)=0 med-p50=6.1ms med-p95=13.2ms
GET /learn/progress: requests_ok=2136 errors(429/401/other)=0 med-p50=13.7ms med-p95=23.5ms
GET /students/me/invite-code: requests_ok=2026 errors(429/401/other)=0 med-p50=15.0ms med-p95=25.3ms
POST /notes: requests_ok=0 errors(429/401/other)=2102 med-p50=Nonems med-p95=Nonems
POST /tutor/ask (mock): requests_ok=60 errors(429/401/other)=4023 med-p50=32.3ms med-p95=56.65ms

POST /notes: 100% rejections are a payload-shape mismatch in the load script (422, not server failure) — the four correctly-shaped endpoints carry the latency data.

Raw: load-results-fixed.jsonl (corrected paths), load-results.jsonl (first run, two wrong paths recorded as 404s — script bug, noted), server.log.
No production capacity statement: single local worker, synthetic data, mock provider (card Never: no extrapolation; sizing is HO-6/HO-7).
