# INTERVIEW — why every feature exists

The role, as the recruiter described it, line by line, and where Steward answers it. The demo page
in brackets. (The employer is private; this file names no company.)

| The role asks | Steward shows | Page |
|---|---|---|
| Automate data governance on GCP | Contracts compile to controls; Terraform; CI gates | 1, 8 |
| Metadata from owners, stewards, custodians | Contracts declare all three; catalog responsibilities | 1, 5 |
| Reverse-engineer legacy metadata | `legacy_crm_export`: profiling + proposed definitions + owner approval, under an expiring waiver | 1 |
| Automated harvesting and lineage from sources, ETL/ELT, reports | BigQuery jobs + Dataplex lineage + parsed LookML, cross-checked | 3 |
| Integrate Looker and Collibra | LookML → lineage → generated Collibra payload, idempotent, reconciled | 3, 5 |
| DQ rules, monitoring, reconciliation dashboards | Rules from contracts, quarantine with rule id, source = loaded + quarantined | 4 |
| GDPR, PII, anonymisation / de-anonymisation, retention | Value-based detection, policy tags + masking, tokenisation and controlled re-identification, retention compiled | 2, 7 |
| Access | Row policies, masking per role, grants with expiry | 2, 6 |
| Data Marketplace: onboarding, approvals, ownership changes, archival, report expiration | Listing → named approval → expiring grant; unused dashboards → expiry workflow | 6 |

## The 3-minute demo script (to rehearse with the author in T030)
1. (20 s) "A fictional operator on GCP. Contracts declare every dataset; everything else is generated."
2. (40 s) Privacy page: a column called `ref_2` held phone numbers; the value-based detector found it, the build failed until it was tagged. Then one query, three roles, three answers.
3. (40 s) Lineage page: source → table → LookML view → dashboard; one field resolves nowhere, one sensitive column reached a dashboard unmasked — both red.
4. (40 s) Catalog page: the Collibra payload, second sync = zero changes, the reconciliation report. Mode badge: MOCK (or REAL).
5. (20 s) Marketplace: a request approved by a named person, expiring; an expired grant flagged.
6. (20 s) Gates page: every gate and the mutation that proves it bites.

## Honest lines (say them first)
- "Collibra and Looker: not in production. I built against their documented model and APIs; the demo says MOCK where it is a mock."
- "GCP governance services: I learned them for this. My production-style GCP work is the telemetry pipeline on GKE, BigQuery, dbt."
- "BigQuery deletion isn't immediate: time travel and fail-safe keep data up to about two weeks; the retention report says so."
- "It's a reference build on synthetic data, deployed, captured and destroyed — not a client system."

## Interview scenarios this rehearses (job-application/prep/general/TECHNICAL-SCENARIOS.md)
153 slow BigQuery query · 155 lineage to Collibra · 156 DQ rules · 157 PII end to end · 158 pseudonymisation vs anonymisation · 159 retention · 160 Data Marketplace · 161 legacy metadata · 164 a governance control you built.
