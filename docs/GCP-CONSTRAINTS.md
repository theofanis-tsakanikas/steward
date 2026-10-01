# GCP-CONSTRAINTS — verify each before writing the Terraform that depends on it

Status column: `verify` until the first session confirms against current Google Cloud docs / the
Terraform registry, then `ok <date>` or `changed: <what>`.

| # | Item | What we believe | Status |
|---|---|---|---|
| 1 | Dataset location | permanent after creation; queries cannot join across locations | verify |
| 2 | Policy-tag taxonomy location | must match the dataset location | ok 2026-10-01: "the taxonomy and the table must exist in the same regional location"; compiled with `region = lower(var.location)` = `eu` — that `eu` is accepted as a taxonomy region is confirmed only at first apply |
| 3 | Dynamic data masking | which BigQuery edition / pricing model it requires; on-demand vs Enterprise | **changed 2026-10-01:** the taxonomy's project *must belong to an organization* (DECISIONS B8); "may not be available when using reservations created with certain BigQuery editions" — on-demand assumed fine; max 9 data policies per tag (checked by the compiler) |
| 4 | Row access policies | Terraform resource exists? else DDL via an idempotent scripted step | ok 2026-10-01: `google_bigquery_row_access_policy` in google 7.46.1 (`filter_predicate`, `grantees`). **`grantees` is input-only** ("initial members"): Terraform cannot see a grantee added or removed out of band, so T012 reads each policy's IAM live and digests it rather than trusting state |
| 5 | Data masking Terraform | `google_bigquery_datapolicy` | ok 2026-10-01: `google_bigquery_datapolicy_data_policy` (+ `_iam_member`), predefined SHA256 / ALWAYS_NULL / DEFAULT_MASKING_VALUE / LAST_FOUR_CHARACTERS / FIRST_FOUR_CHARACTERS / EMAIL_MASK / DATE_YEAR_MASK; types per rule in `core/compile.py` RULE_TYPES |
| 6 | Taxonomy / policy tags Terraform | `google_data_catalog_taxonomy`, `google_data_catalog_policy_tag` | ok 2026-10-01 (google 7.46.1); one tag per column, ≤5 levels, ≤1,000 tags per table; a user without Fine-Grained Reader who selects a tagged column gets an error listing the columns |
| 7 | Dataplex data scans Terraform | `google_dataplex_datascan` (DQ + profiling) | `google_dataplex_datascan` read from the 7.46.1 schema 2026-10-01 (`terraform providers schema`): rules take `dimension`, `column`, `threshold` (the fraction of rows that must pass), `ignore_null` and one expectation block; `row_filter` and `sampling_percent` are spec-level; `execution_identity.service_account` sets who the scan runs as. Each scan runs **as its dataset's custodian seat**: the custodian is in every unfiltered row access policy and holds no Fine-Grained Reader, so rules on policy-tagged columns are not generated (`core/compile_assurance.py` refuses a table whose row policies leave the custodian out). **Verify at first apply:** that the service account is accepted as the execution identity (the deployer holds `serviceAccountUser`; whether the Dataplex service agent also needs `serviceAccountTokenCreator` on it is not read); that a `row_filter` on the partition column satisfies `require_partition_filter`; that `eu` is accepted as the scan location. |
| 8 | Data Lineage API | automatic for BigQuery jobs; pricing; how to read it | verify |
| 9 | DLP inspection | per-GB pricing; free tier; row-limit sampling options | template schema read 2026-10-01 (`google_data_loss_prevention_inspect_template`); regional parent `projects/<p>/locations/europe-west1`; built-in infoTypes PHONE_NUMBER, EMAIL_ADDRESS, IBAN_CODE, IMEI_HARDWARE_ID, DATE_OF_BIRTH, STREET_ADDRESS plus one custom regex for IMSI. **Not read:** pricing, and whether a template can bound the rows inspected (it cannot: the sample size belongs to the inspection code, which is not written yet). **Verify:** that europe-west1 accepts all of these infoTypes. |
| 10 | Analytics Hub Terraform | data exchange + listing resources; pricing | resources present in google 7.46.1 (exchange, listing, subscription); pricing not yet read (T016) |
| 11 | Budget Terraform | `google_billing_budget`; needs billing-account permissions on the author's account | written (`infra/bootstrap/budget.tf`), `terraform validate` ok; **verify at first apply:** Billing Account Administrator on the author's account; the budget currency must equal the billing account's; the period is one calendar month (DECISIONS B38) |
| 12 | Workload Identity Federation | pool + provider for GitHub OIDC; attribute condition on repo | written (`infra/bootstrap/wif.tf`), `terraform validate` ok; claims used: `repository_owner_id`, `repository_id`, `repository`, `ref`, `environment` (all GitHub OIDC claims). **Verify at first deploy run:** that a job in the `deploy` environment started from `main` is accepted and one started from another branch is refused. |
| 13 | Data Access audit logs | enabled by default for BigQuery; sink to BigQuery | verify |
| 14 | Time travel / fail-safe | time travel up to 7 days (configurable), fail-safe 7 more | verify |
| 15 | IAM Conditions | expiry via `request.time` condition on a binding | verify |
| 16 | VPC Service Controls | needs an organization; a standalone project may have none (→ D6) | verify |
| 17 | Cloud Composer | standing cost per day (for D1 decision) | verify |

Costs to watch: DLP per GB inspected, Dataplex scan processing, BigQuery bytes (first TiB/month free on-demand), Composer (avoid).

Also present in google 7.46.1 and used for cross-layer publishing (no remote-state reads): `google_parameter_manager_parameter` / `_parameter_version` (resource and data source).

## First-apply risks (written down before the apply, so a failure is read against them)

1. `user_project_override` with a project whose Service Usage / Resource Manager APIs are not on yet: the first
   bootstrap apply may need `-target=google_project_service.api` first (the data source now waits for it).
2. The BigQuery Data Transfer service agent is addressed by its derived e-mail
   (`service-<number>@gcp-sa-bigquerydatatransfer.iam.gserviceaccount.com`) in governance, with
   `roles/iam.serviceAccountShortTermTokenMinter` on each custodian's service account (the role name is from the
   provider's documented example and not re-read). `google_project_service_identity` is not in the GA provider
   (7.46), so if the agent does not exist yet when the grant is applied, the apply fails once: use the API
   (create any transfer config in the console, or `bq mk --transfer_config`) and re-run.
3. Data masking needs an organization (DECISIONS B8, DAY-ONE 1b): without one the data policies are refused at apply.
4. Dataplex scans and DLP: the access questions in rows 7 and 9.
5. Cloud Functions 2nd gen build needs the build service account's roles (`steward-build`); the first build is the
   place a missing role would show.

## Estimated cost of one deploy → capture → destroy cycle (an estimate, not a quote)

Prices were not re-read for this estimate. Order of magnitude, for a week with the estate standing a few days and
synthetic data in the low single-digit GB: BigQuery storage and on-demand queries (every query capped by
`maximum_bytes_billed`) well under €1; DLP on samples (the sampling code is not written yet) and Dataplex on-demand scans on small tables a few
euros at most; Cloud Run functions, Scheduler (3 free jobs), Pub/Sub, Cloud Build, Cloud Storage, Parameter Manager,
Analytics Hub: cents, inside free tiers. **Expected total: under €10; ceiling €50** (alerts at €30 and €50, the guard
stops at €45). The one item that could change this is DLP or Dataplex run against more data than the samples; the bound must
be in the code that runs them (to be written, T014), not only in this estimate.
