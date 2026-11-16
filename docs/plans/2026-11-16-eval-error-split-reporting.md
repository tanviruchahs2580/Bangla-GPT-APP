# Eval Error-Split Wilson Reporting Implementation Plan

> **For agentic workers:** Follow this bounded task in order. Use checkbox (`- [ ]`) steps and TDD; do not commit as part of this task.

**Goal:** Add Wilson 95% intervals to the CLI's existing derived false-refusal and false-answer report, without changing serialized metrics, gate behavior or inputs, thresholds, baselines, or serving.

**Architecture:** Keep this as a reporting-only change in the existing evaluation CLI. Derive interval bounds from the already-counted errors and denominators using the existing stdlib Wilson helper in `evaluation.stats`; leave `SuiteMetrics.as_dict()` and all gate comparisons untouched. Add focused tests alongside the existing CLI report tests.

**Tech Stack:** Python >=3.11 (CI: 3.11 and 3.12), pytest, existing `bangla_gpt_api.evaluation.stats.wilson`.

**Spec:** User-authorized bounded slice, recorded in the existing master plan at `docs/engineering/upgrade/agentic-upgrade-plan.md` §2 D2. This plan covers only completing its requested Wilson intervals and focused tests.

## Problem and Evidence

`apps/api/src/bangla_gpt_api/evaluation/cli.py::_report` already derives false refusals as `true_total - answered_true` and false answers as `false_total - refused_false`, then prints counts and point estimates (existing uncommitted change, lines 221–227). It does not print the Wilson intervals required by the slice. The existing helper `apps/api/src/bangla_gpt_api/evaluation/stats.py::wilson(successes, total)` returns a 95% interval and uses `[0, 1]` when `total <= 0` (lines 28–44). `SuiteMetrics.as_dict()` explicitly serializes the six gate metrics and is separate from `.intervals()`; `compare_gate_with_intervals()` calls `compare_gate(baseline, current.as_dict())` (`metrics.py` lines 246–274, 520–548). A focused `_report` test pattern exists in `apps/api/tests/test_w2b_eval_language_gate.py`.

## Global Constraints

- Runtime: API requires Python `>=3.11`; CI matrix runs Python `3.11` and `3.12` (`apps/api/pyproject.toml` line 5; `.github/workflows/ci.yml` lines 17–28).
- Architecture: evaluation is offline tooling; `.importlinter` forbids evaluation imports into routers and initialize. Reuse the existing `stats.wilson`; add no dependency or layer crossing.
- Measurement semantics: Wilson 95% intervals qualify reported rates; they do not replace the fixed `>2pp` gate (`evaluation/stats.py` lines 18–19; project `AGENTS.md` §7).
- Preserve all gate inputs, `SuiteMetrics.as_dict()`, gate behavior, thresholds, and `apps/api/eval/baseline_v3.json`; do not regenerate or edit baselines.
- Keep the change confined to the CLI and focused test module listed below. Do not modify serving, README, the existing master plan, `CHANGELOG.md`, or any generated/serialized artifact.
- Existing user changes in `README.md`, `apps/api/src/bangla_gpt_api/evaluation/cli.py`, and untracked `docs/engineering/upgrade/agentic-upgrade-plan.md` must be preserved. The untracked master plan is user-owned and out of scope.

## Review Focus

- True/answerable denominator is zero: report `n/a` as the point metric and a Wilson interval for zero observations (`[0.0000, 1.0000]`), without division by zero.
- False/refusal denominator is zero: same behavior for false-answer reporting.
- Error count is zero or equals denominator: bound should remain valid at the `[0, 1]` extremes using Wilson, not a normal approximation.
- Derived error count cannot become a different metric: false refusal uses `true_total - answered_true`; false answer uses `false_total - refused_false`.
- Reporting remains informational only: no values are added to `as_dict()` or baseline/gate inputs.

---

### Task 1: Complete Wilson intervals in error-split report

**Files:**
- Modify: `apps/api/src/bangla_gpt_api/evaluation/cli.py` (`_report`, preserving the existing dirty diff)
- Modify: `apps/api/tests/test_w2b_eval_language_gate.py`

**Interfaces:**
- Consumes: `bangla_gpt_api.evaluation.stats.wilson(successes: int, total: int, z: float = Z_95) -> tuple[float, float]`.
- Produces: An `ERROR SPLIT` line reporting each existing count and point rate plus a formatted 95% Wilson interval; no change to `SuiteMetrics.as_dict()`.

**Write-path ownership:**

