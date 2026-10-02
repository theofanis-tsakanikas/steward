# INTERVIEW — why every feature exists

The role, as the recruiter described it, line by line, and where Steward answers it. The demo page
in brackets. (The employer is private; this file names no company.)

Hosted demo (public, no login): <https://steward-governance.streamlit.app>

| The role asks | Steward shows | Page |
|---|---|---|
| Automate data governance on GCP | Contracts compile to controls; Terraform; CI gates | 1, 8 |
| Metadata from owners, stewards, custodians | Contracts declare all three; catalog responsibilities | 1, 5 |
| Reverse-engineer legacy metadata | `legacy_crm_export`: profiling + proposed definitions + owner approval, under an expiring waiver | 1 |
| Automated harvesting and lineage from sources, ETL/ELT, reports | BigQuery jobs + Dataplex lineage + parsed LookML, cross-checked | 3 |
| Integrate Looker and Collibra | LookML → lineage → generated Collibra payload, idempotent, reconciled | 3, 5 |
| DQ rules, monitoring, reconciliation dashboards | Rules from contracts, quarantine with rule id, source = loaded + quarantined | 4 |
| GDPR, PII, anonymisation / de-anonymisation, retention | Value-based detection, policy tags + masking (hash, nullify, last-four), retention compiled | 2, 7 |
| Access | Row policies, masking per role, grants with expiry | 2, 6 |
| Data Marketplace: onboarding, approvals, ownership changes, archival, report expiration | Listing → named approval → expiring grant; unused dashboards → expiry workflow | 6 |

## The 3-minute demo script (to rehearse with the author in T030)

Open <https://steward-governance.streamlit.app> so the **MOCK** badge, the **fictional operator**
line, and the live-capture timestamps are on screen before you speak. Do not wait for a login.

1. **Home (20 s).** "A fictional European operator on GCP. YAML contracts declare every dataset;
   everything else is generated. We applied the estate, captured what BigQuery, DLP and Dataplex
   actually answered, then destroyed it. Each figure on this page says fixture or live, with that
   file's own date — not one banner date."
2. **Privacy (40 s).** Click Privacy. First the offline detector: a column called `ref_2` held
   phone numbers; values only, the contract is never an input — the recall numbers are on the
   page, read from the fixture. Scroll to **One query, three roles** — that block is a live
   capture. Same `SELECT` on `crm.customers`: the analyst gets hashed MSISDN, email
   `XXXXX@example.net`, GR rows only; the steward sees last-four MSISDN (`XXXXX6536` and the
   rest) and every country; fraud is denied that table (Access Denied). Optionally, the next
   query on that page is `network.usage_events`, which fraud *may* read in the clear — that is a
   second statement, not a substitute for the deny. Offline, the compiled seat × column check
   is the caption under the transcripts.
3. **Lineage (40 s).** Source → table → LookML view → dashboard. A field that resolves nowhere and
   a sensitive column that reached a dashboard unmasked are both red. Job-history edges and LookML
   edges are cross-checked, not merged. The job list at the top is live; the graph under it is the
   fixture.
4. **Catalog (30 s).** Say **MOCK** first. Generated payload; first sync sent changes, second
   sent none; the asset counts are the metrics on the page. The yellow banner is the point: no
   Collibra instance was called.
5. **Marketplace (20 s).** Live IAM bindings first (the estate's actual policy, then destroyed).
   A request becomes a grant only after a named human who is not the requester; every grant has
   an expiry; an expired grant still present turns CI red.
6. **Gates (10 s).** Every gate is broken on purpose; the named gate must refuse it, for the right
   reason. If there are ten seconds left, Live estate: the same captures re-judged offline, every
   check passes, no GCP account.

## Honest lines (say them first)

- "Collibra and Looker: not in production. I built against their documented model and APIs; the demo says MOCK where it is a mock."
- "GCP governance services: I learned them for this. My production-style GCP work is the telemetry pipeline on GKE, BigQuery, dbt."
- "BigQuery deletion isn't immediate: time travel and fail-safe keep data up to about two weeks; the retention report says so."
- "It's a reference build on synthetic data, deployed, captured and destroyed — not a client system."

## Interview scenarios this rehearses

Slow BigQuery query · lineage to the catalog · DQ rules · PII end to end · pseudonymisation vs hashing · retention · Data Marketplace · legacy metadata · a governance control you built.

Dry-run against the hosted URL: 2026-10-02 (session, pages walked, timings above). Speaking rehearsal with the author is still open (T030 / D8).
