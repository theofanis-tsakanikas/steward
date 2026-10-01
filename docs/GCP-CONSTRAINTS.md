# GCP-CONSTRAINTS — verify each before writing the Terraform that depends on it

Status column: `verify` until the first session confirms against current Google Cloud docs / the
Terraform registry, then `ok <date>` or `changed: <what>`.

| # | Item | What we believe | Status |
|---|---|---|---|
| 1 | Dataset location | permanent after creation; queries cannot join across locations | verify |
| 2 | Policy-tag taxonomy location | must match the dataset location | ok 2026-10-01: "the taxonomy and the table must exist in the same regional location"; compiled with `region = lower(var.location)` = `eu` — that `eu` is accepted as a taxonomy region is confirmed only at first apply |
| 3 | Dynamic data masking | which BigQuery edition / pricing model it requires; on-demand vs Enterprise | **changed 2026-10-01:** the taxonomy's project *must belong to an organization* (DECISIONS B8); "may not be available when using reservations created with certain BigQuery editions" — on-demand assumed fine; max 9 data policies per tag (checked by the compiler) |
| 4 | Row access policies | Terraform resource exists? else DDL via an idempotent scripted step | ok 2026-10-01: `google_bigquery_row_access_policy` in google 7.46.1 (`filter_predicate`, `grantees`) |
| 5 | Data masking Terraform | `google_bigquery_datapolicy` | ok 2026-10-01: `google_bigquery_datapolicy_data_policy` (+ `_iam_member`), predefined SHA256 / ALWAYS_NULL / DEFAULT_MASKING_VALUE / LAST_FOUR_CHARACTERS / FIRST_FOUR_CHARACTERS / EMAIL_MASK / DATE_YEAR_MASK; types per rule in `core/compile.py` RULE_TYPES |
| 6 | Taxonomy / policy tags Terraform | `google_data_catalog_taxonomy`, `google_data_catalog_policy_tag` | ok 2026-10-01 (google 7.46.1); one tag per column, ≤5 levels, ≤1,000 tags per table; a user without Fine-Grained Reader who selects a tagged column gets an error listing the columns |
| 7 | Dataplex data scans Terraform | `google_dataplex_datascan` (DQ + profiling) | resource present in google 7.46.1; spec not yet read (T015) |
| 8 | Data Lineage API | automatic for BigQuery jobs; pricing; how to read it | verify |
| 9 | DLP inspection | per-GB pricing; free tier; row-limit sampling options | verify |
| 10 | Analytics Hub Terraform | data exchange + listing resources; pricing | resources present in google 7.46.1 (exchange, listing, subscription); pricing not yet read (T016) |
| 11 | Budget Terraform | `google_billing_budget`; needs billing-account permissions on the author's account | verify |
| 12 | Workload Identity Federation | pool + provider for GitHub OIDC; attribute condition on repo | verify |
| 13 | Data Access audit logs | enabled by default for BigQuery; sink to BigQuery | verify |
| 14 | Time travel / fail-safe | time travel up to 7 days (configurable), fail-safe 7 more | verify |
| 15 | IAM Conditions | expiry via `request.time` condition on a binding | verify |
| 16 | VPC Service Controls | needs an organization; a standalone project may have none (→ D6) | verify |
| 17 | Cloud Composer | standing cost per day (for D1 decision) | verify |

Costs to watch: DLP per GB inspected, Dataplex scan processing, BigQuery bytes (first TiB/month free on-demand), Composer (avoid).

Also present in google 7.46.1 and used for cross-layer publishing (no remote-state reads): `google_parameter_manager_parameter` / `_parameter_version` (resource and data source).
