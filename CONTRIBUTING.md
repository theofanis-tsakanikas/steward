# Contributing

This is a pinned reference implementation, not a library under maintenance. Issues that show a
gate does not bite are welcome; drive-by dependency bumps are not.

## Local setup

Requires Python 3.12, `uv`, and (for Terraform) Terraform 1.15.x.

```bash
uv sync --all-extras --group dev
make preflight          # lint, tests, evals, gates, terraform validate — no GCP account
uv run --extra demo streamlit run app/Home.py
```

`make check` includes `scripts/check_ids.py`. On this machine it reads
`infra/bootstrap/terraform.tfvars` (git-ignored). A clone without that file, and without the
`STEWARD_*` environment variables, has nothing to refuse and the gate passes.

## Pull requests

- One concern per PR. CI is offline and must stay green.
- Do not commit `terraform.tfvars`, state, keys, or any GCP project / org / billing identifier.
- Repository content is English. The operator is fictional (Halverra Telecom).
