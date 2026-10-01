# ADR 0003 — A default is never invented

**Status:** accepted 2026-10-01 · **Doctrine:** 3

## Decision
No default owner, retention, classification or row-access rule. A missing declaration is a failing build.

## Enforced by
- `core/contract.py`: `owner`, `steward`, `custodian`, `retention` (period + legal basis), `lawful_basis`,
  `readers`, `row_access` and every column's `classification` are required, with no defaults.
- `core/validate.py`: missing or null maps to `OWNERSHIP_MISSING`, `RETENTION_MISSING`,
  `CLASSIFICATION_MISSING`, `ROW_ACCESS_MISSING` — none waivable (only `CONTRACT_MISSING` is).
- Terraform: `var.principals` has no default; a seat without a principal fails the plan.
- gate-proof: "retention deleted", "owner deleted".

## Not a default
Values the code owns and states (DECISIONS B4/B9): `jobUser` per seat, `require_partition_filter`, 48 h
time travel, destroy-friendly flags.
