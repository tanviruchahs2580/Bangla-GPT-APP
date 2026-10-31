# Type-checking strictness: current state and the path to `--strict`

Audit finding: **CQ-02 (AUD-0007)** - "Turn on strict incrementally, or
document a written incremental plan with a named owner and target date."

This file is that plan. It exists so the gap between the current mypy
configuration and `--strict` is a known, measured quantity with a route, not an
accident.

## What is enabled today

Configured in `apps/api/pyproject.toml` under `[tool.mypy]`:

| Flag | Why |
| --- | --- |
| `warn_unused_configs` | an `[[overrides]]` block that matches nothing is a lie |
| `warn_redundant_casts` | a cast that changes nothing is misleading |
| `warn_unused_ignores` | dead suppressions are how AUD-0018's class of problem starts |
| `warn_return_any` | an `Any` return hides the real contract from every caller |
| `no_implicit_optional` | `x: int = None` is not an `int` |
| `strict_equality` | `True == 1` silently crossing types |
| `check_untyped_defs` | bodies of untyped functions are still checked |
| `warn_unreachable` | dead code after a terminating branch |
| `no_implicit_reexport` | `import x` must say `from x import y as y` |
| `strict_bytes` | `str`/`bytes` confusion |

`mypy src` is clean on 132 source files with all of these on.

## What is still off, and what it costs

Measured on 2026-10-30 against `src/` (132 files) - re-measured after wave 2, the counts below are current:

| Flag | Errors | Nature of the work |
| --- | --- | --- |
| `disallow_any_generics` | 285 | Bare `dict` / `list` annotations. Each needs a decision about the real key and value types; guessing them would be worse than leaving them implicit, because a wrong annotation silences real errors later. |
| `disallow_untyped_defs` | 28 | Public functions with no annotations. Mechanical, but touches the module boundary of the evaluation runner, ingestion and logging. |
| `disallow_untyped_decorators` | 0 today | Would apply to any decorator applied to an untyped function; the code has none. |
| `disallow_any_decorated` | 0 today | Same. |
| `no_partialtypes` | 0 today | Same. |
| `disallow_subclassing_any` | 0 today | Same. |
| `extra_checks` | 0 today | Same. |
| `disallow_untyped_calls` | 0 today | Same. |

A single `--strict` switch would therefore require roughly 185 edits across
about 30 modules. That is a day of mechanical work with a real risk of
introducing wrong annotations, which is exactly why it is staged rather than
done in one commit.

## The plan

**Stage 1 - done (2026-10-09).** The ten flags above, all clean.

**Stage 2 - `disallow_untyped_defs` (28 errors).** Annotate the public
functions in `evaluation/runner.py`, `nctb/acquisition.py`,
`nctb/bijoy.py`, `logging_config.py`, `services/circuit_breaker.py` and the
rest. No behaviour change; each function's types are already implied by its
body and its callers. Owner: whoever next touches those modules.
Target: within two sprints of this file's date.

**Stage 3 - `disallow_any_generics` (285 errors).** Do it module by module,
starting where the types are already known (`db/session.py`,
`providers/base.py`) and finishing where they are genuinely open
(`services/learn.py`, `services/govt_report.py`). Each module should be a
separate commit so a bad annotation is easy to revert in isolation.
Owner: module maintainers. Target: after Stage 2.

**Stage 4 - switch `--strict` on and delete the flag list.** Only when Stages
2 and 3 are complete, because `--strict` also enables the four flags currently
showing zero errors - those are unmeasured on future code, which is precisely
why they are listed rather than quietly assumed.

## Rules for the stages

- No annotation may be added to make an error disappear. If the real type is
  unknown, leave the code untyped and record it; a confident wrong annotation
  is worse than a gap.
- New modules must be typed to whatever stage the repository is at when they
  are added. Do not wait for stage 4 to start annotating.
- `warn_unused_ignores` stays on permanently, so any `# type: ignore` that
  stops being necessary is reported rather than left behind.

## Verifying

```bash
cd apps/api
mypy src                 # must be clean at the current stage
ruff check .             # RUF100 would report a stale suppression
```

CI runs both on every push (`api` job), so a regression in typing fails the
build rather than being noticed later.
