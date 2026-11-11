# Tooling Inventory — Bangla GPT frontend renovation

Honest inventory of what was available, what was actually invoked, and what was verified at
runtime. The master prompt §18.5 requires `installed`, `loaded`, `invoked` and `verified` to
be separated rather than all inferred from one config entry.

---

## 1. Skills

| Skill | Status | Where it was used |
|---|---|---|
| `bangla-gpt-frontend-studio:bangla-gpt-design-system` | installed, **loaded, invoked** | Guided the design-system audit: token inspection order (`styles.css` `:root` + `[data-theme="dark"]`, primitives in `components/ui.tsx`), reuse-before-adding, semantic-tokens-over-raw-values, light/dark and bn/en parity as acceptance criteria. Directly shaped `DESIGN-SYSTEM-SPEC.md`. |
| `bangla-gpt-frontend-studio:bengali-quality` | installed, **loaded, invoked** | Governed the Bengali decisions: no `letter-spacing`/`text-transform` on Bengali, line-height floors, numeral policy, mixed-script handling. Used when adding `offlineDeleteFailed` / `qpAcceptOne` and when checking the `.ring-inner` tracking finding. |
| `bangla-gpt-frontend-studio:frontend-design` | installed, **loaded** | Used for the anti-AI-slop audit and the "subtract, then solidify" direction — specifically for recognising the decorative layer (aurora blobs, per-button shine, duplicated gloss) as ornament rather than identity. |
| `bangla-gpt-frontend-studio:capacitor-mobile-ux` | installed, **NOT invoked** | Android/WebView work was not attempted: no `java`, `gradle` or `adb` on this machine (`AGENTS.md` §13). Invoking it would have produced advice that could not be applied or verified. |
| `nctb-bangla-nlp` (project-local) | available, **NOT invoked** | No tokenization, normalization, transliteration or PDF-shaping code was changed. It governs server-side Bangla text processing, which is outside this diff. |
| `rag-grounding-eval-gates` (project-local) | available, **NOT invoked** | No retrieval, prompt, threshold or eval change was made. The grounding *badge* rendering was preserved, not modified. |
| `student-data-protection` (project-local) | available, **consulted conceptually** | Its concerns (PII storage, consent, export/erasure, retention) were used as the review frame in `FRONTEND-SECURITY-REVIEW.md` §2. It was not formally invoked as a skill. Recorded as consulted-but-not-invoked rather than claimed as invoked. |
| `frontend-design` (claude-plugins-official) | installed, **NOT invoked** | Duplicate of the studio copy; loading two copies of the same guidance adds no signal. |
| `webapp-testing` | available, **NOT invoked** | Playwright MCP plus the project's own Playwright suite already covered the browser-work need; adding a third path would duplicate capability. |

**No Skill was installed, upgraded, or removed by this delivery.** Everything used was already
present. No behaviour of any Skill changed.

## 2. Plugins / marketplaces

| Plugin | Status | Evidence |
|---|---|---|
| `bangla-gpt-frontend-studio` v0.1.0 | installed, enabled, **skills loaded and used** | Four skills visible in the session listing; three invoked (above) |
| `zcode-plugins-official` (browser-use, computer-use, documents, pdf, presentations, spreadsheets, visualize, zcode-guide) | installed | Not needed except as noted |
| `claude-plugins-official` (frontend-design, sentry *) | installed | Sentry tooling not relevant: no Sentry issue was in scope, and error-monitoring setup is not a renovation task |

No plugin was added, removed, or reconfigured.

## 3. MCP servers

| Server | Status | Verified at runtime? | Notes |
|---|---|---|---|
| **Playwright MCP** (`mcp__playwright__*`) | connected, **invoked and verified** | **Yes** — `browser_navigate` to the running app returned a real page (`লগইন · বাংলা GPT টিউটর`), `browser_evaluate` returned real computed styles, `browser_take_screenshot` wrote a real PNG that was read back and inspected | Used to verify R-04 (`::placeholder` resolves `rgb(93,107,87)` at `opacity: 1`), R-08 (`.page-title` rule parses), and to capture the login-page screenshot |
| **Chrome DevTools MCP** | **unavailable** | No — failed with `Browser was not found at the configured executablePath (...chromium-1247\chrome-win64\chrome.exe)` | The configured revision does not exist on this machine; the installed revisions are `chromium-1243` and `chromium-1248`. Not repaired: Playwright MCP already covered the need, and repairing a second browser server would duplicate capability. **Decision: not needed.** |
| **Context7** | connected, **NOT invoked** | No | No library API behaviour was in question. The changes use CSS custom properties, `color-mix`, `conic-gradient`, a React element type swap, and a Vitest helper — none of which needed version-specific documentation, and the installed versions were read from `package.json`/lockfile instead. |
| **Figma MCP** | **not applicable** | No | No Figma file was supplied or authorised. The prompt forbids inventing a design URL; product code and the existing reviewed visual baselines were the design authority. |
| **GitHub MCP** | not used | No | The task explicitly forbids push, merge, release and settings changes. `git` locally was sufficient for inspection. |
| **shadcn / prisma MCP** | installed, **NOT invoked** | No | `shadcn` is irrelevant: `AGENTS.md` §4 forbids a CSS framework and the project uses plain CSS. Prisma is irrelevant: the backend is SQLAlchemy/Alembic and no schema change was in scope. |
| **documents / pdf / presentations / spreadsheets MCP** | installed, **NOT invoked** | No | No Office/PDF deliverable was requested. |

