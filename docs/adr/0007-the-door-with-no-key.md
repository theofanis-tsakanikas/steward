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
- Two bounded cases are not exceptions to this rule, and each is argued here:
  1. A dataset with **no contract at all** (the legacy export): its personal data passes only because the
     compiler holds every column at `restricted` (nobody can read it), and only while its
     `CONTRACT_MISSING` waiver lives.
  2. The **log-sink dataset** (`audit`, B15): Cloud Logging creates its tables, so they cannot carry
     Terraform tags. Value-found personal data there is accepted (info) only in tables named
     `cloudaudit_googleapis_com_*` and only of the kinds the contract declares, which may only be `email`;
     the contract validator refuses any reader but its steward and any grantable role. Any other table,
     or any other kind, blocks.
- **Ceilings** are part of the door: a contract cannot give a role `clear` beyond its ceiling, and raising
  a ceiling is a new version of `_roles.yaml` approved by someone who was an approver *before* the change
  and is not its requester (`ROLES_CHANGE_UNAPPROVED`, `CEILING_RAISED`) — so "tag it, then give
  everyone clear" is not a way round. That approval is an **attestation, not a signature** (ADR 0005).
- **"Removed" means a clean scan of the whole table, or of a stated sample.** `steward scan` prints its
  row limit; a clean sample is not proof of absence, and the evidence states n.

## Enforced by
- `tests/test_contracts.py::test_only_contract_missing_is_waivable` (a waiver for `PII_UNTAGGED` is refused).
- `tests/test_no_key.py` — the waiver is refused **and** the scan still blocks; the scan CLI ignores a PII
  waiver file; the gate imports nothing from the waiver machinery; removing the values clears the finding;
  the log-sink branch is narrow; a ceiling raise needs a new version approved from the base directory;
  adding yourself to the approver group in the same PR, reusing an old approval or rewriting history fails.
- `tests/test_classification.py::test_downgraded_ref_2_is_refused`, `::test_under_declared_kinds_are_refused`.
- gate-proof: "waiver for personal data" → `WAIVER_REFUSED`; "the tag removed from ref_2" → `PII_UNTAGGED`.

## Rejected
A "privacy officer override" for the classification gate. It would be the one key that opens every
door, held by the person least able to say what the values are.
