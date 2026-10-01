# GCP-CONSTRAINTS — verify each before writing the Terraform that depends on it

Status column: `verify` until the first session confirms against current Google Cloud docs / the
Terraform registry, then `ok <date>` or `changed: <what>`.

| # | Item | What we believe | Status |
|---|---|---|---|
| 1 | Dataset location | permanent after creation; queries cannot join across locations | verify |
| 2 | Policy-tag taxonomy location | must match the dataset location | verify |
| 3 | Dynamic data masking | which BigQuery edition / pricing model it requires; on-demand vs Enterprise | verify |
| 4 | Row access policies | Terraform resource exists? else DDL via an idempotent scripted step | verify |
| 5 | Data masking Terraform | `google_bigquery_datapolicy` | verify |
| 6 | Taxonomy / policy tags Terraform | `google_data_catalog_taxonomy`, `google_data_catalog_policy_tag` | verify |
| 7 | Dataplex data scans Terraform | `google_dataplex_datascan` (DQ + profiling) | verify |
| 8 | Data Lineage API | automatic for BigQuery jobs; pricing; how to read it | verify |
| 9 | DLP inspection | per-GB pricing; free tier; row-limit sampling options | verify |
| 10 | Analytics Hub Terraform | data exchange + listing resources; pricing | verify |
| 11 | Budget Terraform | `google_billing_budget`; needs billing-account permissions on the author's account | verify |
| 12 | Workload Identity Federation | pool + provider for GitHub OIDC; attribute condition on repo | verify |
| 13 | Data Access audit logs | enabled by default for BigQuery; sink to BigQuery | verify |
| 14 | Time travel / fail-safe | time travel up to 7 days (configurable), fail-safe 7 more | verify |
| 15 | IAM Conditions | expiry via `request.time` condition on a binding | verify |
| 16 | VPC Service Controls | needs an organization; a standalone project may have none (→ D6) | verify |
| 17 | Cloud Composer | standing cost per day (for D1 decision) | verify |

Costs to watch: DLP per GB inspected, Dataplex scan processing, BigQuery bytes (first TiB/month free on-demand), Composer (avoid).
