SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help install test lint fmt evals claims check gate-proof preflight preflight-fast contracts-validate \
        synthetic generate demo evidence evidence-check capture tf-fmt tf-validate ci clean

UV  ?= uv
PY  := $(UV) run python

help: ## list the targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## the dev environment (uv, Python 3.12, demo extras)
	$(UV) sync --all-extras --group dev

test: ## the unit suite
	$(UV) run pytest

lint: ## ruff check + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt: ## auto-format
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

evals: ## score every claim harness in evals/
	$(PY) evals/run.py

claims: evals ## alias of evals (portfolio Makefile contract)

check: ## every structural gate + every generator in --check mode
	$(PY) scripts/check_core_purity.py
	$(PY) scripts/check_contract_versions.py
	$(PY) scripts/check_workflows.py
	$(PY) scripts/check_contract_fields.py
	$(UV) run steward validate
	$(UV) run steward scan
	$(UV) run steward compile
	$(UV) run steward quality
	$(UV) run steward marketplace
	$(UV) run steward retention
	$(UV) run steward lineage
	$(UV) run steward catalog
	$(UV) run steward evidence-check
	$(PY) scripts/check_demo_numbers.py
	$(PY) scripts/check_oidc_subjects.py
	$(PY) scripts/check_deployer_grants.py
	$(PY) scripts/check_assurance.py
	$(PY) synthetic/generate.py --check
	$(PY) scripts/generate.py --check

gate-proof: ## plant violations; the NAMED gate must refuse each one
	$(PY) scripts/gate_proof.py --json out/gate_proof.json

preflight: lint test check evals gate-proof tf-validate ## everything CI runs, offline

preflight-fast: lint test check ## the quick subset

contracts-validate: ## contracts load and cross-check
	$(UV) run steward validate

synthetic: ## regenerate the fictional operator's data (seeded, deterministic)
	$(PY) synthetic/generate.py

synthetic-sample: ## print 20 rows per synthetic table
	$(PY) synthetic/sample.py 20

generate: ## regenerate every generated artefact from contracts
	$(PY) scripts/generate.py

evidence: ## rebuild the offline fixture evidence the demo reads
	$(UV) run steward evidence --mode fixture

evidence-gates: ## record a full gate-proof run as evidence (minutes); needed whenever a mutation changes
	$(PY) scripts/gate_proof.py --worktree --skip evidence --json out/gate_proof.json
	$(UV) run steward evidence --gates out/gate_proof.json

capture: ## capture live evidence from a deployed estate (needs `uv sync --extra gcp` and credentials); PROJECT=...
	$(UV) run steward capture --project $(PROJECT) $(if $(WHAT),--what $(WHAT),)

evidence-check: ## re-verify every evidence file against its digest, offline
	$(UV) run steward evidence-check

demo: ## the Streamlit demo in recorded mode (no network)
	$(UV) run --extra demo streamlit run app/Home.py

tf-fmt: ## terraform fmt, every layer
	terraform fmt -recursive infra

tf-validate: ## terraform fmt -check + validate, every layer, no backend, no credentials
	$(PY) scripts/tf_validate.py

ci: preflight ## what CI runs

destroy: ## dispatch the destroy workflow (needs the gh CLI); then `gh run watch`
	gh workflow run destroy.yml -f confirm=destroy-steward

clean:
	rm -rf .pytest_cache .ruff_cache out
