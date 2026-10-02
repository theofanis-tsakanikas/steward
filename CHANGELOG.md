# Changelog

## 2026-10-02

- Live estate applied, captured (claims 1, 2, 5, 6) and destroyed. Sweep reported 0 leftovers.
  Bootstrap remains until the project is deleted.
- Catalog mode remains **MOCK**. The operator is fictional; every row is synthetic.
- `scripts/check_ids.py` refuses a tree that contains the author's GCP identifiers
  (read from git-ignored tfvars or the environment).
- Public repository. History rewritten so no live project number remains. `gitleaks --all` clean.

## 2026-10-01

- Offline claims 1–7, Streamlit demo in recorded mode, Terraform for every layer written and
  `terraform validate`d.
