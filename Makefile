SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help install test lint fmt evals claims check gate-proof preflight preflight-fast contracts-validate \
        synthetic generate demo evidence evidence-check tf-fmt tf-validate ci clean

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
	$(PY) scripts/generate.py --check

gate-proof: ## plant violations; the NAMED gate must refuse each one
	$(PY) scripts/gate_proof.py

preflight: lint test check evals gate-proof tf-validate ## everything CI runs, offline

preflight-fast: lint test check ## the quick subset

contracts-validate: ## contracts load and cross-check
	$(UV) run steward validate

synthetic: ## regenerate the fictional operator's data (seeded, deterministic)
	$(PY) synthetic/generate.py

generate: ## regenerate every generated artefact from contracts
	$(PY) scripts/generate.py

evidence: ## rebuild the offline fixture evidence the demo reads
	$(UV) run steward evidence --mode fixture

evidence-check: ## re-verify every evidence file against its digest, offline
	$(UV) run steward evidence-check

demo: ## the Streamlit demo in recorded mode (no network)
	$(UV) run --extra demo streamlit run app/Home.py

tf-fmt: ## terraform fmt, every layer
	terraform fmt -recursive infra

tf-validate: ## terraform fmt -check + validate, every layer, no backend, no credentials
	$(PY) scripts/tf_validate.py

ci: preflight ## what CI runs

clean:
	rm -rf .pytest_cache .ruff_cache out
