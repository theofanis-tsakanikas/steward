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

## The 3-minute demo script (T030 — recorded demo, hosted or `make demo`)

Open the home page so the MOCK badge and “fictional operator” line are on screen before you speak.

1. (20 s) "A fictional European operator on GCP. Contracts declare every dataset; everything else is generated. The live estate was applied, captured and destroyed — what you are looking at is the evidence."
2. (40 s) Privacy: a column called `ref_2` held phone numbers; the value-based detector found it (the contract is never an input). Then one query, three roles, three answers. Live, BigQuery masked; offline we prove the compiled Terraform.
3. (40 s) Lineage: source → table → LookML view → dashboard; a field that resolves nowhere and a sensitive column that reached a dashboard unmasked are both red. Edges from jobs and from LookML are cross-checked, not merged.
4. (40 s) Catalog: the Collibra payload, second sync = zero changes, the reconciliation report. Say **MOCK** first. 91 assets in the fixture.
5. (20 s) Marketplace: a request approved by a named person, not the requester, with an expiry. An expired grant still present turns CI red.
6. (20 s) Gates: every gate is broken on purpose; the named gate must refuse it, for the right reason.

## Honest lines (say them first)
- "Collibra and Looker: not in production. I built against their documented model and APIs; the demo says MOCK where it is a mock."
- "GCP governance services: I learned them for this. My production-style GCP work is the telemetry pipeline on GKE, BigQuery, dbt."
- "BigQuery deletion isn't immediate: time travel and fail-safe keep data up to about two weeks; the retention report says so."
- "It's a reference build on synthetic data, deployed, captured and destroyed — not a client system."

## Interview scenarios this rehearses (job-application/prep/general/TECHNICAL-SCENARIOS.md)
153 slow BigQuery query · 155 lineage to Collibra · 156 DQ rules · 157 PII end to end · 158 pseudonymisation vs anonymisation · 159 retention · 160 Data Marketplace · 161 legacy metadata · 164 a governance control you built.
