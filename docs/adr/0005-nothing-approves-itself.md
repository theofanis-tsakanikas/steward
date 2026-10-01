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
- The custodian's ceiling is `clear_kinds: []` (`contracts/_roles.yaml`), so no contract can give it a
  tagged column in clear (`ROLE_CEILING_EXCEEDED`); `tests/test_compile.py::test_custodian_writes_but_never_reads_a_tag_in_clear`
  and the access eval check the compiled IAM; dataEditor lacks `setCategory`, so it cannot untag (B12).
- `contracts/_roles.yaml` is versioned: any change (directory, approver group, seats, ceilings) is a new
  version whose entry names a requester and an approver who was, **in the base commit's directory**, in the
  approver group, and is not the requester (`ROLES_CHANGE_UNAPPROVED`); a raised ceiling must be listed in
  that entry (`CEILING_RAISED`). An entry is an attestation, not a signature: offline, a forged name of a
  real approver cannot be told from a real one — the check makes the forgery explicit, attributable and
  reviewable in the diff, which is what a pull-request review can then refuse.
- gate-proof: "the self-approval check deleted", "a service account's approval accepted", "pipeline SA
  handed Fine-Grained Reader".