| Path | Sole writer | Purpose |
|---|---|---|
| `apps/api/src/bangla_gpt_api/evaluation/cli.py` | API implementer | Add interval bounds to the existing derived report only. |
| `apps/api/tests/test_w2b_eval_language_gate.py` | API implementer | Pin report output, empty denominators, and unchanged metrics serialization. |
| All other paths | No writer in this task | Explicitly excluded, including README, upgrade master plan, changelog, baseline, constraints, generated artifacts, and serving modules. |

**Serialization and sequencing:**

- The new tests and CLI output change are one logical change and must land together. No contract fixture, baseline, schema, or generated report is involved.
- Preserve the pre-existing dirty CLI diff; implement only the missing intervals atop it. Preserve the unrelated dirty README and untracked master plan without editing, staging, or reverting them.

**Risks and reversibility:**

- Blast radius: evaluation CLI console output only; no serving path, user data, or production gate calculation is changed. Reversible by reverting the CLI/report-test change.
- Risk: accidentally changing gate data or changing the zero-denominator convention. Tests must assert `as_dict()` has no derived error-split keys and cover empty denominator output. Do not alter baseline, gate, or threshold.

- [ ] **Step 1: Add focused failing report tests**

  In `apps/api/tests/test_w2b_eval_language_gate.py`, construct `SuiteMetrics` with explicit counts and call `_report(metrics, None)`. Pin the two derived results with unequal denominators (e.g. 2 errors of 10 answerable items and 2 errors of 5 refusal-expected items): expect counts/rates `2/10 (0.2000)` and `2/5 (0.4000)`, and their Wilson bounds `wilson(2, 10)` / `wilson(2, 5)` formatted to four decimals. Assert the output contains the correct association of each interval to its named metric. Add a zero-denominator case asserting both point metrics are `n/a` and both intervals display `[0.0000, 1.0000]`. Assert the derived rates/intervals are not added to `metrics.as_dict()`.

- [ ] **Step 2: Run the focused tests and confirm they fail for the missing intervals**

  Run from repository root:
  `cd apps/api && python -m pytest tests/test_w2b_eval_language_gate.py -q`

  Expected: the new interval-output assertions fail because the existing `ERROR SPLIT` line only prints count and point rate; existing tests continue to exercise the surrounding report behavior.

- [ ] **Step 3: Add interval formatting to the existing CLI report**

  In `apps/api/src/bangla_gpt_api/evaluation/cli.py`, import the existing `wilson` helper and calculate intervals from the exact derived error numerators and their respective denominators: `wilson(false_refusals, true_total)` and `wilson(false_answers, false_total)`. Append each interval as `wilson95=[low, high]` with four decimals to its matching report field. Preserve current count/rate derivation, `n/a` point output when denominator is zero, user-added comment and logic, `metrics.as_dict()`, `_report`'s gate call, and all other CLI behavior. Wilson's existing zero-total result supplies `[0.0, 1.0]`.

- [ ] **Step 4: Run focused report tests**

  Run from repository root:
  `cd apps/api && python -m pytest tests/test_w2b_eval_language_gate.py -q`

  Expected: PASS, including the new interval and zero-denominator assertions.

- [ ] **Step 5: Run evaluation and static checks**

  Run from repository root:
  `cd apps/api && python -m pytest tests/test_w2b_eval_language_gate.py tests/test_w2_eval_stats.py -q`
  `cd apps/api && ruff check src/bangla_gpt_api/evaluation/cli.py tests/test_w2b_eval_language_gate.py && ruff format --check src/bangla_gpt_api/evaluation/cli.py tests/test_w2b_eval_language_gate.py`
  `cd apps/api && mypy src`

  Expected: all specified tests and static checks exit 0. Full CLI/eval gate and baseline-writing modes are not needed to prove this report-only change; do not invoke `--write-baseline`.

- [ ] **Step 6: Review scope and diff; do not commit**

  Run from repository root:
  `git diff --check`
  `git status --short`
  `git diff -- apps/api/src/bangla_gpt_api/evaluation/cli.py apps/api/tests/test_w2b_eval_language_gate.py`

  Confirm the implementation diff is limited to the CLI and its focused test, `as_dict()` and gate code are unchanged, baseline/threshold inputs are untouched, and the pre-existing README, CLI, and untracked master-plan changes remain present. Do not stage or commit.

## Open Decisions

- None for this authorized slice. The existing `wilson()` helper defines the interval method and empty-sample range. Any request to change gate inputs, thresholds, metrics serialization, baseline, serving behavior, or broader master-plan scope is outside this plan.
