# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform** (planned).

> **Status: FOUNDATION ONLY — application development has NOT started yet.**
> This repository currently contains only repository infrastructure:
> Git configuration, `.gitignore`, and a CI sanity workflow.
> No application source code exists by design at this phase.

## Repository layout

```text
BanglaGptApp/
├── .github/workflows/repository-sanity.yml   # CI: repo-level sanity checks only
├── .gitignore                                 # tech-agnostic safety baseline
└── README.md
```

## CI/CD roadmap

The current pipeline intentionally performs **repository-level checks only** —
it does NOT pretend to build or test an application that does not exist yet.

After the technology stack is selected, the pipeline will expand to:

```text
Checkout
  → Runtime setup
  → Dependency installation
  → Lint
  → Formatting check
  → Type check
  → Unit tests
  → Integration tests
  → Security scans
  → Build
  → Artifact validation
  → Release
  → Deployment   (intentionally pending: no app, no target, no credentials)
```

Each future stage will be added **only when its commands actually exist and are
verified locally** first.
