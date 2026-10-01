# ADR 0004 — A correction never erases what was previously stated

**Status:** accepted 2026-10-01 · **Doctrine:** 4

## Decision
A contract change is a new version with a changelog line; earlier changelog entries survive unchanged;
a contract is retired with a final version, never deleted. The catalog keeps earlier descriptions and
classifications with their dates (T021).

## Enforced by
- `core/contract.py`: changelog versions are 1..n, the last equals `version`.
- `scripts/check_contract_versions.py` + `core/versioning.py`: against the base commit (PR base, or the
  push's `before`), a changed contract must bump its version and keep its history (`VERSION_NOT_BUMPED`,
  `CHANGELOG_REWRITTEN`, `CONTRACT_DELETED`); an unresolvable explicit base fails closed.
- gate-proof: "contract edited without a version bump".
