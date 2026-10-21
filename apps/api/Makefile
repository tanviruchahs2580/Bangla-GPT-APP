# apps/api/Makefile -- evaluation entry points (A8-10)
#
# The root Makefile owns repo-wide targets; this file owns the API-side
# evaluation commands so `make -C apps/api rag-eval` works from anywhere. The
# interpreter is the repo venv when present (Windows Git Bash path), else the
# python on PATH, so a Linux checkout works unchanged.
PYTHON ?= $(shell test -x ../../.venv/Scripts/python.exe && echo ../../.venv/Scripts/python.exe || echo python)

.PHONY: rag-eval rag-eval-fast eval-gate eval-redteam eval-targets eval-variants stage-latency rehearsal-check help

help:
	@echo "rag-eval        A8-10: every evaluation number into eval/tmp/rag_eval/<run-id>/ (JSON + summary.md, no tracked writes)"
	@echo "rag-eval-fast   same, skipping the corpus-scale producers (index budget, ANN sweep, NCTB retrieval eval)"
	@echo "eval-gate       the CI regression gate (hermetic mock provider)"
	@echo "eval-redteam    the safety gate: all adversarial items refused, nothing leaked"
	@echo "eval-targets    A8-08: measured versus pre-registered targets, with CIs"
	@echo "eval-variants   A4-01: per-variant baselines on the held-out split"
	@echo "stage-latency   A9-01: stage p50/p95/p99 incl. TTFT under a stated concurrency"
	@echo "rehearsal-check the quality-ratchet/guard scripts the CI job runs (fast pre-flight)"

rag-eval:
	$(PYTHON) -m bangla_gpt_api.evaluation.cli --rag-eval

rag-eval-fast:
	$(PYTHON) -m bangla_gpt_api.evaluation.cli --rag-eval --no-corpus

eval-gate:
	$(PYTHON) -m bangla_gpt_api.evaluation.cli

eval-redteam:
	$(PYTHON) -m bangla_gpt_api.evaluation.cli --redteam

eval-targets:
	$(PYTHON) -m bangla_gpt_api.evaluation.cli --targets-report --out eval/tmp/targets_report.json

eval-variants:
	$(PYTHON) -m bangla_gpt_api.evaluation.cli --variant-matrix --out eval/tmp/variant_matrix.json

stage-latency:
	$(PYTHON) -m bangla_gpt_api.evaluation.cli --stage-latency --out eval/tmp/stage_latency.json
