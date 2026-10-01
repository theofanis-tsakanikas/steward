# ADR 0002 — Every control is visible where it acts

**Status:** accepted 2026-10-01 · **Doctrine:** 2

## Decision
A masked value says it is masked (BigQuery's own masking output, e.g. `XXXXX3944`); a quarantined row
carries the rule that sent it there; a dataset's BigQuery description states its owner, steward,
custodian, lawful basis and retention; a catalog entry states when it was last reconciled and in which
mode (REAL or MOCK).

## Enforced by
- `core/compile.py`: dataset descriptions and labels (`owner`, `steward`, `contract-version`,
  `retention-days`); policy-tag display names state the masking profile.
- `core/gate_quality.py`: `QUARANTINE_UNATTRIBUTED` if a quarantined row lacks rule ids, row key, run id or
  owner. gate-proof: "quarantine without its rule id".
- Catalog mode on every output: T021.
