# ADR 0005 — Nothing approves itself

**Status:** accepted 2026-10-01 · **Doctrine:** 5

## Decision
No pipeline, model or service account approves an access request, lowers a classification, clears a
quality finding or accepts its own drafted description. A requester never approves their own request.

## Enforced by
- `core/marketplace.py`: `SELF_APPROVAL` (case-insensitive), `SERVICE_ACCOUNT_APPROVAL`,
  `APPROVER_NOT_HUMAN`, `APPROVER_NOT_AUTHORISED`, `REQUESTER_NOT_IN_SEAT`.
- `core/validate.py`: owner, steward and marketplace approvers must resolve to named humans with no service
  account (`DUTY_NOT_HUMAN`); owner ≠ custodian, approvers ≠ custodian (`DUTY_CONFLICT`); a waiver is
  approved by a member of the privacy office who is neither its requester nor an owner of what it waives.
- `core/compile.py` (B12): the custodian writes but holds no Fine-Grained Reader; it cannot untag a
  column (dataEditor lacks `setCategory`).
- gate-proof: "the self-approval check deleted", "a service account's approval accepted", "pipeline SA
  handed Fine-Grained Reader".
