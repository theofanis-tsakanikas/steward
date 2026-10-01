# ADR 0007 — One door has no key

**Status:** accepted 2026-10-01 · **Doctrine:** 7 · **Atom:** T009

## Context
Every other control in Steward can be overridden by a named human with a reason and a deadline. One
cannot: a column in which personal data was **found by value** cannot be declared non-sensitive by anyone.
An approver would have nothing to approve *with* — the values are the evidence, and no signature changes
what the values are.

## Decision
- The classification gate (`steward scan`, `core/gate_classification.py`) takes **no waiver input at all**.
  Its blocking findings — `PII_UNTAGGED`, `PII_UNDECLARED_COLUMN`, `KIND_UNDECLARED`,
  `PII_CONTRACT_BROKEN` — can be cleared only by tagging the column (the contract classifies it as
  personal data and the compiled schema carries the tag) or by removing the data so that the scan comes
  back clean.
- The waiver mechanism refuses to even record such an exception: a waiver whose finding is anything but
  `CONTRACT_MISSING` is `WAIVER_REFUSED`.
- The one bounded case — a table with no contract at all (the legacy export) — is not an exception to
  this rule: its personal data passes only because the compiler holds every column at `restricted`
  (nobody can read it), and only while its `CONTRACT_MISSING` waiver lives.

## Enforced by
- `tests/test_contracts.py::test_only_contract_missing_is_waivable` (a waiver for `PII_UNTAGGED` is refused).
- `tests/test_no_key.py` — the waiver is refused **and** the scan still blocks, with the waiver in place.
- gate-proof: "waiver for personal data" → `WAIVER_REFUSED`; "the tag removed from ref_2" → `PII_UNTAGGED`.

## Rejected
A "privacy officer override" for the classification gate. It would be the one key that opens every
door, held by the person least able to say what the values are.
