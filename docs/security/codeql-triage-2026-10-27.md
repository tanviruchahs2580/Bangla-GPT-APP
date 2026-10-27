# CodeQL / Scorecard alert triage — 2026-10-27

Every open code-scanning alert on the default branch carries a recorded
disposition here, so an untriaged alert list (itself a finding in any
security review) never ships. Dismissals were applied through the API with
the same wording; a future re-scan that re-opens one of these must be
triaged again, not silently re-dismissed.

## Code findings (js/*)

| Alert | Finding | Disposition | Justification |
|---|---|---|---|
| #1 | `js/identity-replacement` (test fixture) | **used in tests** | `string.replace` with itself in `teacherRedesign.test.tsx`; no production surface. |
| #2 | `js/xss-through-dom` — `data:`-URL into `<img src>` on the tutor image preview (AITutorPage) | **mitigated** | The payload is the student's OWN attached photo, mirrored back server-side only after the upload validator's MIME allowlist + magic-byte sniff + 1.5 MB cap (`routers/common.py` upload validation); React sets the src attribute (no HTML parsing). A guard on the render path keeps the preview to the same MIME allowlist. CSP (`script-src 'self'`, no inline) bounds any residual. |
| #3–#6 | `js/bad-tag-filter` + `js/incomplete-multi-character-sanitization` — the regex scrub in `safeMarkdown.tsx` (defense-in-depth) | **mitigated** | The primary control is architectural: `react-markdown` WITHOUT `rehype-raw` renders raw HTML as text (no sanitization to get wrong), CSP blocks inline/remote script, and `tests/safeMarkdown.test` pins the no-`rehype-raw` plugin list so the invariant cannot silently regress. The regex pre-strip stays as a belt-and-suspenders pass; the flagged patterns cannot introduce xss while the primary control holds. |

## Scorecard family (repo-process, no file)

| Alert | Check | Disposition | Justification |
|---|---|---|---|
| #9 | Binary-Artifacts (gradle-wrapper.jar) | **won't fix** | The Gradle wrapper JAR is standard, committed build infrastructure; integrity is pinned by `gradle-wrapper.properties` checksum consumers. |
| #10 | Pinned-Dependencies — `pip install ./apps/api` (Dockerfile) | **false positive** | Local-source install into the image; every external dependency comes from the hash-verified `constraints.txt` (pip-compile `--generate-hashes`, `--require-hashes` enforced in the same build). |
| #11 | Pinned-Dependencies — `scripts/smoke.sh` curl login | **false positive** | Not a dependency install at all — an authenticated API call in an ops script. |
| #12–#18 | Pinned-Dependencies — pip bootstrap lines in workflows (`pip install --upgrade pip`, setuptools floor, prep bowls) | **false positive** | The flagged lines bootstrap pip itself or install local sources; every THIRD-PARTY dependency is installed from the hash-verified lock in the same step (CI fails otherwise). |
| #19 | Maintained | **won't fix** | Single-maintainer cadence; every change lands via a PR with required status checks, last-push approval and enforced conversation resolution. Scorecard's activity heuristics cannot credit that shape. |
| #20 | Code-Review | **won't fix** | Same governance shape: 1-approving-review policy + conversation resolution is enforced on `main`; a second reviewer is an owner decision, not a code change. |
| #21 | Security-Policy | **false positive** | `SECURITY.md` exists at the repository root with the disclosure address and response window. |
| #22 | CII-Best-Practices | **won't fix** | An OpenSSF CII badge application is an owner-side process (best-effort passes most criteria already: pinned actions, SAST, release gates). |
| #23 | Fuzzing | **won't fix** | The retrieval/eval layer is exercised by a 634-item golden suite + adversarial red-team corpus on every push; web-app fuzzing harnesses (OSS-Fuzz) are disproportionate for this deployment stage. Revisit at national scale-up. |
| #24 | Vulnerabilities | **mitigated** | Dependabot security updates + secret scanning + push protection were enabled 2026-10-27 (they were the #52 finding); vulnerable-dependency surfaces now enter the same PR pipeline as everything else. |

## What stays open on purpose

None. All 21 alerts carried a recorded disposition on 2026-10-27. The list
should be re-reviewed at every audit; new alerts arrive untriaged and stay
that way until a human names them here.
