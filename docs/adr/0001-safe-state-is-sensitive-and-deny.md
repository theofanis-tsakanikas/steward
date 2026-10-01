# ADR 0001 — The safe state is "treat it as sensitive and deny"

**Status:** accepted 2026-10-01 · **Doctrine:** 1

## Context
Every failure path needs a default outcome. In governance the two errors are not symmetric: over-masking
costs an analyst an access request; under-masking is a breach.

## Decision
Unknown sensitivity is masked; an undecided access request is denied; a conflict between what values
show and what a contract says resolves to the stricter reading. The catalog is the exception: if the
Collibra sync fails, BigQuery keeps working and the catalog carries a stale marker with its age — fail
closed on privacy, fail open (loudly, with a deadline) on documentation.

## Enforced by
- `core/compile.py`: every column of a table no contract declares, and every column the estate has that
  its contract does not, compiles to the `restricted` tag — no reader, no data policy.
- `core/classify.py`: one value is enough to flag a column (`MIN` = 1 hit); the cost is measured
  (`evals/classification/cases.yaml → known_over_flags`).
- `core/marketplace.py`: a request with no decision is `denied-no-decision`.
- gate-proof: "compiler forgets the safe state" → `PII_UNTAGGED` on `legacy.legacy_crm_export.tel_a`.

## Rejected
A default classification of `internal` for unknown columns (doctrine 3 forbids inventing it; doctrine 1
forbids it being permissive).
