# Type-checking strictness: current state and the path to `--strict`

Audit finding: **CQ-02 (AUD-0007)** and **AUD-CD-10 (D-02)** — "Turn on strict
incrementally, or document a written incremental plan with a named owner and
target date." A flat `--strict` switch is still not reachable in one step, but
the path is no longer a plan on paper: it is a measured per-module ratchet.

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

`mypy src` is the CI gate (`ci.yml`, `api` job) and must be clean. It is clean
on a quiet tree; during the 2026-10-19 remediation pass the only errors any run
observed came from other agents' in-flight edits, never from these settings.

## The ratchet (operative since 2026-10-19)

Every module that already passes `mypy --strict` is listed in one
`[[tool.mypy.overrides]]` block in `apps/api/pyproject.toml` with the flags
`--strict` expands to. New code in a listed module must therefore be
strict-clean, and a module that becomes clean can be added to the list but a
listed module can never regress without failing CI.

### Why the flags are written out

`strict = true` inside a per-module override **applies globally** in mypy 2.4.0:
`mypy/config_parser.py` calls `set_strict_flags()` from
`parse_section` for any section containing `strict`, and that function mutates
the global `Options` object (`mypy/main.py`). Measured: a single-module
override with `strict = true` took `mypy src` from 23 errors to 287. The
per-module equivalent is the explicit flag list, minus the two flags mypy
rejects in per-module sections (`warn_redundant_casts`,
`no_implicit_reexport`) — both are already on globally, so the set is
equivalent to `--strict` for the listed modules.

Pattern reach is measured, not assumed: `module = "pkg"` covers only the
package `__init__`; `pkg.*` is needed for submodules.

### Measured state (2026-10-19, branch `chore/enterprise-hardening-20261018`)

- `mypy --strict src`: **296 errors in 56 of 138 modules** (final run,
  2026-10-19T10:xZ; the tree was moving all day, earlier snapshots read 299/57)
  — mostly `type-arg` (bare `dict` / `list` generics) and `no-untyped-def`.
- **82 modules strict-clean**, hence in the ratchet list (64 module patterns
  after collapsing the fully-clean packages `curriculum`, `ingestion`,
  `retrieval` and `routers.school` into `pkg.*` plus `pkg`).
- Acceptance test: `mypy src` with the ratchet block must produce output
  byte-identical to `mypy src` without it. That is the check that proves the
  ratchet adds no errors today; it must be re-run at landing because the tree
  moves (`E-R2-d2-001`, final run `E-R2-d2-009`).

### Adding a module to the ratchet

```bash
cd apps/api
mypy --strict src 2>&1 | grep ': error:' | cut -d: -f1 | sort -u   # dirty set
# any module not in that set may be added to the module list
mypy src                                                            # must stay clean
```

The list is regenerated and verified mechanically by the handoff script
described in `.audit/handoffs/pyproject-d2.md` (draft at
`.audit/tmp/d2-pyproject-draft.toml`).

## What is still off, and what it costs

Measured 2026-10-19 against `src/` (137 files); the per-flag staging from the
2026-10-09 revision is superseded by the ratchet, which needs no big-bang
commit:

| Flag family | Errors today | Nature of the work |
| --- | --- | --- |
| `disallow_any_generics` (`type-arg`) | 266 | Bare `dict` / `list` annotations. Each needs a decision about the real key and value types; guessing them would silence real errors later. |
| `disallow_untyped_defs` (`no-untyped-def`) | 29 | Public functions with no annotations; mechanical, but touches module boundaries. |
| everything else under `--strict` | 1 | One `no-untyped-call`. Individually fixable; each inline `# type: ignore` carries a reason where a suppression is deliberate. |

Full `--strict` switches on only when the dirty set is empty; until then the
ratchet is the contract.

## Rules

- No annotation may be added to make an error disappear. If the real type is
  unknown, leave the code untyped and record it; a confident wrong annotation
  is worse than a gap.
- New modules must be typed to whatever the repository already satisfies, and
  go into the ratchet list the moment they are strict-clean.
- Every `# type: ignore` carries an inline reason (and an issue link where a
  tracking issue exists). `warn_unused_ignores` stays on permanently, so a
  suppression that stops being necessary is reported rather than left behind.
- The ratchet only moves forward: the list grows. Removing a module from it is
  a deliberate act that needs the same measurement as adding one.

## Verifying

```bash
cd apps/api
mypy src                 # must be clean at the current stage
ruff check .             # RUF100 would report a stale suppression
```

CI runs both on every push (`api` job), so a regression in typing fails the
build rather than being noticed later.