## 4. Subagents

The workflow defined by the studio plugin is read-only audit → spec → plan → approved
implementation → independent review. This delivery used it as follows.

| Agent | Type | Status | Task |
|---|---|---|---|
| `frontend-design-lead` | read-only | **invoked, verified** | Full design-system audit of `styles.css` and `ui.tsx`: token blocks, typography, colour roles, contrast gaps, component inventory, breakpoints, motion, anti-slop. Produced line-referenced findings; **every load-bearing claim was independently re-verified by the orchestrator before being recorded** (see §5) |
| `Explore` (×2) | read-only | **invoked, verified** | (a) capability inventory across all 22 page modules → became `FEATURE-LOCK-REGISTER.md`; (b) local boot/e2e-harness investigation → produced the repro recipe used in `TEST-STRATEGY-AND-MATRIX.md` §6, including the `reuseExistingServer` seeding trap that later bit the first e2e run |
| `security-reviewer` | read-only | **invoked** | Independent security/privacy review of the diff incl. the children's-data angle |
| `frontend-visual-reviewer` | read-only | **invoked** | Independent attempt to falsify the "behaviour preserved" claim: behaviour deltas, test integrity, the new `cssTokens.ts` parser, i18n parity, the CSS changes, and whether `animation-iteration-count: 1` misrepresents any live state |

**No implementer subagent was used.** All product-code edits were made by the orchestrator.
That is a deliberate choice, not an omission: the change set is small enough to keep in one
head, and the master prompt's prohibition on concurrent writers to shared files
(`styles.css` is a single 5,156-line file every change touches) makes parallel writers a
correctness risk rather than a speed-up. The trade-off is that the implementer and the
integrator are the same agent, which is why the two independent read-only reviewers matter
more here — their findings are in `REGRESSION-AND-INDEPENDENT-REVIEW.md`.

## 5. Verification of delegated findings

Delegating a finding does not make it true. Each load-bearing claim from the design audit was
re-checked by the orchestrator before it entered a register:

| Claim from the audit | Independently re-verified | Result |
|---|---|---|
| Both contrast guards read only the first token block | Read `contrastTokens.test.ts:17-18` and `formControlBoundary.test.ts:24-25` directly | **Confirmed** — `indexOf`-based |
| Hero placeholder measures 4.24–4.31:1 | Wrote `evidence/accessibility/contrast_audit.py`, computed WCAG ratios from the real token values | **Confirmed exactly** — 4.24 / 4.31 / 4.28 |
| Ring track measures 1.21:1 / 1.16:1 | Same script | **Confirmed exactly** |
| `.stat` rendered three ways; 86 raw sites vs 5 `<Stat>` uses | grep counts | **Confirmed** |
| Two button vocabularies with 7 raw call sites | grep; also found `formControlBoundary.test.ts:107` asserts one of them, which the audit had not flagged | **Confirmed and extended** |
| 52 `rgba()` literals outside token lines | grep, replicating the guard's comment-masking | **Confirmed** |
| `--glass-bg` duplicated with an identical value | Read both lines | **Confirmed** |
| `@keyframes voice-pulse` defined twice | Read both definitions; found they are **different animations**, so the later silently broke the first consumer's intent — a stronger conclusion than the audit's "silently replaces the first" | **Confirmed and sharpened** |
| The malformed selector causes a *visible* defect across 7 staff dashboards | Built a minimal repro, loaded it in a real browser, measured: `rulesFound.probe = 0` (rule dropped) **but** read the base `h1` rule at `styles.css:380`, which already sets the font size — so the real delta is only the bottom margin | **PARTIALLY REFUTED** — the audit's implied severity was too high; recorded as **P3**, not P1 |

That last row is the reason this section exists. The heading said "seven pages unstyled"; the
measurement said "seven pages with a ~5 px margin difference". The correction is recorded in
`RISK-REGISTER.md` R-08 and in `CONTENT-AND-TERMINOLOGY.md` §5 item 4.

## 6. Not available, and why it matters

| Capability | State | Consequence |
|---|---|---|
| Chrome DevTools MCP | unavailable (stale browser path) | Worked around with Playwright MCP; no capability lost |
| Android SDK, `java`, `gradle`, `adb` | absent | **Android/WebView verification is BLOCKED.** Browser viewport emulation is never reported as device testing |
| Field performance data / RUM | does not exist | All performance figures are lab-only and labelled so |
| A real assistive-technology session | not performed | The accessibility report states this plainly rather than implying an axe pass is equivalent |
| A working dev API/database pairing | the running API serves a different SQLite file than the seed target | Worked around by running Playwright self-contained (`CI=1 E2E_API_PORT=8100 E2E_WEB_PORT=5273`); the owner's running services were left untouched |
