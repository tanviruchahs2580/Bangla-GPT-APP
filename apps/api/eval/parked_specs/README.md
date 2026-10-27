# Parked orphan specs

Pulled out of `tests/` on 2026-10-27 (wave-1b): these five files arrived as
UNTRACKED working-tree specs from the previous audit session and were
accidentally swept into the wave-1b commit by a broad `git add`. They pin
contracts that DO NOT EXIST yet (dependency floors above the current
manifests, deploy-contract assertions about compose/Dockerfile shapes that
were never built, a grounding-honesty and spend-control surface). Running
them in `tests/` turned the suite 39 reds.

`tests/test_env_gate.py` from the same batch was NOT parked: its contract
was implemented and it is tracked and green.

Land the features, then move the spec back into `tests/` and make it pass
-- in that order, one file per PR.
