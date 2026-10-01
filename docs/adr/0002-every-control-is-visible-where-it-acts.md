# ADR 0002 — Every control is visible where it acts

**Status:** accepted 2026-10-01 · **Doctrine:** 2

## Decision
A value is shown masked in BigQuery's own output where the rule allows it (`XXXXX3944`, `XXXXX@domain`;
a hash or a NULL does not announce itself — the policy tag on the column does); a quarantined row
carries the rule that sent it there; a dataset's BigQuery description states its owner, steward,
custodian, lawful basis and retention; a catalog entry states when it was last reconciled and in which
mode (REAL or MOCK).

## Enforced by
- `core/compile.py`: dataset descriptions and labels (`owner`, `steward`, `contract-version`,
  `retention-days`); policy-tag display names state the masking profile.
- `core/gate_quality.py`: `QUARANTINE_UNATTRIBUTED` if a quarantined row lacks rule ids, row key, run id or
  owner. gate-proof: "quarantine without its rule id".
- Catalog mode on every output: T021 (not built yet).
