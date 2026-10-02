# Security

Steward is a **reference implementation** on synthetic data for a fictional operator. It is not a
client system and it does not hold anyone's personal data.

## What is in scope

- The contracts, the core, the adapters, the Terraform, the CI gates, and the recorded demo.
- Identifiers of the author's GCP project (project id, project number, organization id, billing
  account id) must not appear in the tree. `scripts/check_ids.py` reads them from the git-ignored
  `terraform.tfvars` or from the environment and fails CI if they do.

## What is out of scope

- A live GCP estate. The demo estate was applied, captured and destroyed; the bootstrap layer is
  removed by deleting the project.
- A production Collibra or Looker instance. The catalog path is a **validating mock** unless
  `docs/COLLIBRA.md` says otherwise.
- Incoming reports about the fictional operator's "customers" — those rows are generated.

## Reporting

Open a GitHub issue or email the address on the author's GitHub profile. There is no bounty.

## Known limits

- Workload Identity Federation is pinned to this repository, `main`, and the `deploy` / `destroy`
  environments. A required reviewer on those environments is the second human at the button.
- BigQuery time travel and fail-safe keep deleted data recoverable for up to about 14 days; the
  retention report says so in its first line.
- The safe state is "treat it as sensitive and deny". A column of unknown sensitivity is masked;
  an access request with no decision is denied.
