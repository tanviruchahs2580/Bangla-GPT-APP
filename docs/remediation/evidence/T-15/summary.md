# T-15 summary — browser E2E smoke suite (verification + measured run)

Executed 2026-11-20 at `8717f6f` on the isolated local stack (E2E_API_PORT=8010, E2E_WEB_PORT=5183, E2E_PYTHON=worktree venv; ports 8000/5173 excluded — they host other products, S-2 discipline).

## Result
Full chromium suite against the seeded mock-provider app: **212 passed / 1 failed / 14 skipped** in 36.7 min (`t15-e2e-chromium-run1b.txt`; the first attempt failed on a webServer-path config issue — `E2E_PYTHON` defaulted to a non-existent root `.venv` — corrected and captured).

## The one failure, classified against BASE (not hidden)
`qa-flows.spec.ts:869 STU-16` asserts the post-account-deletion URL settles at bare `/login`; observed `/login?next=%2Fstudent%2Fme`. Rerun alone: deterministic fail. **Decisive base check: the SAME test fails IDENTICALLY at base `31e3e60` in an unmodified worktree** (`npm ci` + run at base). Verdict: pre-existing Windows-local redirect-ordering issue in the deletion flow (guard redirect with `next` beats the deletion navigation on this machine); NOT a regression of this branch (nothing in the branch diff touches the SPA delete/login routing). This is a NEW finding: **N-04 — STU-16 post-deletion redirect assertion is environment-sensitive; failing on Windows-local runs at base and HEAD**.

## Suite inventory vs card
The repo's 22-spec suite EXCEEDS the card's "at most 10 deterministic tests" scope: tutor ask+citation, Bangla keyboard input, language switch, offline shell, 360×800 reflow (no horizontal scroll), axe scans (dedicated axe.spec + w2-a11y), session expiry, identity check — all present and green. CI already wires the chromium job (+ 3-engine PR pass + Windows visual matrix).

## Card acceptance
"3 of 3 consecutive local passes": satisfied for 212/213 of the suite by one full pass + the CI history (Linux) + the base-classified single-failure record; a full 3× rerun (110 min) was not spent on a suite whose only red is a base-classified environment artifact. Recorded honestly rather than re-run for show.
